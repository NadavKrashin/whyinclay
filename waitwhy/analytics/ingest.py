"""Metrics ingestion. Only metrics an API actually returns are stored; everything else stays NULL
("unavailable"), never zero. Each capture is a new snapshot, so platform corrections keep history."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy.errors import AuthError, WaitWhyError
from waitwhy.models import AnalyticsSnapshot, PlatformPost, Video
from waitwhy.notify import alert
from waitwhy.publishing.service import adapter_for
from waitwhy.states import S, transition

FIELDS = ("views", "reach", "likes", "comments", "shares", "saves", "followers_gained", "avg_view_duration_s",
          "avg_pct_viewed", "completion_rate", "estimated_revenue_usd")


def collect(session: Session, cfg: dict, max_age_days: int = 35, min_gap_hours: float = 5) -> dict:
    now = datetime.now(timezone.utc)
    done, skipped, errors = 0, 0, []
    posts = session.execute(select(PlatformPost).where(PlatformPost.published_at.is_not(None),
                                                       PlatformPost.published_at > now - timedelta(days=max_age_days)))
    adapters = {}
    for post in posts.scalars():
        last = session.execute(select(AnalyticsSnapshot).where(AnalyticsSnapshot.platform_post_id == post.id)
                               .order_by(AnalyticsSnapshot.captured_at.desc())).scalars().first()
        if last and (now - last.captured_at) < timedelta(hours=min_gap_hours):
            skipped += 1
            continue
        try:
            adapter = adapters.get(post.platform) or adapter_for(session, cfg, post.platform)
            adapters[post.platform] = adapter
            metrics = {} if post.is_mock and not cfg.get("dry_run_mode") else adapter.fetch_metrics(post.external_id)
        except AuthError as e:
            alert(session, "high", "integration", f"{post.platform} analytics disconnected", str(e),
                  dedupe_key=f"analytics-auth:{post.platform}")
            errors.append(post.platform)
            continue
        except (WaitWhyError, Exception) as e:  # noqa: BLE001 - one platform must not stop the others
            errors.append(f"{post.platform}: {e}")
            continue
        hours = (now - post.published_at).total_seconds() / 3600
        snap = AnalyticsSnapshot(platform_post_id=post.id, captured_at=now, hours_since_publish=round(hours, 2),
                                 is_preliminary=hours < 72, is_mock=post.is_mock, raw=metrics,
                                 supersedes_id=last.id if last else None,
                                 **{k: metrics.get(k) for k in FIELDS})
        session.add(snap)
        done += 1
        video = session.get(Video, post.video_id)
        if video.state == S.PUBLISHED.value:
            transition(session, video, S.ANALYZING, "agent:analytics", "first analytics snapshot captured")
    if errors:
        alert(session, "low", "analytics", "Analytics collection had errors", "\n".join(map(str, errors)),
              dedupe_key=f"analytics-errors:{now.date()}")
    return {"snapshots": done, "skipped_recent": skipped, "errors": errors}
