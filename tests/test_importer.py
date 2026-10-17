"""Importing finished episodes from the Claude + Higgsfield production runs (channel/episodes.json)."""
import json

import pytest
from sqlalchemy import select

from waitwhy import importer
from waitwhy.agents import coo
from waitwhy.models import Approval, QualityReview, Video, VideoVersion, WorkflowJob


@pytest.fixture(autouse=True)
def fake_probe(monkeypatch):
    """The real ffprobe checks are covered in test_media; here every technical check passes."""
    def report(path, cfg_video):
        assert path.exists()
        names = ["video_stream", "audio_stream", "resolution", "frame_rate", "video_codec", "pixel_format",
                 "frame_count", "audio_codec", "duration", "decode_clean", "no_black_frames",
                 "no_excessive_silence", "loudness", "true_peak"]  # same list as the real report
        assert (cfg_video["width"], cfg_video["height"], cfg_video["fps"]) == (1440, 2560, 24)
        return {"checks": [{"name": n, "category": "technical", "passed": True, "mandatory": True, "detail": "ok"}
                           for n in names], "probe": {"duration_s": 60.1}}
    monkeypatch.setattr(importer.probe, "technical_report", report)


@pytest.fixture
def ep(tmp_path):
    (tmp_path / "v1.mp4").write_bytes(b"video-1")
    (tmp_path / "v2.mp4").write_bytes(b"video-2")
    (tmp_path / "t.png").write_bytes(b"png")
    return {"number": 1, "slug": "why-traffic-jams-appear", "title": "Why Traffic Jams Appear Out of Nowhere",
            "status": "produced_not_published", "video_url": f"file://{tmp_path}/v1.mp4",
            "thumbnail_url": f"file://{tmp_path}/t.png", "sources": ["https://a.example", "https://b.example"],
            "description": "No crash, no roadwork: the jam makes itself.", "hashtags": ["#shorts", "#traffic"],
            "checks": {"narration_strict": "passed", "captions": "passed", "visual_review": "passed"},
            "known_issues": ["hook scored WEAK"]}


def _cleared(cfg):
    cfg["episodes"]["higgsfield_commercial_use_confirmed"] = True
    return cfg


def _uncleared(cfg):
    cfg["episodes"]["higgsfield_commercial_use_confirmed"] = False
    return cfg


def test_blocks_until_rights_confirmed(session, cfg, ep):
    out = importer.import_episode(session, _uncleared(cfg), ep)
    v = session.execute(select(Video).where(Video.slug == ep["slug"])).scalar_one()
    rev = session.execute(select(QualityReview)).scalar_one()
    assert out.startswith("imported") and v.state == "NEEDS_REVISION"
    assert [b.split(":")[0] for b in rev.blocking_issues] == ["rights_cleared"]


def test_autonomous_mode_approves_and_schedules(session, cfg, ep):
    importer.import_episode(session, _cleared(cfg), ep)
    v = session.execute(select(Video).where(Video.slug == ep["slug"])).scalar_one()
    vv = session.get(VideoVersion, v.current_version_id)
    assert v.state == "APPROVED" and vv.status == "qc_passed" and vv.manifest["publishable"]
    assert vv.thumbnail_key and v.publish_metadata["disclosure"]["ai_generated_visuals"]
    assert "https://a.example" in v.publish_metadata["youtube_description"]
    assert session.execute(select(WorkflowJob).where(WorkflowJob.type == "schedule_publications")).scalar_one()


def test_supervised_mode_waits_for_owner(session, cfg, ep):
    cfg = _cleared(cfg)
    cfg["operating_mode"] = "supervised"
    importer.import_episode(session, cfg, ep)
    v = session.execute(select(Video)).scalar_one()
    assert v.state == "READY_FOR_REVIEW"
    assert session.execute(select(Approval).where(Approval.status == "pending")).scalar_one()


def test_missing_run_checks_block(session, cfg, ep):
    ep["checks"] = {"captions": "passed"}
    importer.import_episode(session, _cleared(cfg), ep)
    rev = session.execute(select(QualityReview)).scalar_one()
    assert {b.split(":")[0] for b in rev.blocking_issues} == {"narration_word_check", "visual_review"}


def test_reimport_is_idempotent(session, cfg, ep):
    importer.import_episode(session, _cleared(cfg), ep)
    assert importer.import_episode(session, cfg, ep) == "unchanged"
    assert len(session.execute(select(VideoVersion)).scalars().all()) == 1


def test_confirming_rights_rechecks_without_new_cut(session, cfg, ep):
    importer.import_episode(session, _uncleared(cfg), ep)
    assert importer.import_episode(session, cfg, ep) == "unchanged"  # nothing changed: no repeat alerts
    out = importer.import_episode(session, _cleared(cfg), ep)
    v = session.execute(select(Video)).scalar_one()
    assert out.startswith("rechecked") and v.state == "APPROVED"
    assert session.get(VideoVersion, v.current_version_id).manifest["rights"][0]["commercial_use"]


def test_new_cut_replaces_unapproved_version(session, cfg, ep, tmp_path):
    cfg = _cleared(cfg)
    cfg["operating_mode"] = "supervised"
    importer.import_episode(session, cfg, ep)
    ep["video_url"] = f"file://{tmp_path}/v2.mp4"
    assert importer.import_episode(session, cfg, ep).startswith("replaced")
    v = session.execute(select(Video)).scalar_one()
    assert session.get(VideoVersion, v.current_version_id).version == 2
    statuses = sorted(a.status for a in session.execute(select(Approval)).scalars())
    assert statuses == ["pending", "superseded"]


def test_new_cut_never_swaps_an_approved_video(session, cfg, ep, tmp_path):
    importer.import_episode(session, _cleared(cfg), ep)
    ep["video_url"] = f"file://{tmp_path}/v2.mp4"
    assert importer.import_episode(session, cfg, ep) == "skipped: already APPROVED"


def test_import_all_reads_the_log_and_isolates_failures(session, cfg, ep, tmp_path):
    bad = {**ep, "slug": "broken", "video_url": f"file://{tmp_path}/missing.mp4"}
    draft = {**ep, "slug": "draft", "status": "in_production"}
    f = tmp_path / "episodes.json"
    f.write_text(json.dumps({"episodes": [ep, bad, draft]}))
    out = importer.import_all(session, _cleared(cfg), f)
    assert out[ep["slug"]].startswith("imported") and out["broken"].startswith("failed")
    assert "draft" not in out
    assert session.execute(select(Video).where(Video.slug == "broken")).scalar_one_or_none() is None


def test_repo_episode_log_is_importable():
    data = json.loads(importer.episodes_path({"episodes": {}}).read_text())
    for e in data["episodes"]:
        assert {"slug", "title", "video_url", "status"} <= e.keys()
        importer.build_metadata(e, {})


def test_app_production_stays_idle_for_claude_runs(session, cfg):
    cfg["production_source"] = "claude_runs"
    out = coo.content_planning(session, cfg)
    assert out["actions"] == ["production handled by scheduled Claude runs"]
    assert not session.execute(select(WorkflowJob)).scalars().all()


def test_dashboard_page_for_imported_episode(session, cfg, ep):
    from fastapi.testclient import TestClient

    from waitwhy.api.app import app
    importer.import_episode(session, _cleared(cfg), ep)
    v = session.execute(select(Video)).scalar_one()
    vv = session.get(VideoVersion, v.current_version_id)
    assert vv.duration_s == 60.1
    vv.duration_s = None  # episodes imported before the fix have no length stored
    session.commit()
    r = TestClient(app).get(f"/videos/{v.id}", auth=("ceo", "test-pass"))
    assert r.status_code == 200
    assert "length unknown" in r.text and "Publishing details" in r.text
    assert "No crash, no roadwork" in r.text and "AI-generated visuals: yes" in r.text


def test_every_dashboard_page_works_with_imported_episode(session, cfg, ep):
    from fastapi.testclient import TestClient

    from waitwhy.api.app import app
    importer.import_episode(session, _cleared(cfg), ep)
    session.commit()
    c = TestClient(app)
    for path in ("/", "/pipeline", "/library", "/approvals", "/calendar", "/analytics", "/finance",
                 "/sponsors", "/agents", "/incidents", "/settings", "/api/status", "/api/videos"):
        assert c.get(path, auth=("ceo", "test-pass")).status_code == 200, path


def test_held_episode_alerts_the_owner_loudly(session, cfg, ep, monkeypatch):
    """An imported episode can't be repaired inside the app, so a failed check is a high alert."""
    from waitwhy.models import Notification

    def report(path, cfg_video):
        return {"checks": [{"name": "no_excessive_silence", "category": "technical", "passed": False,
                            "mandatory": True, "detail": "silences >= 1.5s: [(9.3, 10.9)]"}],
                "probe": {"duration_s": 60.1}}
    monkeypatch.setattr(importer.probe, "technical_report", report)
    importer.import_episode(session, _cleared(cfg), ep)
    n = session.execute(select(Notification)).scalar_one()
    assert n.severity == "high" and n.title.startswith("Episode held, not posted")
    assert "no_excessive_silence" in n.body


def test_qc_script_matches_the_import_check(cfg, ep, tmp_path, capsys):
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("qc_episode", root / "scripts" / "qc_episode.py")
    qc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qc)
    ok = qc.check(_cleared(cfg), {**ep, "known_issues": []}, Path(ep["video_url"][7:]))
    out = capsys.readouterr().out
    assert ok and "would be approved and posted automatically" in out
    assert not qc.check(_cleared(cfg), {**ep, "checks": {}}, Path(ep["video_url"][7:]))
    assert "HELD on the Mac" in capsys.readouterr().out


def test_publish_at_moves_waiting_posts_once(session, cfg, ep):
    from datetime import datetime, timedelta, timezone

    from waitwhy.models import PublicationJob
    from waitwhy.publishing import service as pub
    from waitwhy.settings import get_config
    importer.import_episode(session, _cleared(cfg), ep)
    v = session.execute(select(Video)).scalar_one()
    pub.schedule_video(session, get_config(session), v, "test")
    session.commit()
    soon = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(microsecond=0)
    ep["publish_at"] = soon.astimezone(timezone(timedelta(hours=3))).isoformat()
    assert importer.apply_publish_at(session, ep).startswith("rescheduled")
    jobs = session.execute(select(PublicationJob)).scalars().all()
    assert jobs and {j.scheduled_at for j in jobs} == {soon}
    later = soon + timedelta(days=1)
    for j in jobs:                       # owner moves it again in the dashboard
        j.scheduled_at = later
    assert importer.apply_publish_at(session, ep) is None   # the same publish_at isn't re-applied
    assert {j.scheduled_at for j in jobs} == {later}
    ep["publish_at"] = "2020-01-01T10:00:00+00:00"           # past times are ignored
    assert importer.apply_publish_at(session, ep) is None


def test_published_episodes_are_never_imported_again(session, cfg, ep, tmp_path):
    """After a database reset, an episode marked published in episodes.json must not be posted twice."""
    import json
    path = tmp_path / "episodes.json"
    path.write_text(json.dumps({"episodes": [{**ep, "status": "published", "posted": {"youtube": "x"}}]}))
    assert importer.import_all(session, _cleared(cfg), path=path) == {}
    assert session.execute(select(Video)).first() is None
