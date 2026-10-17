"""Where each number on the dashboard comes from, and how fresh it is.

Every source reports: what it feeds, where it comes from, when it last arrived, when the next update is
due and whether that is late. Nothing here is estimated: a source that never delivered says "never".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waitwhy.models import (
    AnalyticsSnapshot,
    Expense,
    PlatformPost,
    ProviderUsage,
    RevenueTransaction,
    SystemSetting,
    WorkflowJob,
)

PLATFORM_ORIGIN = {
    "youtube": "YouTube Data API (views, likes, comments) + YouTube Analytics API (shares, watch time, subscribers)",
    "instagram": "Instagram Graph API, Reel insights",
    "facebook": "Facebook Graph API, Reel insights",
    "tiktok": "TikTok API",
}


PLATFORM_NAMES = {"youtube": "YouTube", "instagram": "Instagram", "facebook": "Facebook", "tiktok": "TikTok"}


def platform_name(p: str) -> str:
    return PLATFORM_NAMES.get(p, p.capitalize())


@dataclass
class Source:
    key: str
    name: str            # what the data is
    origin: str          # where it comes from
    last_at: datetime | None
    next_at: datetime | None = None
    late_after_h: float | None = None   # older than this = stale (None = updates only when someone acts)
    detail: str = ""     # last run's outcome, errors, or why there is nothing
    state: str = ""      # fresh | stale | never (expected but missing) | manual | none (nothing yet, none due) | off

    def __post_init__(self):
        if self.state:
            return
        if self.last_at is None:
            self.state = "never" if self.late_after_h else "none"
        elif self.late_after_h is None:
            self.state = "manual"
        else:
            age_h = (datetime.now(timezone.utc) - self.last_at).total_seconds() / 3600
            self.state = "fresh" if age_h <= self.late_after_h else "stale"


def parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _last_job(session: Session, job_type: str) -> WorkflowJob | None:
    return session.execute(select(WorkflowJob).where(WorkflowJob.type == job_type,
                                                     WorkflowJob.status.in_(["succeeded", "dead", "failed"]))
                           .order_by(WorkflowJob.finished_at.desc().nulls_last())).scalars().first()


def _next_run(cfg: dict, job_type: str) -> datetime | None:
    from waitwhy.jobs.scheduler import Cron
    spec = cfg.get("schedules", {}).get(job_type)
    if not spec:
        return None
    tz = ZoneInfo(cfg.get("timezone", "UTC"))
    nxt = Cron(spec["cron"]).next_slot(datetime.now(tz))
    return nxt.astimezone(timezone.utc) if nxt else None


def _job_detail(job: WorkflowJob | None) -> str:
    if job is None:
        return "has not run yet"
    when = job.finished_at.strftime("%d %b %H:%M UTC") if job.finished_at else "?"
    if job.status != "succeeded":
        return f"last run {when} failed: {(job.last_error or job.status)[:160]}"
    r = job.result or {}
    errs = r.get("errors") or []
    if errs:
        return f"last run {when}: {len(errs)} error(s): " + "; ".join(map(str, errs))[:200]
    return f"last run {when} OK"


def analytics_sources(session: Session, cfg: dict) -> list[Source]:
    """One row per platform that is switched on or has posts."""
    from waitwhy.agents.coo import credential_status
    creds = credential_status()
    job = _last_job(session, "analytics_collect")
    nxt = _next_run(cfg, "analytics_collect")
    posted = {p for (p,) in session.execute(select(PlatformPost.platform).where(
        PlatformPost.is_mock.is_(False), PlatformPost.published_at.is_not(None)).distinct())}
    out = []
    for platform, pc in cfg.get("platforms", {}).items():
        enabled = bool(pc.get("enabled"))
        if not enabled and platform not in posted:
            continue
        last = session.execute(select(func.max(AnalyticsSnapshot.captured_at)).join(
            PlatformPost, PlatformPost.id == AnalyticsSnapshot.platform_post_id).where(
            PlatformPost.platform == platform, AnalyticsSnapshot.is_mock.is_(False))).scalar()
        name = f"{platform_name(platform)} stats"
        if platform == "tiktok" and not creds.get("tiktok_direct_post"):
            out.append(Source(platform, name, "Not collected: TikTok is posted by hand and has no stats connection. "
                              "Check numbers in the TikTok app.", last, state="off"))
            continue
        if not creds.get(platform):
            out.append(Source(platform, name, PLATFORM_ORIGIN.get(platform, platform), last, nxt, 13,
                              f"not connected on the Mac ({platform} credentials missing)", state="stale"))
            continue
        detail = _job_detail(job)
        if platform not in posted:
            detail = "nothing posted here yet, so nothing to read"
        out.append(Source(platform, name, PLATFORM_ORIGIN.get(platform, platform), last, nxt,
                          13 if platform in posted else None, detail,
                          state="" if platform in posted else ("manual" if last else "none")))
    return out


def all_sources(session: Session, cfg: dict) -> list[Source]:
    out = analytics_sources(session, cfg)

    imp = _last_job(session, "import_episodes")
    git = "channel/episodes.json on GitHub (main): the Mac pulls it every 15 min and imports every 30 min"
    out.append(Source("episodes", "New episodes", git, imp.finished_at if imp else None,
                      _next_run(cfg, "import_episodes"), 1.5, _job_detail(imp)))

    usage = session.execute(select(func.max(ProviderUsage.created_at)).where(ProviderUsage.is_mock.is_(False))).scalar()
    exp = session.execute(select(func.max(Expense.created_at))).scalar()
    cost_last = max([t for t in (usage, exp) if t], default=None)
    out.append(Source("costs", "Costs", "Credits each episode reports in episodes.json, plus expenses you add on "
                      "the Finance page", cost_last, detail="updates when an episode is imported or you add one"))

    rev = session.execute(select(func.max(RevenueTransaction.created_at))).scalar()
    out.append(Source("revenue", "Revenue", "Only what you record on the Finance page", rev,
                      detail="no revenue recorded yet" if rev is None else ""))

    health = (session.get(SystemSetting, "last_health") or SystemSetting(value=None)).value or {}
    out.append(Source("health", "System health", "Health check job on the Mac mini", parse_ts(health.get("checked_at")),
                      _next_run(cfg, "health_check"), 26))

    hb = session.get(SystemSetting, "scheduler_heartbeat")
    out.append(Source("scheduler", "Mac scheduler", "Heartbeat from the scheduler service on the Mac mini",
                      parse_ts(hb.value if hb else None), late_after_h=0.1,
                      detail="beats every 20 s while the Mac is on and the service runs"))
    return out


def views_freshness(sources: list[Source]) -> dict:
    """Short summary for page headers: newest stats time and which platforms it came from."""
    stats = [s for s in sources if s.key in PLATFORM_ORIGIN and s.state != "off"]
    times = [s.last_at for s in stats if s.last_at]
    return {"last_at": max(times) if times else None,
            "from": [s.key for s in stats if s.last_at],
            "stale": any(s.state in ("stale", "never") and s.late_after_h for s in stats),
            "next_at": min([s.next_at for s in stats if s.next_at], default=None)}


def ago(dt: datetime | None, now: datetime | None = None) -> str:
    if dt is None:
        return "never"
    now = now or datetime.now(timezone.utc)
    secs = (now - dt).total_seconds()
    future = secs < 0
    secs = abs(secs)
    if secs < 60:
        return "in under a minute" if future else "just now"
    for unit, size in (("d", 86400), ("h", 3600), ("min", 60)):
        if secs >= size:
            n = int(secs // size)
            if unit == "h" and n < 10 and secs % 3600 >= 60 * 10:
                txt = f"{n} h {int(secs % 3600 // 60)} min"
            else:
                txt = f"{n} {unit}"
            return f"in {txt}" if future else f"{txt} ago"
    return ""

