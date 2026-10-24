"""Publishing orchestration: approval gates, scheduling, at-most-once publication, per-platform status.

Idempotency layers:
1. ``publication_jobs`` has UNIQUE(video_id, platform) and a UNIQUE idempotency key per (content, platform).
2. The queue job that triggers an upload has its own idempotency key.
3. A job found in ``uploading`` state on re-entry (worker crashed mid-upload) is NOT retried
   automatically - it is blocked for a human to verify, because the upload may have gone through.
4. An existing ``platform_posts`` row short-circuits any further attempt.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy.audit import audit
from waitwhy.errors import AuthError, AutomationPaused, PermanentError, PolicyError, TransientError
from waitwhy.jobs import queue
from waitwhy.models import Approval, PlatformPost, PublicationJob, SystemSetting, Video, VideoVersion
from waitwhy.notify import alert
from waitwhy.providers import registry
from waitwhy.publishing import adapters as ad
from waitwhy.settings import secrets
from waitwhy.states import S, transition

TERMINAL = {"published", "private_uploaded", "manual_action_required", "failed", "blocked", "cancelled"}
DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def adapter_for(session: Session, cfg: dict, platform: str):
    if cfg.get("dry_run_mode"):
        row = session.get(SystemSetting, "mock_publish_scenario")
        return ad.MockAdapter(platform, (row.value if row else None) or {})
    s = secrets()
    pcfg = cfg["platforms"][platform]
    ver = cfg.get("meta_graph_version", "v25.0")
    if platform == "youtube":
        return ad.YouTubeAdapter(s.youtube_client_id, s.youtube_client_secret, s.youtube_refresh_token,
                                 pcfg.get("publishing_mode", ""))
    if platform == "instagram":
        from waitwhy.publishing.tokens import current_token
        return ad.InstagramAdapter(s.instagram_user_id, current_token(), s.instagram_graph_host, ver)
    if platform == "facebook":
        return ad.FacebookReelsAdapter(s.meta_page_id, s.meta_page_access_token, ver)
    if platform == "tiktok":
        return ad.TikTokAdapter(s.tiktok_access_token, s.tiktok_app_audited, pcfg.get("publishing_mode", ""))
    raise PermanentError(f"unknown platform {platform}")


def public_video_url(store, vv: VideoVersion) -> str | None:
    """A public HTTPS link to this exact file, for platforms that fetch the video (Instagram).

    For episodes imported from the production runs, the CDN copy they were downloaded from comes first:
    the same bytes that passed QC, reachable from anywhere. Otherwise storage's own link, but only an
    HTTPS one: a LAN or tailnet address (e.g. PUBLIC_BASE_URL=http://mac.local:8000) can't be fetched by
    Instagram, which is why episode 1's first Instagram post failed on 2026-10-16."""
    src = (vv.manifest or {}).get("source_url") or ""
    if src.startswith("https://"):
        return src
    url = store.public_url(vv.storage_key, 6 * 3600)
    return url if url and url.startswith("https://") else None


def is_publication_approved(session: Session, video: Video) -> bool:
    a = session.execute(select(Approval).where(Approval.video_id == video.id, Approval.kind == "publication")
                        .order_by(Approval.created_at.desc())).scalars().first()
    return bool(a and a.status == "approved")


def next_slot(session: Session, cfg: dict, after: datetime | None = None) -> datetime:
    """Next free audience-timezone slot (one video per slot), returned in UTC."""
    ps = cfg["publishing_slots"]
    tz = ZoneInfo(ps["timezone"])
    now = (after or datetime.now(timezone.utc)).astimezone(tz) + timedelta(minutes=30)
    taken = {r.replace(second=0, microsecond=0) for (r,) in session.execute(
        select(PublicationJob.scheduled_at).where(PublicationJob.status.notin_(["cancelled"]))).all() if r}
    days = {DAYS[d] for d in ps["days"]}
    for day in range(0, 30):
        d = (now + timedelta(days=day)).date()
        if d.weekday() not in days:
            continue
        for hhmm in ps["slots"]:
            h, m = map(int, hhmm.split(":"))
            local = datetime(d.year, d.month, d.day, h, m, tzinfo=tz)
            utc = local.astimezone(timezone.utc)
            if local > now and utc.replace(second=0, microsecond=0) not in taken:
                return utc
    raise PermanentError("no free publishing slot in the next 30 days")


def schedule_video(session: Session, cfg: dict, video: Video, actor: str, at: datetime | None = None) -> list[PublicationJob]:
    if not is_publication_approved(session, video):
        raise PolicyError("publication requires an approved 'publication' approval")
    vv = session.get(VideoVersion, video.current_version_id)
    if vv is None or vv.status != "qc_passed":
        raise PolicyError("current version has not passed QC")
    if not cfg.get("dry_run_mode") and not vv.manifest.get("publishable"):
        raise PolicyError("version is not publishable (rights/mock waivers present) - re-render with licensed assets")
    when = at or next_slot(session, cfg)
    jobs = []
    for platform, pcfg in cfg["platforms"].items():
        if not pcfg.get("enabled"):
            continue
        key = f"pub:{video.id}:{platform}"
        pj = session.execute(select(PublicationJob).where(PublicationJob.idempotency_key == key)).scalar_one_or_none()
        if pj is None:
            meta = video.publish_metadata or {}
            pj = PublicationJob(video_id=video.id, video_version_id=vv.id, platform=platform, idempotency_key=key,
                                status="scheduled", scheduled_at=when, dry_run=bool(cfg.get("dry_run_mode")),
                                metadata_={"title": meta.get("youtube_title", video.title),
                                           "caption": meta.get(f"{platform}_caption") or meta.get("instagram_caption", ""),
                                           "description": meta.get("youtube_description", ""),
                                           "hashtags": meta.get("hashtags", []),
                                           "disclosure": meta.get("disclosure", {})})
            session.add(pj)
            session.flush()
            audit(session, actor, "publication.scheduled", "publication_job", pj.id, platform=platform,
                  scheduled_at=when.isoformat(), dry_run=pj.dry_run)
        elif pj.status in ("scheduled", "blocked", "failed"):
            pj.scheduled_at = when
        queue.enqueue(session, "publish", {"publication_job_id": str(pj.id)}, run_at=pj.scheduled_at,
                      idempotency_key=f"publish:{pj.id}:{pj.scheduled_at.isoformat()}", video_id=video.id)
        jobs.append(pj)
    if video.state == S.APPROVED.value:
        transition(session, video, S.SCHEDULED, actor, f"scheduled for {when.isoformat()}")
    return jobs


def publish(session: Session, cfg: dict, pj: PublicationJob, actor: str = "agent:publisher") -> str:
    if pj.status in ("published", "cancelled", "manual_action_required", "private_uploaded"):
        return pj.status  # idempotent no-op
    paused = session.get(SystemSetting, "publishing_paused")
    if paused and paused.value:
        raise AutomationPaused("publishing is paused (emergency switch)")
    existing = session.execute(select(PlatformPost).where(PlatformPost.publication_job_id == pj.id)).scalar_one_or_none()
    if existing:
        pj.status = "published" if existing.is_public else "private_uploaded"
        return pj.status
    video = session.get(Video, pj.video_id)
    if not cfg["platforms"].get(pj.platform, {}).get("enabled"):
        # Switched off after the job was scheduled (e.g. Facebook, which has no Page): drop it quietly.
        pj.status, pj.last_error = "cancelled", f"{pj.platform} {SWITCHED_OFF}"
        audit(session, actor, "publication.cancelled", "publication_job", pj.id, reason=pj.last_error)
        _evaluate(session, video, actor)
        return pj.status
    if pj.status == "uploading":
        pj.status = "blocked"
        pj.last_error = "previous attempt was interrupted mid-upload - verify on the platform before retrying"
        alert(session, "high", "publishing", f"Verify {pj.platform} upload for '{video.title}'", pj.last_error,
              dedupe_key=f"verify-upload:{pj.id}", video_id=video.id)
        _evaluate(session, video, actor)
        return pj.status
    if not is_publication_approved(session, video):
        pj.status, pj.last_error = "blocked", "approval missing or revoked"
        _evaluate(session, video, actor)
        return pj.status
    live = not cfg.get("dry_run_mode")
    if pj.dry_run == live:
        # Scheduled under the other mode (e.g. dry-run switched off after scheduling): the adapter
        # follows the current mode, so the record must too, or a real post is filed as a mock.
        pj.dry_run = not live
        audit(session, actor, "publication.mode_changed", "publication_job", pj.id, dry_run=pj.dry_run)
    vv = session.get(VideoVersion, pj.video_version_id)
    if not pj.dry_run and not vv.manifest.get("publishable"):
        pj.status, pj.last_error = "blocked", "version not publishable (licensing/mock content)"
        _evaluate(session, video, actor)
        return pj.status
    if video.state == S.SCHEDULED.value:
        transition(session, video, S.PUBLISHING, actor, f"publishing to {pj.platform}")
    store = registry.storage(cfg)
    req = ad.PublishRequest(
        idempotency_key=pj.idempotency_key, video_path=store.local_path(vv.storage_key),
        public_video_url=public_video_url(store, vv), thumbnail_path=store.local_path(vv.thumbnail_key)
        if vv.thumbnail_key else None, title=pj.metadata_.get("title", video.title),
        description=pj.metadata_.get("description", ""), caption=pj.metadata_.get("caption", ""),
        hashtags=pj.metadata_.get("hashtags", []), disclosure=pj.metadata_.get("disclosure", {}),
        scheduled_at_iso=None, made_for_kids=cfg["platforms"].get("youtube", {}).get("made_for_kids", False))
    pj.attempts += 1
    try:
        adapter = adapter_for(session, cfg, pj.platform)
        pj.status = "uploading"
        session.commit()
        out = adapter.publish(req)
    except TransientError as e:
        pj.status, pj.last_error, pj.error_class = "scheduled", str(e), "transient"
        session.commit()
        raise
    except AuthError as e:
        pj.status, pj.last_error, pj.error_class = "failed", str(e), "auth"
        alert(session, "high", "integration", f"{pj.platform} integration disconnected", str(e),
              dedupe_key=f"auth:{pj.platform}")
        _evaluate(session, video, actor)
        session.commit()
        raise
    except (PolicyError, PermanentError) as e:
        pj.status, pj.last_error = ("blocked" if isinstance(e, PolicyError) else "failed"), str(e)
        pj.error_class = getattr(e, "error_class", "permanent")
        alert(session, "high", "publishing", f"{pj.platform} publication failed for '{video.title}'", str(e),
              dedupe_key=f"pubfail:{pj.id}", video_id=video.id)
        _evaluate(session, video, actor)
        session.commit()
        raise
    pj.status, pj.last_error = out.status, (out.detail or None)
    if out.external_id:
        session.add(PlatformPost(publication_job_id=pj.id, video_id=video.id, platform=pj.platform,
                                 external_id=out.external_id, url=out.url, privacy_status=out.privacy,
                                 is_public=out.is_public, is_mock=pj.dry_run,
                                 published_at=datetime.now(timezone.utc) if out.is_public else None,
                                 verified_at=datetime.now(timezone.utc)))
    audit(session, actor, "publication.result", "publication_job", pj.id, platform=pj.platform, status=out.status,
          external_id=out.external_id, url=out.url, dry_run=pj.dry_run, detail=out.detail)
    if out.status in ("manual_action_required", "private_uploaded"):
        link = f"\n\nOpen: {cfg['dashboard_url'].rstrip('/')}/calendar" if cfg.get("dashboard_url") else ""
        alert(session, "low" if pj.dry_run else "high", "manual_action",
              f"Action needed: {pj.platform} for '{video.title}'", (out.detail or "") + link,
              dedupe_key=f"manual:{pj.id}", video_id=video.id)
    _evaluate(session, video, actor)
    return pj.status


def mark_manually_published(session: Session, pj: PublicationJob, url: str, external_id: str | None, actor: str) -> None:
    """Owner confirms a manual (e.g. TikTok) post. Recorded as a human-verified public post."""
    video = session.get(Video, pj.video_id)
    session.add(PlatformPost(publication_job_id=pj.id, video_id=pj.video_id, platform=pj.platform,
                             external_id=external_id or url, url=url, privacy_status="public", is_public=True,
                             is_mock=pj.dry_run, published_at=datetime.now(timezone.utc),
                             verified_at=datetime.now(timezone.utc)))
    pj.status, pj.last_error = "published", None
    audit(session, actor, "publication.manual_confirmed", "publication_job", pj.id, url=url)
    session.flush()
    _evaluate(session, video, actor)


def _evaluate(session: Session, video: Video, actor: str) -> None:
    session.flush()
    jobs = session.execute(select(PublicationJob).where(PublicationJob.video_id == video.id)).scalars().all()
    if not jobs:
        return
    if any(j.status == "published" for j in jobs) and video.state in (S.PUBLISHING.value, S.SCHEDULED.value,
                                                                      S.BLOCKED.value):
        if video.state == S.SCHEDULED.value:
            transition(session, video, S.PUBLISHING, actor, "first platform publishing")
        if video.state == S.BLOCKED.value:
            transition(session, video, S.PUBLISHING, actor, "manual publication confirmed")
        transition(session, video, S.PUBLISHED, actor,
                   "published on: " + ", ".join(j.platform for j in jobs if j.status == "published"))
    elif all(j.status in TERMINAL for j in jobs) and video.state == S.PUBLISHING.value:
        summary = ", ".join(f"{j.platform}={j.status}" for j in jobs)
        transition(session, video, S.BLOCKED, actor, f"no public publication yet ({summary})")


SWITCHED_OFF = "is switched off in config"


def catch_up_platforms(session: Session, cfg: dict, actor: str = "agent:publisher") -> list[str]:
    """Queue approved videos on platforms they missed because the platform was off at the time.

    A platform switched back on (e.g. Instagram after an account suspension) gets each such video in
    its own next free slot. Jobs the owner cancelled are left alone; only ones never created, or
    cancelled because the platform was off, are (re)queued."""
    done = []
    live = (S.SCHEDULED.value, S.PUBLISHING.value, S.PUBLISHED.value, S.BLOCKED.value)
    for video in session.execute(select(Video).where(Video.state.in_(live)).order_by(Video.created_at)).scalars():
        if not is_publication_approved(session, video):
            continue
        vv = session.get(VideoVersion, video.current_version_id)
        if vv is None or vv.status != "qc_passed" or (not cfg.get("dry_run_mode") and not vv.manifest.get("publishable")):
            continue
        for platform, pcfg in cfg["platforms"].items():
            if not pcfg.get("enabled"):
                continue
            key = f"pub:{video.id}:{platform}"
            pj = session.execute(select(PublicationJob).where(PublicationJob.idempotency_key == key)).scalar_one_or_none()
            if pj is not None and not (pj.status == "cancelled" and SWITCHED_OFF in (pj.last_error or "")):
                continue
            when = next_slot(session, cfg)
            meta = video.publish_metadata or {}
            if pj is None:
                pj = PublicationJob(video_id=video.id, video_version_id=vv.id, platform=platform, idempotency_key=key,
                                    status="scheduled", scheduled_at=when, dry_run=bool(cfg.get("dry_run_mode")),
                                    metadata_={"title": meta.get("youtube_title", video.title),
                                               "caption": meta.get(f"{platform}_caption") or meta.get("instagram_caption", ""),
                                               "description": meta.get("youtube_description", ""),
                                               "hashtags": meta.get("hashtags", []),
                                               "disclosure": meta.get("disclosure", {})})
                session.add(pj)
            else:
                pj.status, pj.last_error, pj.scheduled_at, pj.video_version_id = "scheduled", None, when, vv.id
                pj.dry_run = bool(cfg.get("dry_run_mode"))
            session.flush()
            queue.enqueue(session, "publish", {"publication_job_id": str(pj.id)}, run_at=when,
                          idempotency_key=f"publish:{pj.id}:{when.isoformat()}", video_id=video.id)
            audit(session, actor, "publication.caught_up", "publication_job", pj.id, platform=platform,
                  scheduled_at=when.isoformat())
            done.append(f"{video.slug}:{platform}@{when.isoformat()}")
    return done


STATUS_LABELS = {"published": ("posted", "ok"), "scheduled": ("waiting for its slot", "muted"),
                 "uploading": ("uploading now", "muted"), "manual_action_required": ("your turn: post it by hand", "warn"),
                 "private_uploaded": ("uploaded as private: make it public", "warn"), "blocked": ("blocked", "bad"),
                 "failed": ("failed", "bad"), "cancelled": ("cancelled", "muted")}


def status_label(pj: PublicationJob, dry_run_mode: bool) -> tuple[str, str, bool]:
    """Plain-words status for the dashboard: (label, css class, show the dry-run tag)."""
    label, cls = STATUS_LABELS.get(pj.status, (pj.status, "muted"))
    if pj.status == "cancelled" and SWITCHED_OFF in (pj.last_error or ""):
        label = f"skipped: {pj.platform} is off"
    elif pj.status in ("blocked", "failed") and pj.last_error:
        label = f"{label}: {pj.last_error[:80]}"
    # The tag means "this was / will be a test post": only for test posts that happened, or for
    # waiting posts while dry-run is still on. A job's flag is re-set to the live mode when it runs.
    done = pj.status in ("published", "private_uploaded", "manual_action_required")
    show_dry = (done and pj.dry_run) or (pj.status == "scheduled" and dry_run_mode)
    return label, cls, show_dry


def retry_publication(session: Session, pj: PublicationJob, actor: str) -> bool:
    """Owner's Retry on a failed or blocked post (e.g. after reconnecting YouTube): run it again now."""
    if pj.status not in ("failed", "blocked"):
        return False
    now = datetime.now(timezone.utc)
    pj.status, pj.last_error, pj.error_class, pj.scheduled_at = "scheduled", None, None, now
    queue.enqueue(session, "publish", {"publication_job_id": str(pj.id)}, run_at=now, video_id=pj.video_id,
                  idempotency_key=f"publish:{pj.id}:retry:{now.isoformat()}")
    audit(session, actor, "publication.retried", "publication_job", pj.id, platform=pj.platform)
    return True


def cancel_video_publications(session: Session, video_id: uuid.UUID, actor: str) -> int:
    n = 0
    for pj in session.execute(select(PublicationJob).where(PublicationJob.video_id == video_id,
                                                           PublicationJob.status == "scheduled")).scalars():
        pj.status = "cancelled"
        n += 1
        audit(session, actor, "publication.cancelled", "publication_job", pj.id)
    return n
