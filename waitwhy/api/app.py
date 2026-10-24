"""FastAPI app: CEO dashboard (server-rendered, mobile-first) + JSON API.

Security: HTTP Basic auth on everything except /healthz and the narrowly-scoped /public-media route
(platform pulls of scheduled videos only); CSRF token on every state-changing form; all actions audited.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import secrets as pysecrets
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from waitwhy import datasources, pipeline
from waitwhy.agents import coo
from waitwhy.analytics import metrics as am
from waitwhy.audit import audit
from waitwhy.business import budget, finance, sponsors
from waitwhy.db import session_factory
from waitwhy.errors import WaitWhyError
from waitwhy.jobs import queue
from waitwhy.models import (AgentRun, Approval, AuditLog, Experiment, FactCheck, GeneratedAsset, Notification,
                            OutreachDraft, PlatformPost, ProviderUsage, PublicationJob, QualityReview, ResearchSource,
                            RevenueTransaction, Script, Sponsor, Storyboard, SystemSetting, Topic, Video, VideoVersion,
                            WorkflowJob)
from waitwhy.providers import registry
from waitwhy.publishing import service as pub
from waitwhy.publishing.adapters import post_text
from waitwhy.publishing.cover import portrait_cover
from waitwhy.settings import get_config, secrets
from waitwhy.states import KANBAN_COLUMNS, S

HERE = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Why in Clay - operations", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["in_tz"] = lambda dt, tz: dt.astimezone(ZoneInfo(tz)).strftime("%H:%M") if dt else ""
templates.env.filters["local"] = lambda dt, tz, fmt="%a %d %b, %H:%M": dt.astimezone(ZoneInfo(tz)).strftime(fmt) if dt else "never"
templates.env.filters["ago"] = datasources.ago
templates.env.filters["ts"] = datasources.parse_ts
templates.env.filters["pname"] = datasources.platform_name
templates.env.filters["usd"] = lambda v: "—" if v is None else f"{'-' if v < 0 else ''}${abs(v):,.2f}"
templates.env.filters["num"] = lambda v: "—" if v is None else (f"{v / 1000:.1f}k" if abs(v) >= 10000 else f"{v:,.0f}")
basic = HTTPBasic()
Sessions = session_factory()


# ------------------------------------------------------------------ plumbing
def db():
    s = Sessions()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def user(creds: HTTPBasicCredentials = Depends(basic)) -> str:
    sec = secrets()
    if not sec.dashboard_password:
        if sec.app_env == "production":
            raise HTTPException(503, "DASHBOARD_PASSWORD must be set in production")
        return creds.username or "dev"
    ok = pysecrets.compare_digest(creds.username, sec.dashboard_username) and \
        pysecrets.compare_digest(creds.password, sec.dashboard_password)
    if not ok:
        raise HTTPException(401, "invalid credentials", headers={"WWW-Authenticate": "Basic"})
    return creds.username


def csrf_token(username: str) -> str:
    return hmac.new(secrets().secret_key.encode(), f"csrf:{username}".encode(), hashlib.sha256).hexdigest()[:32]


def check_csrf(username: str, token: str) -> None:
    if not pysecrets.compare_digest(token or "", csrf_token(username)):
        raise HTTPException(403, "invalid CSRF token")


def render(request: Request, name: str, ctx: dict, username: str, session: Session):
    cfg = get_config(session)
    flags = {k: bool((session.get(SystemSetting, k) or SystemSetting(value=False)).value)
             for k in ("publishing_paused", "automation_paused")}
    pending = session.execute(select(func.count()).select_from(Approval).where(Approval.status == "pending")).scalar()
    incidents = session.execute(select(func.count()).select_from(Notification).where(
        Notification.acknowledged_at.is_(None), Notification.severity.in_(["critical", "high"]))).scalar()
    base = {"request": request, "user": username, "csrf": csrf_token(username), "cfg": cfg, "flags": flags,
            "nav_pending": pending, "nav_incidents": incidents, "now": datetime.now(timezone.utc)}
    return templates.TemplateResponse(request, name, {**base, **ctx})


def back(request: Request, default: str = "/") -> RedirectResponse:
    return RedirectResponse(request.headers.get("referer") or default, status_code=303)


def _setting(session: Session, key: str, value, who: str) -> None:
    row = session.get(SystemSetting, key)
    before = row.value if row else None
    if row:
        row.value, row.updated_by = value, who
    else:
        session.add(SystemSetting(key=key, value=value, updated_by=who))
    audit(session, f"user:{who}", "setting.changed", "system_setting", key, before={"value": before},
          after={"value": value})


# ------------------------------------------------------------------ health
@app.get("/healthz")
def healthz():
    s = Sessions()
    try:
        s.execute(text("select 1"))
        return {"status": "ok", "db": True}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"status": "error", "db": False, "error": str(e)}, status_code=503)
    finally:
        s.close()


# ------------------------------------------------------------------ overview
@app.get("/", response_class=HTMLResponse)
def overview(request: Request, u: str = Depends(user), s: Session = Depends(db)):
    cfg = get_config(s)
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    published_month = s.execute(select(func.count(func.distinct(PlatformPost.video_id))).where(
        PlatformPost.published_at >= month_start, PlatformPost.is_public.is_(True),
        PlatformPost.is_mock.is_(False))).scalar()
    mock_published = s.execute(select(func.count()).select_from(PlatformPost).where(PlatformPost.is_mock.is_(True))).scalar()
    rows = am.all_post_metrics(s)
    views = [r.latest.get("views") for r in rows]
    st = budget.status(s, cfg)
    inv = coo.inventory(s)
    health = (s.get(SystemSetting, "last_health") or SystemSetting(value=None)).value
    revenue = finance.revenue_mtd(s, "received")
    attention = s.execute(select(Notification).where(Notification.acknowledged_at.is_(None))
                          .order_by(Notification.created_at.desc()).limit(6)).scalars().all()
    report = (s.get(SystemSetting, "last_daily_report") or SystemSetting(value=None)).value
    sources = datasources.all_sources(s, cfg)
    return render(request, "overview.html", {
        "sources": sources, "fresh": datasources.views_freshness(sources), "timeline": am.views_timeline(s),
        "by_video": am.views_by_video(rows)[:6], "totals": am.totals(rows),
        "published_month": published_month, "mock_published": mock_published,
        "total_views": sum(v for v in views if v is not None) if any(v is not None for v in views) else None,
        "views_partial": any(v is None for v in views), "budget": st, "inventory": inv, "health": health,
        "revenue": revenue, "contribution": round(revenue - st["total_spend_usd"], 2), "attention": attention,
        "report": report, "creds": coo.credential_status()}, u, s)


# ------------------------------------------------------------------ pipeline (kanban)
@app.get("/pipeline", response_class=HTMLResponse)
def pipeline_board(request: Request, u: str = Depends(user), s: Session = Depends(db)):
    videos = s.execute(select(Video).order_by(Video.priority.desc(), Video.updated_at.desc())).scalars().all()
    cols = []
    for name, states in KANBAN_COLUMNS:
        cols.append({"name": name, "videos": [v for v in videos if v.state in {x.value for x in states}]})
    ideas = s.execute(select(Topic).where(Topic.status == "evaluated").order_by(Topic.score_total.desc()).limit(12)).scalars().all()
    jobs = s.execute(select(WorkflowJob).where(WorkflowJob.status.in_(["queued", "running", "blocked"]))
                     .order_by(WorkflowJob.run_at).limit(30)).scalars().all()
    return render(request, "pipeline.html", {"cols": cols, "ideas": ideas, "jobs": jobs}, u, s)


@app.post("/topics/{tid}/produce")
def produce_topic(request: Request, tid: uuid.UUID, csrf: str = Form(...), u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    t = s.get(Topic, tid)
    pipeline.start_production(s, get_config(s), t, actor=f"user:{u}", priority=5)
    return back(request, "/pipeline")


@app.post("/topics")
def add_topic(request: Request, title: str = Form(...), category: str = Form(...), angle: str = Form(""),
              csrf: str = Form(...), u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    from waitwhy.agents.trends import add_candidate
    from waitwhy.schemas import TopicCandidate, TopicScores
    add_candidate(s, get_config(s), TopicCandidate(
        title=title, category=category, angle=angle or title, summary=angle or title, keywords=[], risk_flags=[],
        scores=TopicScores(**{k: 75 for k in TopicScores.model_fields}), reasoning=f"submitted by {u}"), origin="owner")
    audit(s, f"user:{u}", "topic.added", "topic", None, title=title)
    return back(request, "/pipeline")


# ------------------------------------------------------------------ library + video detail
@app.get("/library", response_class=HTMLResponse)
def library(request: Request, u: str = Depends(user), s: Session = Depends(db)):
    videos = s.execute(select(Video).order_by(Video.created_at.desc())).scalars().all()
    costs = {v.id: finance.video_cost(s, v.id, include_mock=True) for v in videos}
    return render(request, "library.html", {"videos": videos, "costs": costs}, u, s)


@app.get("/videos/{vid}", response_class=HTMLResponse)
def video_detail(request: Request, vid: uuid.UUID, u: str = Depends(user), s: Session = Depends(db)):
    v = s.get(Video, vid)
    if not v:
        raise HTTPException(404)
    fc = s.execute(select(FactCheck).where(FactCheck.video_id == vid).order_by(FactCheck.version.desc())).scalars().first()
    script = s.get(Script, v.current_script_id) if v.current_script_id else None
    board = s.get(Storyboard, v.current_storyboard_id) if v.current_storyboard_id else None
    versions = s.execute(select(VideoVersion).where(VideoVersion.video_id == vid).order_by(VideoVersion.version.desc())).scalars().all()
    reviews = {vv.id: s.execute(select(QualityReview).where(QualityReview.video_version_id == vv.id)
                                .order_by(QualityReview.created_at.desc())).scalars().first() for vv in versions}
    pubs = s.execute(select(PublicationJob).where(PublicationJob.video_id == vid)).scalars().all()
    posts = {p.publication_job_id: p for p in s.execute(select(PlatformPost).where(PlatformPost.video_id == vid)).scalars()}
    post_metrics = [am.post_metrics(s, p) for p in posts.values()]
    approvals = s.execute(select(Approval).where(Approval.video_id == vid).order_by(Approval.created_at.desc())).scalars().all()
    history = s.execute(select(AuditLog).where(AuditLog.entity_type == "video", AuditLog.entity_id == str(vid))
                        .order_by(AuditLog.created_at)).scalars().all()
    runs = s.execute(select(AgentRun).where(AgentRun.video_id == vid).order_by(AgentRun.created_at)).scalars().all()
    usage = s.execute(select(ProviderUsage.kind, ProviderUsage.provider, ProviderUsage.is_mock, func.sum(ProviderUsage.cost_usd))
                      .where(ProviderUsage.video_id == vid).group_by(ProviderUsage.kind, ProviderUsage.provider,
                                                                     ProviderUsage.is_mock)).all()
    sources = s.execute(select(ResearchSource).where(ResearchSource.video_id == vid)).scalars().all()
    return render(request, "video.html", {"v": v, "fc": fc, "script": script, "board": board, "versions": versions,
                                          "reviews": reviews, "pubs": pubs, "posts": posts, "approvals": approvals,
                                          "history": history, "runs": runs, "usage": usage, "sources": sources,
                                          "post_metrics": post_metrics}, u, s)


@app.post("/videos/{vid}/revise")
def revise(request: Request, vid: uuid.UUID, from_stage: str = Form(...), notes: str = Form(""), csrf: str = Form(...),
           u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    pipeline.request_revision(s, get_config(s), s.get(Video, vid), from_stage, f"user:{u}", notes)
    return back(request)


@app.post("/videos/{vid}/cancel")
def cancel_video(request: Request, vid: uuid.UUID, csrf: str = Form(...), u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    from waitwhy.states import transition
    v = s.get(Video, vid)
    pub.cancel_video_publications(s, vid, f"user:{u}")
    transition(s, v, S.CANCELLED, f"user:{u}", "cancelled from dashboard")
    return back(request)


@app.post("/videos/{vid}/reschedule")
def reschedule(request: Request, vid: uuid.UUID, when: str = Form(...), csrf: str = Form(...), u: str = Depends(user),
               s: Session = Depends(db)):
    check_csrf(u, csrf)
    at = datetime.fromisoformat(when)
    if at.tzinfo is None:
        from zoneinfo import ZoneInfo
        at = at.replace(tzinfo=ZoneInfo(get_config(s)["timezone"]))
    v = s.get(Video, vid)
    for pj in s.execute(select(PublicationJob).where(PublicationJob.video_id == vid, PublicationJob.status == "scheduled")).scalars():
        pj.scheduled_at = at.astimezone(timezone.utc)
        queue.enqueue(s, "publish", {"publication_job_id": str(pj.id)}, run_at=pj.scheduled_at, video_id=vid,
                      idempotency_key=f"publish:{pj.id}:{pj.scheduled_at.isoformat()}")
    audit(s, f"user:{u}", "publication.rescheduled", "video", vid, when=at.isoformat())
    return back(request)


@app.get("/media/{key:path}")
def media(key: str, u: str = Depends(user), s: Session = Depends(db)):
    p = registry.storage(get_config(s)).local_path(key)
    if not p or not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/public-media/{key:path}")
def public_media(key: str, s: Session = Depends(db)):
    """Unauthenticated, but ONLY for final renders of videos with an active publication job."""
    vv = s.execute(select(VideoVersion).where(VideoVersion.storage_key == key)).scalar_one_or_none()
    if not vv:
        raise HTTPException(404)
    active = s.execute(select(PublicationJob.id).where(PublicationJob.video_version_id == vv.id,
                                                       PublicationJob.status.in_(["scheduled", "uploading", "processing"]))).first()
    if not active:
        raise HTTPException(404)
    return FileResponse(registry.storage(get_config(s)).local_path(key), media_type="video/mp4")


# ------------------------------------------------------------------ approvals
@app.get("/approvals", response_class=HTMLResponse)
def approvals(request: Request, u: str = Depends(user), s: Session = Depends(db)):
    pending = s.execute(select(Approval).where(Approval.status == "pending").order_by(Approval.created_at)).scalars().all()
    recent = s.execute(select(Approval).where(Approval.status != "pending").order_by(Approval.decided_at.desc()).limit(20)).scalars().all()
    ctx = []
    for a in pending:
        v = s.get(Video, a.video_id) if a.video_id else None
        vv = s.get(VideoVersion, v.current_version_id) if v and v.current_version_id else None
        rv = s.execute(select(QualityReview).where(QualityReview.video_version_id == vv.id)
                       .order_by(QualityReview.created_at.desc())).scalars().first() if vv else None
        ctx.append({"a": a, "v": v, "vv": vv, "review": rv})
    drafts = s.execute(select(OutreachDraft).where(OutreachDraft.status == "draft")).scalars().all()
    return render(request, "approvals.html", {"items": ctx, "recent": recent, "drafts": drafts}, u, s)


@app.post("/approvals/{aid}/decide")
def decide(request: Request, aid: uuid.UUID, decision: str = Form(...), notes: str = Form(""), csrf: str = Form(...),
           u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    try:
        pipeline.decide(s, get_config(s), s.get(Approval, aid), decision, f"user:{u}", notes)
    except WaitWhyError as e:
        raise HTTPException(409, str(e))
    return back(request, "/approvals")


# ------------------------------------------------------------------ calendar + publications
@app.get("/calendar", response_class=HTMLResponse)
def calendar(request: Request, u: str = Depends(user), s: Session = Depends(db)):
    start = datetime.now(timezone.utc) - timedelta(days=7)
    jobs = s.execute(select(PublicationJob).where(PublicationJob.scheduled_at >= start)
                     .order_by(PublicationJob.scheduled_at)).scalars().all()
    cfg = get_config(s)
    tz = ZoneInfo(cfg.get("timezone", "UTC"))
    days: dict[str, list] = {}
    for j in jobs:
        label, cls, dry = pub.status_label(j, bool(cfg.get("dry_run_mode")))
        day = j.scheduled_at.astimezone(tz).strftime("%a %d %b")
        days.setdefault(day, []).append((j, s.get(Video, j.video_id), label, cls, dry))
    waiting = []  # finished videos that have no publishing slot yet, and why
    for v in s.execute(select(Video).where(Video.state.in_(["QUALITY_CHECK", "NEEDS_REVISION", "READY_FOR_REVIEW",
                                                            "APPROVED"])).order_by(Video.created_at)).scalars():
        if v.current_version_id is None or s.execute(select(PublicationJob.id).where(
                PublicationJob.video_id == v.id)).first():
            continue
        rev = s.execute(select(QualityReview).where(QualityReview.video_version_id == v.current_version_id)
                        .order_by(QualityReview.created_at.desc())).scalars().first()
        why = {"QUALITY_CHECK": "being checked", "READY_FOR_REVIEW": "waiting for your approval (Approvals page)",
               "APPROVED": "approved; gets a slot within a few minutes"}.get(v.state, "failed a check")
        if v.state == "NEEDS_REVISION" and rev and rev.blocking_issues:
            why = "failed a check: " + "; ".join(str(b) for b in rev.blocking_issues)[:300]
        waiting.append((v, why))
    manual = s.execute(select(PublicationJob).where(PublicationJob.status.in_(["manual_action_required",
                                                                               "private_uploaded", "blocked"]))).scalars().all()
    return render(request, "calendar.html", {"days": days, "waiting": waiting, "manual": [(j, s.get(Video, j.video_id)) for j in manual]}, u, s)


@app.get("/publications/{pid}/package")
def manual_package(pid: uuid.UUID, u: str = Depends(user), s: Session = Depends(db)):
    pj = s.get(PublicationJob, pid)
    vv = s.get(VideoVersion, pj.video_version_id)
    store = registry.storage(get_config(s))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.write(store.local_path(vv.storage_key), "video.mp4")
        cover = (vv.manifest or {}).get("cover_key") or vv.thumbnail_key
        if cover:
            z.writestr("cover.jpg", portrait_cover(store.local_path(cover)))
        md = pj.metadata_ or {}
        z.writestr("caption.txt", post_text(md.get("caption", ""), md.get("hashtags", []), pj.platform))
        z.writestr("disclosure.json", json.dumps(md.get("disclosure", {}), indent=1))
    buf.seek(0)
    audit(s, f"user:{u}", "publication.package_downloaded", "publication_job", pid)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename={pj.platform}-package.zip"})


@app.post("/publications/{pid}/retry")
def retry_publication(request: Request, pid: uuid.UUID, csrf: str = Form(...), u: str = Depends(user),
                      s: Session = Depends(db)):
    check_csrf(u, csrf)
    pj = s.get(PublicationJob, pid)
    if pj is None:
        raise HTTPException(404)
    pub.retry_publication(s, pj, f"user:{u}")
    return back(request, f"/videos/{pj.video_id}")


@app.post("/publications/{pid}/manual-done")
def manual_done(request: Request, pid: uuid.UUID, url: str = Form(...), csrf: str = Form(...), u: str = Depends(user),
                s: Session = Depends(db)):
    check_csrf(u, csrf)
    if not url.startswith("https://"):
        raise HTTPException(400, "post URL must be https")
    pub.mark_manually_published(s, s.get(PublicationJob, pid), url, None, f"user:{u}")
    return back(request, "/calendar")


# ------------------------------------------------------------------ analytics
@app.get("/analytics", response_class=HTMLResponse)
def analytics(request: Request, u: str = Depends(user), s: Session = Depends(db)):
    rows = am.all_post_metrics(s)
    baselines = am.platform_baselines(rows)
    sources = datasources.all_sources(s, get_config(s))
    experiments = s.execute(select(Experiment).order_by(Experiment.created_at.desc())).scalars().all()
    strategy = s.execute(select(AgentRun).where(AgentRun.task == "strategy_analysis")
                         .order_by(AgentRun.created_at.desc())).scalars().first()
    return render(request, "analytics.html", {
        "rows": rows, "baselines": baselines, "by_category": am.cohort_stats(rows, "category"),
        "by_hook": am.cohort_stats(rows, "hook_style"),
        "timeline": am.views_timeline(s), "by_video": am.views_by_video(rows), "totals": am.totals(rows),
        "likes_chart": am.per_video_chart(rows, "rates", "likes_per_1k"),
        "watched_chart": am.per_video_chart(rows, "latest", "avg_pct_viewed"),
        "sources": sources, "fresh": datasources.views_freshness(sources),
        "experiments": experiments, "strategy": strategy}, u, s)


@app.post("/experiments")
def add_experiment(request: Request, hypothesis: str = Form(...), change: str = Form(...), metric: str = Form(...),
                   csrf: str = Form(...), u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    s.add(Experiment(hypothesis=hypothesis, change=change, metric=metric, status="proposed"))
    return back(request, "/analytics")


# ------------------------------------------------------------------ finance
@app.get("/finance", response_class=HTMLResponse)
def finance_page(request: Request, u: str = Depends(user), s: Session = Depends(db)):
    cfg = get_config(s)
    vids = s.execute(select(Video).order_by(Video.created_at.desc()).limit(30)).scalars().all()
    credits = []  # Higgsfield credits per episode, as each production run reported them in episodes.json
    for v in reversed(vids):
        vv = s.get(VideoVersion, v.current_version_id) if v.current_version_id else None
        spent = (vv.manifest or {}).get("credits_spent") if vv else None
        if spent is not None:
            credits.append({"title": v.title, "credits": float(spent)})
    sources = {x.key: x for x in datasources.all_sources(s, cfg)}
    return render(request, "finance.html", {
        "credits": credits, "cost_source": sources["costs"], "revenue_source": sources["revenue"],
        "budget": budget.status(s, cfg), "by_provider": finance.spend_by_provider(s),
        "per_video": [(v, finance.video_cost(s, v.id), finance.video_cost(s, v.id, include_mock=True)) for v in vids],
        "pnl": finance.monthly_pnl(s), "invoices": finance.outstanding_invoices(s),
        "revenue": s.execute(select(RevenueTransaction).order_by(RevenueTransaction.created_at.desc()).limit(20)).scalars().all(),
        "rate": sponsors.rate_guidance(s, cfg)}, u, s)


@app.post("/finance/expense")
def add_expense(request: Request, vendor: str = Form(...), category: str = Form(...), amount: float = Form(...),
                kind: str = Form("cash"), fixed: bool = Form(False), description: str = Form(""), csrf: str = Form(...),
                u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    e = finance.record_expense(s, vendor=vendor, category=category, amount_usd=amount, kind=kind, is_fixed=fixed,
                               description=description)
    audit(s, f"user:{u}", "expense.recorded", "expense", e.id, amount=amount, vendor=vendor)
    return back(request, "/finance")


@app.post("/finance/revenue")
def add_revenue(request: Request, source: str = Form(...), counterparty: str = Form(...), amount: float = Form(...),
                status: str = Form(...), description: str = Form(""), csrf: str = Form(...), u: str = Depends(user),
                s: Session = Depends(db)):
    check_csrf(u, csrf)
    today = datetime.now(timezone.utc).date()
    r = RevenueTransaction(source=source, counterparty=counterparty, amount_usd=amount, status=status,
                           description=description, invoiced_on=today if status in ("invoiced", "received") else None,
                           received_on=today if status == "received" else None,
                           is_client_work=source == "client")
    s.add(r)
    s.flush()
    audit(s, f"user:{u}", "revenue.recorded", "revenue", r.id, amount=amount, status=status)
    return back(request, "/finance")


# ------------------------------------------------------------------ sponsors
@app.get("/sponsors", response_class=HTMLResponse)
def sponsors_page(request: Request, u: str = Depends(user), s: Session = Depends(db)):
    sp = s.execute(select(Sponsor).order_by(Sponsor.updated_at.desc())).scalars().all()
    drafts = {d.sponsor_id: d for d in s.execute(select(OutreachDraft)).scalars()}
    return render(request, "sponsors.html", {"sponsors": sp, "drafts": drafts,
                                             "rate": sponsors.rate_guidance(s, get_config(s))}, u, s)


@app.post("/sponsors")
def add_sponsor(request: Request, company: str = Form(...), website: str = Form(""), product: str = Form(""),
                fit_reason: str = Form(""), video_concept: str = Form(""), csrf: str = Form(...), u: str = Depends(user),
                s: Session = Depends(db)):
    check_csrf(u, csrf)
    s.add(Sponsor(company=company, website=website, product=product, fit_reason=fit_reason,
                  video_concept=video_concept, contact_source=f"added by {u}"))
    return back(request, "/sponsors")


@app.post("/sponsors/{sid}/draft")
def draft_sponsor(request: Request, sid: uuid.UUID, csrf: str = Form(...), u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    d = sponsors.draft_outreach(s, get_config(s), s.get(Sponsor, sid))
    s.add(Approval(kind="outreach", status="pending", target_type="outreach_draft", target_id=str(d.id),
                   reason="Commercial outreach draft - sending is never automatic"))
    return back(request, "/sponsors")


@app.post("/jobs/sponsor-research")
def run_sponsor_research(request: Request, csrf: str = Form(...), u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    queue.enqueue(s, "sponsor_research", {}, idempotency_key=f"sponsors:{datetime.now(timezone.utc).date()}")
    return back(request, "/sponsors")


# ------------------------------------------------------------------ agents / incidents
@app.get("/agents", response_class=HTMLResponse)
def agents_page(request: Request, u: str = Depends(user), s: Session = Depends(db)):
    runs = s.execute(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(60)).scalars().all()
    jobs = s.execute(select(WorkflowJob).order_by(WorkflowJob.created_at.desc()).limit(60)).scalars().all()
    counts = dict(s.execute(select(WorkflowJob.status, func.count()).group_by(WorkflowJob.status)).all())
    workers = s.execute(select(SystemSetting).where(SystemSetting.key.like("worker_heartbeat:%"))).scalars().all()
    sched = s.get(SystemSetting, "scheduler_heartbeat")
    return render(request, "agents.html", {"runs": runs, "jobs": jobs, "counts": counts, "workers": workers,
                                           "sched": sched, "schedule": datasources.schedule_overview(s, get_config(s)),
                                           "queued": counts.get("queued", 0)}, u, s)


@app.post("/jobs/{jid}/retry")
def retry_job(request: Request, jid: uuid.UUID, csrf: str = Form(...), u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    j = s.get(WorkflowJob, jid)
    if j.status in ("dead", "blocked", "failed"):
        j.status, j.run_at, j.attempts = "queued", datetime.now(timezone.utc), 0
        audit(s, f"user:{u}", "job.retried", "workflow_job", jid)
    return back(request, "/agents")


@app.post("/jobs/{jid}/cancel")
def cancel_job(request: Request, jid: uuid.UUID, csrf: str = Form(...), u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    queue.cancel(s, jid)
    audit(s, f"user:{u}", "job.cancelled", "workflow_job", jid)
    return back(request, "/agents")


@app.post("/jobs/run/{job_type}")
def run_now(request: Request, job_type: str, csrf: str = Form(...), u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    allowed = {"health_check", "content_planning", "daily_report", "analytics_collect", "trend_discovery",
               "strategy_analysis", "weekly_review"}
    if job_type not in allowed:
        raise HTTPException(400, "job type not runnable from the dashboard")
    queue.enqueue(s, job_type, {"manual": True})
    audit(s, f"user:{u}", "job.manual_run", "workflow_job", None, type=job_type)
    return back(request)


@app.get("/incidents", response_class=HTMLResponse)
def incidents(request: Request, u: str = Depends(user), s: Session = Depends(db)):
    items = s.execute(select(Notification).order_by(Notification.acknowledged_at.is_not(None),
                                                    Notification.created_at.desc()).limit(100)).scalars().all()
    return render(request, "incidents.html", {"items": items}, u, s)


@app.post("/incidents/{nid}/ack")
def ack(request: Request, nid: uuid.UUID, resolution: str = Form(""), csrf: str = Form(...), u: str = Depends(user),
        s: Session = Depends(db)):
    check_csrf(u, csrf)
    n = s.get(Notification, nid)
    n.acknowledged_at, n.acknowledged_by, n.resolution = datetime.now(timezone.utc), u, resolution or None
    audit(s, f"user:{u}", "incident.acknowledged", "notification", nid, resolution=resolution)
    return back(request, "/incidents")


# ------------------------------------------------------------------ controls + settings
@app.post("/controls/{flag}/{state}")
def control(request: Request, flag: str, state: str, csrf: str = Form(...), u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    if flag not in ("publishing_paused", "automation_paused") or state not in ("on", "off"):
        raise HTTPException(400)
    _setting(s, flag, state == "on", u)
    if flag == "publishing_paused" and state == "on":
        from waitwhy.notify import alert
        alert(s, "high", "controls", "ALL PUBLISHING PAUSED", f"by {u} from the dashboard", dedupe_key=None, push=True)
    return back(request)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, u: str = Depends(user), s: Session = Depends(db)):
    overrides = s.execute(select(SystemSetting).order_by(SystemSetting.key)).scalars().all()
    from waitwhy import prompts
    return render(request, "settings.html", {"overrides": overrides, "creds": coo.credential_status(),
                                             "prompts": prompts.list_prompts(),
                                             "cfg_json": json.dumps(get_config(s), indent=1, default=str)}, u, s)


@app.post("/settings")
def save_setting(request: Request, key: str = Form(...), value: str = Form(...), confirm: str = Form(""),
                 csrf: str = Form(...), u: str = Depends(user), s: Session = Depends(db)):
    check_csrf(u, csrf)
    cfg = get_config(s)
    if key.startswith(("worker_heartbeat", "scheduler_heartbeat", "last_")):
        raise HTTPException(400, "system-managed key")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = value
    if key in cfg.get("protected_keys", []) and confirm.strip() != f"I AUTHORIZE {key}":
        raise HTTPException(400, f"'{key}' is protected: type exactly 'I AUTHORIZE {key}' to confirm")
    if key == "operating_mode" and parsed not in ("supervised", "controlled", "autonomous"):
        raise HTTPException(400, "invalid mode")
    _setting(s, key, parsed, u)
    if key in cfg.get("protected_keys", []):
        s.add(Approval(kind="setting_change", status="approved", decided_by=f"user:{u}",
                       decided_at=datetime.now(timezone.utc), reason=f"{key} -> {parsed}",
                       payload={"key": key, "value": parsed}))
    return back(request, "/settings")


# ------------------------------------------------------------------ JSON API (for n8n / scripts / mobile)
@app.get("/api/status")
def api_status(u: str = Depends(user), s: Session = Depends(db)):
    cfg = get_config(s)
    return {"budget": budget.status(s, cfg), "inventory": coo.inventory(s),
            "health": (s.get(SystemSetting, "last_health") or SystemSetting(value=None)).value}


@app.get("/api/videos")
def api_videos(u: str = Depends(user), s: Session = Depends(db)):
    return [{"id": str(v.id), "title": v.title, "state": v.state, "updated_at": v.updated_at.isoformat()}
            for v in s.execute(select(Video).order_by(Video.updated_at.desc())).scalars()]


@app.post("/api/jobs/{job_type}")
def api_enqueue(job_type: str, payload: dict | None = None, u: str = Depends(user), s: Session = Depends(db)):
    if job_type not in queue.JOB_SPECS:
        raise HTTPException(400, "unknown job type")
    j = queue.enqueue(s, job_type, payload or {})
    audit(s, f"user:{u}", "job.api_enqueue", "workflow_job", j.id, type=job_type)
    return {"job_id": str(j.id)}
