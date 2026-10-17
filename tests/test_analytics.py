from datetime import datetime, timedelta, timezone

from tests import factories as f
from waitwhy.analytics import metrics as m
from waitwhy.models import AnalyticsSnapshot, PlatformPost, PublicationJob


def _post(session, cfg, platform="youtube", age_h=200):
    v = f.ready_video(session, cfg)
    pj = PublicationJob(video_id=v.id, video_version_id=v.current_version_id, platform=platform,
                        idempotency_key=f"pub:{v.id}:{platform}", status="published", dry_run=False)
    session.add(pj)
    session.flush()
    p = PlatformPost(publication_job_id=pj.id, video_id=v.id, platform=platform, external_id=str(v.id),
                     privacy_status="public", is_public=True,
                     published_at=datetime.now(timezone.utc) - timedelta(hours=age_h))
    session.add(p)
    session.flush()
    return p


def test_window_metrics_only_when_observable(session, cfg):
    p = _post(session, cfg, age_h=30)
    session.add(AnalyticsSnapshot(platform_post_id=p.id, hours_since_publish=26, views=1000, likes=50))
    session.flush()
    pm = m.post_metrics(session, p)
    assert pm.windows["24h"] == 1000
    assert pm.windows["7d"] is None          # a 30-hour-old post has no 7-day value yet
    assert pm.rates["likes_per_1k"] == 50.0


def test_unavailable_metrics_stay_null_not_zero(session, cfg):
    p = _post(session, cfg)
    session.add(AnalyticsSnapshot(platform_post_id=p.id, hours_since_publish=170, views=500, saves=None))
    session.flush()
    pm = m.post_metrics(session, p)
    assert pm.latest["saves"] is None and pm.rates["saves_per_1k"] is None


def test_cohorts_flag_small_samples_and_never_pool_platforms(session, cfg):
    for plat in ("youtube", "instagram"):
        p = _post(session, cfg, platform=plat)
        session.add(AnalyticsSnapshot(platform_post_id=p.id, hours_since_publish=170, views=100))
    session.flush()
    rows = m.all_post_metrics(session)
    stats = m.cohort_stats(rows, "category")
    assert {s["platform"] for s in stats} == {"youtube", "instagram"}
    assert all(not s["sufficient"] for s in stats)


def test_views_timeline_sums_posts_and_carries_readings_forward(session, cfg):
    now = datetime.now(timezone.utc)
    a, b = _post(session, cfg, age_h=30), _post(session, cfg, age_h=30)
    session.add_all([
        AnalyticsSnapshot(platform_post_id=a.id, captured_at=now - timedelta(hours=24), hours_since_publish=6, views=100),
        AnalyticsSnapshot(platform_post_id=a.id, captured_at=now - timedelta(hours=1), hours_since_publish=29, views=300),
        AnalyticsSnapshot(platform_post_id=b.id, captured_at=now - timedelta(hours=12), hours_since_publish=18, views=50),
    ])
    session.flush()
    t = m.views_timeline(session)
    assert t["step_h"] == 6                      # short history: 6-hour buckets
    yt = t["series"]["youtube"]
    assert yt[0] == 100                          # only post a has a reading yet
    assert yt[-1] == 350                         # a's newest (300) + b carried forward (50)
    assert yt == sorted(yt)                      # carrying forward never dips


def test_totals_stay_none_when_no_post_reports_a_metric(session, cfg):
    p = _post(session, cfg)
    session.add(AnalyticsSnapshot(platform_post_id=p.id, hours_since_publish=170, views=500, likes=10))
    session.flush()
    t = m.totals(m.all_post_metrics(session))
    assert t["views"] == 500 and t["likes"] == 10 and t["saves"] is None
