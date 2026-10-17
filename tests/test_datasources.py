from datetime import datetime, timedelta, timezone

from tests.test_analytics import _post
from waitwhy import datasources as ds
from waitwhy.jobs.scheduler import Cron
from waitwhy.models import AnalyticsSnapshot, SystemSetting, WorkflowJob


def test_source_states():
    now = datetime.now(timezone.utc)
    assert ds.Source("x", "X", "o", now - timedelta(hours=1), late_after_h=13).state == "fresh"
    assert ds.Source("x", "X", "o", now - timedelta(hours=20), late_after_h=13).state == "stale"
    assert ds.Source("x", "X", "o", None, late_after_h=13).state == "never"
    assert ds.Source("x", "X", "o", None).state == "none"          # nothing due, nothing yet: not a warning
    assert ds.Source("x", "X", "o", now).state == "manual"


def test_ago():
    now = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
    assert ds.ago(None) == "never"
    assert ds.ago(now - timedelta(seconds=20), now) == "just now"
    assert ds.ago(now - timedelta(minutes=5), now) == "5 min ago"
    assert ds.ago(now - timedelta(hours=3, minutes=20), now) == "3 h 20 min ago"
    assert ds.ago(now - timedelta(days=2), now) == "2 d ago"
    assert ds.ago(now + timedelta(hours=2), now) == "in 2 h"


def test_next_slot():
    t = datetime(2026, 10, 17, 8, 0)
    assert Cron("30 1,7,13,19 * * *").next_slot(t) == datetime(2026, 10, 17, 13, 30)


def test_sources_report_last_stats_time_and_origin(session, cfg):
    p = _post(session, cfg, platform="youtube")
    at = datetime.now(timezone.utc) - timedelta(hours=2)
    session.add(AnalyticsSnapshot(platform_post_id=p.id, captured_at=at, hours_since_publish=10, views=5))
    session.add(WorkflowJob(type="analytics_collect", status="succeeded", finished_at=at, result={"errors": []}))
    session.add(SystemSetting(key="scheduler_heartbeat", value=datetime.now(timezone.utc).isoformat(), updated_by="t"))
    session.flush()
    srcs = {s.key: s for s in ds.all_sources(session, cfg)}
    yt = srcs["youtube"]
    assert abs((yt.last_at - at).total_seconds()) < 1
    assert "YouTube Data API" in yt.origin and yt.next_at is not None
    assert srcs["scheduler"].state == "fresh"
    assert srcs["revenue"].state == "none"
    fresh = ds.views_freshness(list(srcs.values()))
    assert fresh["from"] == ["youtube"] and abs((fresh["last_at"] - at).total_seconds()) < 1


def test_manual_refresh_rereads_recent_posts(session, cfg, monkeypatch):
    from waitwhy.analytics import ingest
    p = _post(session, cfg)
    session.add(AnalyticsSnapshot(platform_post_id=p.id, captured_at=datetime.now(timezone.utc) - timedelta(hours=1),
                                  hours_since_publish=199, views=5))
    session.flush()

    class A:
        def fetch_metrics(self, _):
            return {"views": 9}
    monkeypatch.setattr(ingest, "adapter_for", lambda *a: A())
    assert ingest.collect(session, cfg)["skipped_recent"] == 1            # scheduled run: an hour is too recent
    assert ingest.collect(session, cfg, min_gap_hours=0.25)["snapshots"] == 1


def test_describe_cron():
    from waitwhy.jobs.scheduler import describe
    assert describe("*/30 * * * *") == "every 30 min"
    assert describe("15 * * * *") == "every hour at :15"
    assert describe("30 1,7,13,19 * * *") == "daily at 01:30, 07:30, 13:30, 19:30"
    assert describe("0 10 * * 0") == "Suns at 10:00"
    assert describe("0 10 1 * *") == "day 1 of each month at 10:00"


def test_schedule_overview_lists_every_timed_job(session, cfg):
    rows = ds.schedule_overview(session, cfg)
    assert {r["name"] for r in rows} == set(cfg["schedules"])
    assert all(r["next_at"] for r in rows) and all(r["purpose"] for r in rows)


def test_next_slot_monthly_and_weekly():
    t = datetime(2026, 10, 17, 8, 0)   # a Saturday
    assert Cron("0 10 1 * *").next_slot(t) == datetime(2026, 11, 1, 10, 0)
    assert Cron("0 10 * * 0").next_slot(t) == datetime(2026, 10, 18, 10, 0)
    assert Cron("*/5 * * * *").next_slot(t) == datetime(2026, 10, 17, 8, 5)
