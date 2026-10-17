"""Recurring task scheduler (cron syntax, evaluated in the owner's timezone).

Each due slot is enqueued with idempotency key ``sched:<name>:<slot>`` so running several scheduler
instances, or restarting one, can never double-run a task. After downtime, the most recent missed
slot (within ``catch_up``) is run once - e.g. a 09:00 report is still sent if the server was down at 9.
"""
from __future__ import annotations

import logging
import signal
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from waitwhy.db import session_scope
from waitwhy.jobs import queue
from waitwhy.settings import get_config

log = logging.getLogger("waitwhy.scheduler")

_DOW = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/")
            step = int(step_s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a_s, b_s = part.split("-")
            a, b = int(_DOW.get(a_s, a_s)), int(_DOW.get(b_s, b_s))
        else:
            a = b = int(_DOW.get(part, part))
        out.update(range(a, b + 1, step))
    return out


class Cron:
    def __init__(self, expr: str):
        m, h, dom, mon, dow = expr.split()
        self.minutes = _parse_field(m, 0, 59)
        self.hours = _parse_field(h, 0, 23)
        self.dom = _parse_field(dom, 1, 31)
        self.months = _parse_field(mon, 1, 12)
        self.dow = {d % 7 for d in _parse_field(dow, 0, 7)}
        self.dom_any, self.dow_any = dom == "*", dow == "*"

    def matches(self, t: datetime) -> bool:
        if t.minute not in self.minutes or t.hour not in self.hours or t.month not in self.months:
            return False
        cron_dow = (t.weekday() + 1) % 7  # python Monday=0 -> cron Sunday=0
        dom_ok, dow_ok = t.day in self.dom, cron_dow in self.dow
        if self.dom_any or self.dow_any:
            return dom_ok and dow_ok
        return dom_ok or dow_ok  # standard cron semantics when both are restricted

    def _day_ok(self, t: datetime) -> bool:
        if t.month not in self.months:
            return False
        dom_ok, dow_ok = t.day in self.dom, (t.weekday() + 1) % 7 in self.dow
        return dom_ok and dow_ok if (self.dom_any or self.dow_any) else dom_ok or dow_ok

    def next_slot(self, now: datetime, horizon: timedelta = timedelta(days=40)) -> datetime | None:
        t = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        end = now + horizon
        while t <= end:  # skip whole days and hours that can't match, so monthly jobs stay cheap
            if not self._day_ok(t):
                t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            elif t.hour not in self.hours:
                t = (t + timedelta(hours=1)).replace(minute=0)
            elif self.matches(t):
                return t
            else:
                t += timedelta(minutes=1)
        return None

    def last_slot(self, now: datetime, lookback: timedelta) -> datetime | None:
        t = now.replace(second=0, microsecond=0)
        end = now - lookback
        while t >= end:
            if self.matches(t):
                return t
            t -= timedelta(minutes=1)
        return None


_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def describe(expr: str) -> str:
    """Plain-words version of the cron shapes used in company.yaml; anything else is shown as is."""
    m, h, dom, mon, dow = expr.split()
    if m.startswith("*/") and h == dom == mon == dow == "*":
        return f"every {m[2:]} min"
    if m.isdigit() and h == dom == mon == dow == "*":
        return f"every hour at :{int(m):02d}"
    if not (m.isdigit() and mon == "*" and all(x.isdigit() for x in h.split(","))):
        return expr
    times = ", ".join(f"{int(x):02d}:{int(m):02d}" for x in h.split(","))
    if dom == "*" and dow == "*":
        return f"daily at {times}"
    if dom == "*" and dow.isdigit():
        return f"{_DAYS[int(dow) % 7]}s at {times}"
    if dom.isdigit() and dow == "*":
        return f"day {dom} of each month at {times}"
    return expr


def due_jobs(now_local: datetime, schedules: dict[str, dict], catch_up: timedelta = timedelta(hours=6)):
    for name, spec in schedules.items():
        cron = Cron(spec["cron"])
        lookback = timedelta(minutes=10) if spec["cron"].startswith("*/") else catch_up
        slot = cron.last_slot(now_local, lookback)
        if slot is not None:
            yield name, slot


def tick(now: datetime | None = None) -> list[str]:
    """Enqueue every due scheduled job exactly once. Returns the idempotency keys touched."""
    with session_scope() as session:
        cfg = get_config(session)
        tz = ZoneInfo(cfg.get("timezone", "Asia/Jerusalem"))
        now_local = (now or datetime.now(tz)).astimezone(tz)
        keys = []
        for name, slot in due_jobs(now_local, cfg.get("schedules", {})):
            key = f"sched:{name}:{slot.isoformat()}"
            queue.enqueue(session, name, {"slot": slot.isoformat()}, idempotency_key=key)
            keys.append(key)
        return keys


def run_forever(interval_s: float = 20.0) -> None:
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    log.info("scheduler started")
    while not stop.is_set():
        try:
            tick()
            with session_scope() as s:
                from waitwhy.models import SystemSetting
                row = s.get(SystemSetting, "scheduler_heartbeat")
                stamp = datetime.now(ZoneInfo("UTC")).isoformat()
                if row:
                    row.value = stamp
                else:
                    s.add(SystemSetting(key="scheduler_heartbeat", value=stamp, updated_by="scheduler"))
        except Exception:  # noqa: BLE001 - scheduler must keep ticking
            log.exception("scheduler tick failed")
        stop.wait(interval_s)
    log.info("scheduler stopped")
