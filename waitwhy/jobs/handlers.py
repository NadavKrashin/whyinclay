"""Job type -> handler registry. Handlers are thin: load entities, call pipeline/agents, return a summary."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy import pipeline
from waitwhy.errors import ApprovalRequired, BudgetExceeded, QualityGateFailed
from waitwhy.jobs.worker import handler
from waitwhy.models import PublicationJob, Topic, Video, WorkflowJob
from waitwhy.settings import get_config


def _video_stage(stage: str, fn):
    def run(session: Session, job: WorkflowJob):
        cfg = get_config(session)
        vid = uuid.UUID(job.payload["video_id"])
        video = session.get(Video, vid)
        if video is None or video.state in ("CANCELLED",):
            return {"skipped": "video missing or cancelled"}
        try:
            return fn(session, cfg, video, job.id)
        except (BudgetExceeded, ApprovalRequired, QualityGateFailed) as exc:
            session.rollback()
            pipeline.on_stage_error(session, session.get(Video, vid), exc, stage)
            session.commit()
            raise
    return run


for _name, _fn in {
    "research": pipeline.stage_research,
    "script": pipeline.stage_script,
    "storyboard": pipeline.stage_storyboard,
    "generate_assets": pipeline.stage_generate,
    "prepare_metadata": pipeline.stage_metadata,
    "edit": pipeline.stage_edit,
    "qc": pipeline.stage_qc,
}.items():
    handler(_name)(_video_stage(_name, _fn))


@handler("start_production")
def h_start(session: Session, job: WorkflowJob):
    cfg = get_config(session)
    topic = session.get(Topic, uuid.UUID(job.payload["topic_id"]))
    v = pipeline.start_production(session, cfg, topic, actor=job.payload.get("actor", "agent:coo"))
    return {"video_id": str(v.id)}


@handler("schedule_publications")
def h_schedule(session: Session, job: WorkflowJob):
    from waitwhy.publishing import service
    cfg = get_config(session)
    video = session.get(Video, uuid.UUID(job.payload["video_id"]))
    jobs = service.schedule_video(session, cfg, video, "agent:publisher")
    return {"scheduled": [(j.platform, j.scheduled_at.isoformat()) for j in jobs]}


@handler("publish")
def h_publish(session: Session, job: WorkflowJob):
    from waitwhy.publishing import service
    cfg = get_config(session)
    pj = session.get(PublicationJob, uuid.UUID(job.payload["publication_job_id"]))
    status = service.publish(session, cfg, pj)
    return {"platform": pj.platform, "status": status}


@handler("trend_discovery")
def h_trends(session: Session, job: WorkflowJob):
    from waitwhy.agents import trends
    return trends.discover(session, get_config(session), count=job.payload.get("count", 10), job_id=job.id)


@handler("sponsor_research")
def h_sponsors(session: Session, job: WorkflowJob):
    from waitwhy.business import sponsors
    return sponsors.research(session, get_config(session), job_id=job.id)


@handler("health_check")
def h_health(session: Session, job: WorkflowJob):
    from waitwhy.agents import coo
    return coo.health_check(session, get_config(session))


@handler("recover_stalled")
def h_recover(session: Session, job: WorkflowJob):
    from waitwhy.jobs import queue
    return {"recovered": queue.recover_stalled(session)}


@handler("content_planning")
def h_planning(session: Session, job: WorkflowJob):
    from waitwhy.agents import coo
    return coo.content_planning(session, get_config(session))


@handler("production_tick")
def h_tick(session: Session, job: WorkflowJob):
    from waitwhy.agents import coo
    return coo.production_tick(session, get_config(session))


@handler("import_episodes")
def h_import(session: Session, job: WorkflowJob):
    from waitwhy import importer
    cfg = get_config(session)
    if cfg.get("episodes", {}).get("git_pull"):
        importer.git_pull()
    from waitwhy.publishing import service as pub
    out = importer.import_all(session, cfg)
    caught_up = pub.catch_up_platforms(session, cfg)
    return {**out, "caught_up": caught_up} if caught_up else out


@handler("instagram_token_refresh")
def h_ig_token(session: Session, job: WorkflowJob):
    from waitwhy.publishing import tokens
    return tokens.refresh_instagram(session)


@handler("publish_due")
def h_publish_due(session: Session, job: WorkflowJob):
    from waitwhy.agents import coo
    return coo.publish_due(session, get_config(session))


@handler("analytics_collect")
def h_analytics(session: Session, job: WorkflowJob):
    from waitwhy.analytics import ingest
    # "Refresh now" on the dashboard re-reads anything older than 15 minutes; scheduled runs every ~6 hours
    gap = 0.25 if (job.payload or {}).get("manual") else 5
    return ingest.collect(session, get_config(session), min_gap_hours=gap)


@handler("strategy_analysis")
def h_strategy(session: Session, job: WorkflowJob):
    from waitwhy.analytics import insights
    return insights.strategy_analysis(session, get_config(session), job_id=job.id)


@handler("daily_report")
def h_daily(session: Session, job: WorkflowJob):
    from waitwhy import reports
    return reports.send_daily(session, get_config(session))


@handler("weekly_review")
def h_weekly(session: Session, job: WorkflowJob):
    from waitwhy import reports
    return reports.send_weekly(session, get_config(session))


@handler("monthly_review")
def h_monthly(session: Session, job: WorkflowJob):
    from waitwhy import reports
    return reports.send_monthly(session, get_config(session))


@handler("db_backup")
def h_backup(session: Session, job: WorkflowJob):
    from waitwhy.ops import backup
    return backup.run_backup()


def known_publication_jobs(session: Session, video_id: uuid.UUID) -> list[PublicationJob]:
    return list(session.execute(select(PublicationJob).where(PublicationJob.video_id == video_id)).scalars())
