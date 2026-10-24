import pytest
from datetime import datetime, timezone

from tests import factories as f
from tests.conftest import set_setting
from waitwhy.errors import AuthError, PolicyError, TransientError
from waitwhy.jobs.worker import Worker
from waitwhy.models import Notification, PlatformPost, PublicationJob, Video, WorkflowJob
from waitwhy.publishing import adapters as ad
from waitwhy.publishing import service as pub
from waitwhy.settings import get_config


@pytest.fixture(autouse=True)
def all_platforms_on(session):
    """These tests cover all four adapters; the live config may have some switched off."""
    set_setting(session, "platforms", {p: {"enabled": True} for p in ("youtube", "instagram", "facebook", "tiktok")})


def _publish_all(session):
    for j in session.query(WorkflowJob).filter_by(type="publish", status="queued").all():
        j.run_at = datetime.now(timezone.utc)
    session.commit()
    Worker(worker_id="t", types=["publish"]).run_until_idle()
    session.expire_all()


def test_independent_platform_statuses(session, cfg):
    """Video OK; Instagram fails; YouTube succeeds; TikTok needs manual action."""
    set_setting(session, "mock_publish_scenario", {"youtube": "ok", "instagram": "fail_permanent",
                                                   "facebook": "ok", "tiktok": "manual"})
    v = f.ready_video(session, cfg)
    pub.schedule_video(session, get_config(session), v, "test")
    session.commit()
    _publish_all(session)
    st = {j.platform: j.status for j in session.query(PublicationJob).all()}
    assert st == {"youtube": "published", "instagram": "failed", "facebook": "published",
                  "tiktok": "manual_action_required"}
    assert session.query(PlatformPost).count() == 2
    assert session.get(Video, v.id).state == "PUBLISHED"
    assert session.query(WorkflowJob).filter_by(type="publish", status="dead").count() == 1


def test_no_public_post_means_not_published(session, cfg):
    set_setting(session, "mock_publish_scenario", {"youtube": "private", "instagram": "fail_permanent",
                                                   "facebook": "fail_permanent", "tiktok": "manual"})
    v = f.ready_video(session, cfg)
    pub.schedule_video(session, get_config(session), v, "test")
    session.commit()
    _publish_all(session)
    v = session.get(Video, v.id)
    assert v.state == "BLOCKED"            # a private upload is never reported as a publication
    assert "youtube=private_uploaded" in v.blocked_reason
    tj = session.query(PublicationJob).filter_by(platform="tiktok").one()
    pub.mark_manually_published(session, tj, "https://www.tiktok.com/@waitwhy/video/1", None, "user:test")
    session.commit()
    assert session.get(Video, v.id).state == "PUBLISHED"


def test_duplicate_publication_is_prevented(session, cfg):
    set_setting(session, "mock_publish_scenario", {"youtube": "ok"})
    v = f.ready_video(session, cfg)
    c = get_config(session)
    pub.schedule_video(session, c, v, "test")
    pub.schedule_video(session, c, v, "test")   # scheduling twice: still one job per platform
    session.commit()
    assert session.query(PublicationJob).filter_by(platform="youtube").count() == 1
    pj = session.query(PublicationJob).filter_by(platform="youtube").one()
    calls = []
    orig = ad.MockAdapter.publish
    ad.MockAdapter.publish = lambda self, req: calls.append(1) or orig(self, req)
    try:
        assert pub.publish(session, c, pj) == "published"
        assert pub.publish(session, c, pj) == "published"   # retry of a finished job is a no-op
    finally:
        ad.MockAdapter.publish = orig
    assert len(calls) == 1
    assert session.query(PlatformPost).filter_by(platform="youtube").count() == 1


def test_interrupted_upload_is_not_blindly_retried(session, cfg):
    v = f.ready_video(session, cfg)
    c = get_config(session)
    pub.schedule_video(session, c, v, "test")
    pj = session.query(PublicationJob).filter_by(platform="youtube").one()
    pj.status = "uploading"                      # worker died mid-upload
    session.commit()
    assert pub.publish(session, c, pj) == "blocked"
    assert any("Verify youtube upload" in n.title for n in session.query(Notification).all())


def test_failed_upload_retries_then_succeeds(session, cfg):
    set_setting(session, "mock_publish_scenario", {"youtube": "fail_transient"})
    v = f.ready_video(session, cfg)
    c = get_config(session)
    pub.schedule_video(session, c, v, "test")
    pj = session.query(PublicationJob).filter_by(platform="youtube").one()
    with pytest.raises(TransientError):
        pub.publish(session, c, pj)
    assert pj.status == "scheduled" and pj.attempts == 1
    set_setting(session, "mock_publish_scenario", {"youtube": "ok"})
    assert pub.publish(session, get_config(session), pj) == "published"


def test_expired_auth_fails_fast_and_alerts(session, cfg):
    set_setting(session, "mock_publish_scenario", {"instagram": "fail_auth"})
    v = f.ready_video(session, cfg)
    c = get_config(session)
    pub.schedule_video(session, c, v, "test")
    pj = session.query(PublicationJob).filter_by(platform="instagram").one()
    with pytest.raises(AuthError):
        pub.publish(session, c, pj)
    assert pj.status == "failed" and pj.error_class == "auth"
    assert any("integration disconnected" in n.title for n in session.query(Notification).all())


def test_youtube_expired_refresh_token(monkeypatch):
    class R:
        status_code, text = 400, '{"error":"invalid_grant"}'
    monkeypatch.setattr(ad.httpx, "post", lambda *a, **k: R())
    with pytest.raises(AuthError, match="expired or revoked"):
        ad.YouTubeAdapter("id", "secret", "refresh", "api")._token()


def test_publication_requires_human_approval(session, cfg):
    v = f.ready_video(session, cfg, approved=False)
    with pytest.raises(PolicyError, match="approval"):
        pub.schedule_video(session, cfg, v, "test")


def test_live_mode_refuses_non_publishable_version(session, cfg):
    set_setting(session, "dry_run_mode", False)
    v = f.ready_video(session, cfg, publishable=False)
    with pytest.raises(PolicyError, match="not publishable"):
        pub.schedule_video(session, get_config(session), v, "test")


def test_tiktok_defaults_to_manual_handoff():
    out = ad.TikTokAdapter("", audited=False, mode="pending_compliance_review").publish(None)
    assert out.status == "manual_action_required" and not out.is_public


def test_supervised_mode_never_auto_approves(session, cfg):
    from waitwhy.pipeline import _auto_approvable
    v = f.ready_video(session, cfg, approved=False)
    c = dict(cfg, operating_mode="supervised", content_approval_required=False, auto_publish_enabled=True)

    class Rv:
        passed, score = True, 100
    assert _auto_approvable(session, c, v, Rv()) is False
    c2 = dict(cfg, operating_mode="controlled", content_approval_required=False, auto_publish_enabled=True)
    assert _auto_approvable(session, c2, v, Rv()) is True
    v.is_sponsored = True
    assert _auto_approvable(session, c2, v, Rv()) is False   # sponsored content always needs a human


def test_imported_episode_uses_its_cdn_copy_for_instagram():
    class NoPublicStorage:
        def public_url(self, key, expires_s=3600):
            return None

    class Bucket:
        def public_url(self, key, expires_s=3600):
            return f"https://media.example/{key}"

    from waitwhy.models import VideoVersion
    cdn = "https://d2ol7oe51mr4n9.cloudfront.net/u/ep1.mp4"
    imported = VideoVersion(storage_key="videos/x/v1.mp4", manifest={"source_url": cdn})
    rendered = VideoVersion(storage_key="videos/y/v1.mp4", manifest={})
    assert pub.public_video_url(NoPublicStorage(), imported) == cdn
    assert pub.public_video_url(NoPublicStorage(), rendered) is None
    assert pub.public_video_url(Bucket(), imported) == cdn               # the QC'd CDN copy comes first
    assert pub.public_video_url(Bucket(), rendered) == "https://media.example/videos/y/v1.mp4"

    class LanServer:  # PUBLIC_BASE_URL=http://mac.local:8000: unreachable for Instagram (2026-10-16)
        def public_url(self, key, expires_s=3600):
            return f"http://atlass-mac-mini.local:8000/public-media/{key}"
    assert pub.public_video_url(LanServer(), imported) == cdn
    assert pub.public_video_url(LanServer(), rendered) is None
    assert pub.public_video_url(NoPublicStorage(),
                                VideoVersion(storage_key="k", manifest={"source_url": "file:///tmp/a.mp4"})) is None


def test_job_scheduled_in_dry_run_publishes_live_after_switch(session, cfg, monkeypatch):
    """Owner turns dry-run off after a video was scheduled: the post is real, so it is recorded as real."""
    set_setting(session, "mock_publish_scenario", {"youtube": "ok"})
    v = f.ready_video(session, cfg)
    pub.schedule_video(session, get_config(session), v, "test")
    session.commit()
    pj = session.query(PublicationJob).filter_by(platform="youtube").one()
    assert pj.dry_run
    set_setting(session, "dry_run_mode", False)
    live = get_config(session)
    seen = []
    monkeypatch.setattr(pub, "adapter_for", lambda s, c, p: seen.append(c["dry_run_mode"])
                        or ad.MockAdapter(p, {"youtube": "ok"}))
    assert pub.publish(session, live, pj) == "published"
    assert seen == [False] and pj.dry_run is False
    assert session.query(PlatformPost).filter_by(platform="youtube").one().is_mock is False


def test_job_for_platform_switched_off_after_scheduling_is_cancelled(session, cfg):
    set_setting(session, "mock_publish_scenario", {"facebook": "ok"})
    v = f.ready_video(session, cfg)
    pub.schedule_video(session, get_config(session), v, "test")
    session.commit()
    set_setting(session, "platforms", {"facebook": {"enabled": False}})
    pj = session.query(PublicationJob).filter_by(platform="facebook").one()
    assert pub.publish(session, get_config(session), pj) == "cancelled"
    assert session.query(PlatformPost).filter_by(platform="facebook").count() == 0
    assert session.query(Notification).count() == 0


def test_database_times_are_utc_and_calendar_shows_owner_time(session, cfg):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from waitwhy.api.app import app
    assert session.execute(text("SHOW timezone")).scalar() == "UTC"
    v = f.ready_video(session, cfg)
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    at = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=16, minute=0, second=0, microsecond=0)
    pub.schedule_video(session, get_config(session), v, "test", at=at)   # the calendar shows the last 7 days on
    session.commit()
    local = at.astimezone(ZoneInfo("Asia/Jerusalem")).strftime("%H:%M")  # 19:00 in summer, 18:00 in winter
    r = TestClient(app).get("/calendar", auth=("ceo", "test-pass"))
    assert r.status_code == 200 and f"{local} Jerusalem · 16:00 UTC" in r.text


def test_manual_action_alert_links_to_the_dashboard(session, cfg):
    set_setting(session, "mock_publish_scenario", {"tiktok": "manual"})
    set_setting(session, "dry_run_mode", False)
    set_setting(session, "dashboard_url", "https://studio.example/")
    v = f.ready_video(session, cfg)
    c = get_config(session)
    pub.schedule_video(session, c, v, "test")
    pj = session.query(PublicationJob).filter_by(platform="tiktok").one()
    orig = pub.adapter_for
    pub.adapter_for = lambda s, cc, p: ad.MockAdapter(p, {"tiktok": "manual"})
    try:
        assert pub.publish(session, c, pj) == "manual_action_required"
    finally:
        pub.adapter_for = orig
    n = session.query(Notification).filter(Notification.title.like("Action needed: tiktok%")).one()
    assert n.severity == "high" and "\n\nOpen: https://studio.example/calendar" in n.body


def test_platform_switched_back_on_catches_up_missed_videos(session, cfg):
    set_setting(session, "platforms", {"instagram": {"enabled": False}})
    first, second = f.ready_video(session, cfg), f.ready_video(session, cfg)
    c = get_config(session)
    pub.schedule_video(session, c, first, "test")
    session.commit()
    ig = session.query(PublicationJob).filter_by(video_id=first.id, platform="instagram").one_or_none()
    assert ig is None                                   # scheduled while Instagram was off
    other = session.query(PublicationJob).filter_by(video_id=first.id, platform="youtube").one()
    pub.schedule_video(session, get_config(session), second, "test")
    set_setting(session, "platforms", {"instagram": {"enabled": True}})
    session.commit()
    # second video's Instagram job existed only as one cancelled because the platform was off
    sec = session.query(PublicationJob).filter_by(video_id=second.id, platform="youtube").one()
    pj2 = PublicationJob(video_id=second.id, video_version_id=sec.video_version_id, platform="instagram",
                         idempotency_key=f"pub:{second.id}:instagram", status="cancelled", scheduled_at=sec.scheduled_at,
                         last_error=f"instagram {pub.SWITCHED_OFF}", metadata_={})
    session.add(pj2)
    session.commit()
    out = pub.catch_up_platforms(session, get_config(session))
    assert len(out) == 2 and all(":instagram@" in o for o in out)
    jobs = session.query(PublicationJob).filter_by(platform="instagram").all()
    assert {j.status for j in jobs} == {"scheduled"}
    slots = {j.scheduled_at for j in jobs} | {other.scheduled_at, sec.scheduled_at}
    assert len(slots) == 4                              # each catch-up post gets its own free slot
    assert pub.catch_up_platforms(session, get_config(session)) == []   # idempotent


def test_owner_cancelled_job_is_not_revived(session, cfg):
    v = f.ready_video(session, cfg)
    pub.schedule_video(session, get_config(session), v, "test")
    pj = session.query(PublicationJob).filter_by(platform="instagram").one()
    pj.status = "cancelled"
    session.commit()
    assert pub.catch_up_platforms(session, get_config(session)) == []


def test_post_text_merges_dedupes_and_caps_hashtags():
    tags = ["#shorts", "#traffic", "#science", "#physics", "#claymation", "#cars"]
    cap = "The jam with no cause. #shorts #traffic #science #physics #claymation"
    tt = ad.post_text(cap, tags, "tiktok")
    assert tt == "The jam with no cause.\n\n#traffic #science #physics #claymation #cars"
    yt = ad.post_text(cap, tags, "youtube")
    assert yt.split("\n\n")[1].split() == ["#shorts", "#traffic", "#science", "#physics", "#claymation"]
    assert ad.post_text("Plain caption", [], "instagram") == "Plain caption"


def test_tiktok_package_has_portrait_cover_and_five_tags(session, cfg, tmp_path):
    import io
    import zipfile

    from fastapi.testclient import TestClient
    from PIL import Image

    from waitwhy.api.app import app
    from waitwhy.providers import registry
    v = f.ready_video(session, cfg)
    store = registry.storage(cfg)
    thumb = tmp_path / "thumb.png"
    Image.new("RGB", (5504, 3072), (90, 160, 220)).save(thumb)
    vv = session.get(f.VideoVersion, v.current_version_id)
    vv.thumbnail_key = store.put_file(thumb, f"videos/{v.slug}/thumb.png")
    v.publish_metadata = {**v.publish_metadata, "tiktok_caption": "Why jams happen. #shorts #traffic #science",
                          "hashtags": ["#shorts", "#traffic", "#science", "#physics", "#claymation", "#cars"]}
    pub.schedule_video(session, get_config(session), v, "test")
    session.commit()
    pj = session.query(PublicationJob).filter_by(platform="tiktok").one()
    r = TestClient(app).get(f"/publications/{pj.id}/package", auth=("ceo", "test-pass"))
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    cover = Image.open(io.BytesIO(z.read("cover.jpg")))
    assert cover.size == (1080, 1920) and cover.format == "JPEG" and len(z.read("cover.jpg")) < 2_000_000
    caption = z.read("caption.txt").decode()
    tags = caption.split("\n\n")[1].split()
    assert len(tags) == 5 and "#shorts" not in tags and len(set(tags)) == 5


def test_calendar_speaks_plainly(session, cfg):
    """Owner's screenshot 2026-10-16: an off platform read as 'cancelled', stale 'dry run' tags after
    going live, and a video that failed QC missing from the calendar with no explanation."""
    from fastapi.testclient import TestClient

    from waitwhy.api.app import app
    from waitwhy.models import QualityReview
    v = f.ready_video(session, cfg)
    pub.schedule_video(session, get_config(session), v, "test")       # scheduled while dry-run is on
    fb = session.query(PublicationJob).filter_by(platform="facebook").one()
    fb.status, fb.last_error = "cancelled", f"facebook {pub.SWITCHED_OFF}"
    held = f.ready_video(session, cfg, approved=False, state="NEEDS_REVISION")
    session.add(QualityReview(video_version_id=held.current_version_id, reviewer="automated", passed=False,
                              score=80, checks=[], blocking_issues=["no_excessive_silence: silence 9.3-10.9 s"]))
    set_setting(session, "dry_run_mode", False)
    session.commit()
    html = TestClient(app).get("/calendar", auth=("ceo", "test-pass")).text
    assert "skipped: facebook is off" in html and "waiting for its slot" in html
    assert "dry run" not in html                                      # live now: no stale test-post tags
    assert "Not scheduled yet" in html and "no_excessive_silence" in html and held.title in html
