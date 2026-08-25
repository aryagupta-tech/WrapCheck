import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse

from .api_middleware import install_api_middleware
from .comparison import compare_observations, recommendation
from .config import get_settings
from .delivery_router import create_delivery_router
from .durable import DurableStore
from .schema import ensure_delivery_schema
from .fixtures import (
    CURRENT_OBSERVATIONS, CURATED_ASSETS, PRODUCTION, REFERENCE_OBSERVATIONS, TAKES,
    fixture_gate_run, release_gate_brief, workflow_steps,
)
from .gate import evaluate_requirements, gate_status, refresh_run_state
from .handoff_fixtures import DATA_ROOT, fixture_handoff_run, load_handoff_inputs
from .handoff_gate import handoff_status, reconcile_media, refresh_handoff
from .handoff_models import (
    ExpectedTake, HandoffDecisionRequest, HandoffReleaseRequest, HandoffRun,
    HandoffRunRequest, MediaFile,
)
from .handoff_reporting import render_handoff_html, render_handoff_text
from .models import (
    AuditEvent, ClearanceRequest, DecisionRequest, DemoRunRequest, FindingDecisionRequest,
    LiveRunRequest, RequirementObservation, SceneRequirement, ReviewSnapshot, WrapRun,
)
from .repository import ClickHouseRepository, DecisionStore, RunStore
from .reporting import (
    render_html_report, render_text_report, render_wrap_html_report, render_wrap_text_report,
)
from .services.adk_workflow import ContinuityAgent, MediaHandoffAgent, WrapGateAgent
from .services.gemini import GeminiAnalyzer
from .services.uploads import validate_upload
from .services.session import signed_session_hash

logger = logging.getLogger(__name__)
settings = get_settings()
repository = ClickHouseRepository(settings)
durable = DurableStore(repository)
decisions = DecisionStore()
runs = RunStore()
handoff_runs: dict[str, HandoffRun] = {}
database_state: dict[str, bool | str | None] = {"seeded": False, "error": None}


def _find_handoff_by_finding(finding_id: str) -> HandoffRun | None:
    return durable.find_run_by_finding(finding_id)


async def _build_live_handoff(payload: HandoffRunRequest) -> HandoffRun:
    if not settings.media_handoff_ready:
        raise HTTPException(
            status_code=503,
            detail="Live media handoff needs Google Cloud Agent Builder, ClickHouse, and a private MCP endpoint.",
        )
    run_id = str(uuid4())
    expected, media, documents = load_handoff_inputs(run_id, payload.scenario_id)
    repository.store_handoff_inputs(expected, media)
    repository.store_media_copies(media)
    started = perf_counter()
    agent = MediaHandoffAgent(settings)
    context = await agent.retrieve_context(run_id)
    mcp_ms = round((perf_counter() - started) * 1000)
    retrieved_expected = [ExpectedTake.model_validate(item) for item in context.get("expectations", [])]
    retrieved_media = [MediaFile.model_validate(item) for item in context.get("inventory", [])]
    if not retrieved_expected:
        raise HTTPException(status_code=503, detail="ClickHouse MCP returned no media expectations.")
    checks, findings = reconcile_media(run_id, retrieved_expected, retrieved_media)
    status, reason = handoff_status(findings)
    run = HandoffRun(
        run_id=run_id, mode="live",
        mode_disclaimer="Live Gemini ADK agent retrieval through the official read-only ClickHouse MCP. Deterministic code sets the gate.",
        scenario_id=payload.scenario_id, production=payload.production, shoot_day=payload.shoot_day,
        delivery_name=payload.delivery_name,
        camera_cards=sorted({item.card_id for item in retrieved_expected}),
        source_documents=documents, checks=checks, findings=findings, status=status,
        status_reason=reason, audit=[
            {"step":"ingest_delivery_records","service":"clickhouse-connect","status":"complete","duration_ms":4,"summary":f"{len(expected)} expectations and {len(media)} media rows appended."},
            {"step":"retrieve_delivery_context","service":"Gemini ADK · official mcp-clickhouse","status":"complete","duration_ms":mcp_ms,"summary":agent.last_summary or "The agent retrieved this delivery through MCP.","query":"\n\n".join(context.get("queries", []))},
            {"step":"reconcile_media","service":"Deterministic policy","status":"complete","duration_ms":2,"summary":f"{len(findings)} operational discrepancy item(s) produced."},
        ],
    )
    repository.store_handoff_run(run)
    durable.save_run(run)
    return run


def build_demo_snapshot() -> ReviewSnapshot:
    conflicts = compare_observations(
        REFERENCE_OBSERVATIONS, CURRENT_OBSERVATIONS, settings.blocking_confidence_threshold
    )
    for conflict in conflicts:
        conflict.decision = decisions.get(conflict.conflict_id)
    status, reason = recommendation(conflicts)
    return ReviewSnapshot(
        mode="demo",
        mode_disclaimer="Fixture observations + real deterministic comparison. No Gemini, ADK, or MCP call is represented as live.",
        production=PRODUCTION,
        takes=TAKES,
        observations=REFERENCE_OBSERVATIONS + CURRENT_OBSERVATIONS,
        conflicts=conflicts,
        workflow=workflow_steps(
            persistence_ok=bool(database_state["seeded"]),
            persistence_error=str(database_state["error"]) if database_state["error"] else None,
        ),
        recommendation=status,
        recommendation_reason=reason,
    )


def _persist_fixture_gate(run: WrapRun, observations: list[RequirementObservation]) -> None:
    if not database_state["seeded"]:
        run.audit.append(AuditEvent(
            step="persist_release_gate", service="ClickHouse",
            status="skipped", duration_ms=0,
            summary="ClickHouse is unavailable; fixture state remains in this local process.",
        ))
        return
    try:
        repository.store_scene_requirements(run.brief)
        repository.store_requirement_observations(observations)
        repository.store_wrap_run(run)
        run.audit.append(AuditEvent(
            step="persist_release_gate", service="clickhouse-connect",
            status="complete", duration_ms=4,
            summary="Scenario events appended to ClickHouse and kept explicitly labelled as fixtures.",
        ))
    except Exception as exc:
        logger.info("Fixture gate remains available without ClickHouse: %s", exc)


async def _build_live_gate(request: DemoRunRequest) -> WrapRun:
    if not settings.release_gate_ready:
        raise HTTPException(
            status_code=503,
            detail="Live release gate needs Google Cloud plus all three CURATED_*_GCS_URI values.",
        )
    run_id = str(uuid4())
    brief = release_gate_brief(request)
    reference_asset = CURATED_ASSETS["reference"]
    candidate_asset = CURATED_ASSETS[request.candidate_asset_id]
    gcs_uris = {
        "reference": settings.curated_reference_gcs_uri,
        "candidate-clean": settings.curated_clean_gcs_uri,
        "candidate-flawed": settings.curated_flawed_gcs_uri,
    }
    analyzer = GeminiAnalyzer(settings)
    started = perf_counter()
    reference = analyzer.analyze_requirements_gcs(
        gcs_uris["reference"], run_id, brief, reference_asset.take_id,
    )
    candidate = analyzer.analyze_requirements_gcs(
        gcs_uris[request.candidate_asset_id], run_id, brief, candidate_asset.take_id,
    )
    analyze_ms = round((perf_counter() - started) * 1000)
    repository.store_scene_requirements(brief)
    repository.store_requirement_observations(reference + candidate)

    mcp_started = perf_counter()
    agent = WrapGateAgent(settings)
    context = await agent.retrieve_context(
        brief.production_id, brief.scene_id, brief.setup_id,
        reference_asset.take_id, candidate_asset.take_id, run_id,
    )
    mcp_ms = round((perf_counter() - mcp_started) * 1000)
    retrieved_requirements = [
        SceneRequirement.model_validate(item) for item in context.get("requirements", [])
    ]
    retrieved_observations = [
        RequirementObservation.model_validate(item) for item in context.get("observations", [])
    ]
    if not retrieved_requirements or not retrieved_observations:
        raise HTTPException(status_code=503, detail="ClickHouse MCP returned no grounded wrap context.")
    latest = {}
    for item in retrieved_observations:
        latest.setdefault((item.take_id, item.requirement_id), item)
    reference_from_mcp = [
        item for (take, _), item in latest.items() if take == reference_asset.take_id
    ]
    candidate_from_mcp = [
        item for (take, _), item in latest.items() if take == candidate_asset.take_id
    ]
    findings = evaluate_requirements(
        run_id, retrieved_requirements, reference_from_mcp, candidate_from_mcp,
        settings.blocking_confidence_threshold,
    )
    status, reason = gate_status(findings)
    queries = context.get("queries", [])
    run = WrapRun(
        run_id=run_id, mode="live",
        mode_disclaimer="Live Gemini analysis and read-only ClickHouse MCP retrieval. Human clearance remains authoritative.",
        brief=brief, reference_asset=reference_asset, candidate_asset=candidate_asset,
        findings=findings, status=status, status_reason=reason, pickup_count=0,
        audit=[
            {
                "step": "analyze_declared_requirements", "service": f"Vertex AI · {settings.gemini_model}",
                "status": "complete", "duration_ms": analyze_ms,
                "summary": f"{len(reference) + len(candidate)} grounded observations produced from two clips.",
            },
            {
                "step": "persist_observations", "service": "clickhouse-connect",
                "status": "complete", "duration_ms": 0,
                "summary": "Requirements and timestamped observations appended to ClickHouse.",
            },
            {
                "step": "retrieve_wrap_context", "service": "Google ADK · official mcp-clickhouse",
                "status": "complete", "duration_ms": mcp_ms,
                "summary": agent.last_summary or "The ADK agent retrieved both takes and the declared scene requirements.",
                "query": "\n\n".join(queries),
            },
            {
                "step": "evaluate_release_gate", "service": "Deterministic policy",
                "status": "complete", "duration_ms": 1,
                "summary": f"{len(findings)} actionable finding(s); the model did not set gate status.",
            },
        ],
    )
    repository.store_wrap_run(run)
    return run


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        ensure_delivery_schema(repository)
        snapshot = build_demo_snapshot()
        repository.seed_demo(PRODUCTION.model_dump(), snapshot.observations, snapshot.conflicts)
        database_state["seeded"] = True
        database_state["error"] = None
        repository.store_agent_run(
            PRODUCTION.production_id,
            PRODUCTION.scene_id,
            "demo",
            "fixtures/no-model",
            workflow_steps(persistence_ok=True),
        )
    except Exception as exc:
        database_state["seeded"] = False
        database_state["error"] = str(exc)
        logger.warning("ClickHouse seed deferred: %s", exc)
    yield


app = FastAPI(title="WrapCheck API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)


app.include_router(create_delivery_router(settings, durable, repository))
install_api_middleware(app, repository)

@app.get("/health")
def health():
    return {"status": "ok", "mode": settings.app_mode, "clickhouse": "ok" if repository.ping() else "unavailable"}


@app.get("/api/review", response_model=ReviewSnapshot)
def review():
    return build_demo_snapshot()


@app.post("/api/conflicts/{conflict_id}/decision", response_model=ReviewSnapshot)
def decide(conflict_id: str, request: DecisionRequest):
    snapshot = build_demo_snapshot()
    if conflict_id not in {item.conflict_id for item in snapshot.conflicts}:
        raise HTTPException(status_code=404, detail="Conflict not found")
    decisions.set(conflict_id, request.decision)
    try:
        repository.store_decision(conflict_id, request.decision, request.reviewer, request.note)
    except Exception as exc:
        logger.warning("Decision retained in this session; ClickHouse append failed: %s", exc)
    return build_demo_snapshot()


@app.post("/api/uploads/validate")
async def upload(file: UploadFile = File(...)):
    return await validate_upload(file, settings.max_upload_mb)


@app.get("/api/live/readiness")
def live_readiness():
    return {
        "ready": settings.release_gate_ready,
        "requirements": [] if settings.release_gate_ready else [
            "Set GOOGLE_CLOUD_PROJECT", "Provide Application Default Credentials",
            "Set all three CURATED_*_GCS_URI values",
        ],
        "gemini_model": settings.gemini_model,
        "mcp_url": settings.clickhouse_mcp_url,
    }


@app.get("/api/demo/config")
def demo_config():
    return {
        "mode": "live" if settings.app_mode == "live" else "fixture",
        "live_ready": settings.release_gate_ready,
        "assets": [item.model_dump() for item in CURATED_ASSETS.values()],
        "defaults": DemoRunRequest().model_dump(),
    }


@app.post("/api/demo/runs", response_model=WrapRun)
async def create_demo_run(payload: DemoRunRequest, request: Request, response: Response):
    session_hash = signed_session_hash(settings, request, response)
    if settings.app_mode == "live":
        try:
            if repository.demo_runs_in_window(session_hash) >= settings.demo_runs_per_10_minutes:
                raise HTTPException(status_code=429, detail="Demo quota reached. Try again in ten minutes.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Demo quota service is unavailable.") from exc
        run = await _build_live_gate(payload)
        repository.record_demo_run(session_hash, run.run_id)
    else:
        run, observations = fixture_gate_run(payload)
        _persist_fixture_gate(run, observations)
    return runs.put(run)


@app.get("/api/runs/{run_id}", response_model=WrapRun)
def get_run(run_id: str):
    run = runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Wrap check not found")
    return run


@app.post("/api/findings/{finding_id}/decision", response_model=WrapRun)
def decide_finding(finding_id: str, payload: FindingDecisionRequest):
    run = runs.find_by_finding(finding_id)
    if not run:
        raise HTTPException(status_code=404, detail="Finding not found")
    if run.cleared_at:
        raise HTTPException(status_code=409, detail="A cleared run is immutable. Start a new wrap check.")
    finding = next(item for item in run.findings if item.finding_id == finding_id)
    finding.decision = payload.decision
    finding.reviewer_note = payload.note
    refresh_run_state(run)
    if run.mode == "live" or database_state["seeded"]:
        try:
            repository.store_finding_decision(finding_id, payload.decision, payload.reviewer, payload.note)
        except Exception as exc:
            logger.info("Decision remains in session; ClickHouse append failed: %s", exc)
    return runs.put(run)


@app.post("/api/runs/{run_id}/clearance", response_model=WrapRun)
def clear_run(run_id: str, payload: ClearanceRequest):
    run = runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Wrap check not found")
    if run.status.value != "ready_for_supervisor_signoff":
        raise HTTPException(status_code=409, detail="Resolve all blocking or uncertain findings before clearance.")
    run.cleared_by = payload.reviewer
    run.cleared_at = datetime.now(timezone.utc)
    refresh_run_state(run)
    if run.mode == "live" or database_state["seeded"]:
        try:
            repository.store_clearance(run, payload.reviewer, payload.note)
        except Exception as exc:
            logger.info("Clearance remains in session; ClickHouse append failed: %s", exc)
    return runs.put(run)


@app.get("/api/runs/{run_id}/report")
def wrap_report(run_id: str, format: str = "html"):
    run = runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Wrap check not found")
    if format == "txt":
        return PlainTextResponse(
            render_wrap_text_report(run),
            headers={"Content-Disposition": 'attachment; filename="wrapcheck-setup-handoff.txt"'},
        )
    return HTMLResponse(render_wrap_html_report(run))


@app.get("/api/assets/{asset_id}/playback")
def asset_playback(asset_id: str):
    if asset_id not in CURATED_ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    local = Path(__file__).resolve().parents[2] / "fixtures" / "media" / f"{asset_id}.mp4"
    if local.is_file():
        return FileResponse(local, media_type="video/mp4", filename=local.name)
    if settings.app_mode == "live" and settings.curated_media_bucket:
        try:
            from google.cloud import storage
            client = storage.Client(project=settings.google_cloud_project)
            blob = client.bucket(settings.curated_media_bucket).blob(f"{asset_id}.mp4")
            url = blob.generate_signed_url(version="v4", expiration=900, method="GET")
            return RedirectResponse(url)
        except Exception as exc:
            logger.warning("Could not sign playback URL: %s", exc)
    raise HTTPException(
        status_code=404,
        detail=f"Record and place fixtures/media/{asset_id}.mp4 to enable playback.",
    )


@app.post("/api/live/run")
async def live_run(request: LiveRunRequest):
    if settings.app_mode != "live":
        raise HTTPException(status_code=409, detail="Set APP_MODE=live and configure Google Cloud credentials.")
    try:
        analyzer = GeminiAnalyzer(settings)
        context = request.model_dump(exclude={"reference_gcs_uri", "current_gcs_uri"})
        reference = analyzer.analyze_gcs_video(request.reference_gcs_uri, {**context, "take_id": request.reference_take_id})
        current = analyzer.analyze_gcs_video(request.current_gcs_uri, {**context, "take_id": request.current_take_id})
        repository.seed_demo(
            {"production_id": request.production_id, "title": "Live production"},
            reference + current,
            [],
        )
        agent = ContinuityAgent(settings)
        history_summary = await agent.retrieve_and_summarize(
            f"Retrieve continuity history for production_id={request.production_id} and scene_id={request.scene_id}, then summarize only retrieved evidence.",
            user_id="script-supervisor", session_id=f"{request.production_id}-{request.scene_id}",
        )
        conflicts = compare_observations(reference, current, settings.blocking_confidence_threshold)
        repository.store_conflicts(conflicts)
        return {
            "mode": "live", "observations": reference + current, "conflicts": conflicts,
            "mcp_trace": agent.last_mcp_trace, "adk_history_summary": history_summary,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/report")
def report(format: str = "html"):
    snapshot = build_demo_snapshot()
    if format == "txt":
        return PlainTextResponse(
            render_text_report(snapshot),
            headers={"Content-Disposition": 'attachment; filename="wrapcheck-continuity-report.txt"'},
        )
    return HTMLResponse(render_html_report(snapshot))


@app.get("/api/handoff/config")
def handoff_config():
    return {
        "mode": "live" if settings.app_mode == "live" else "fixture",
        "live_ready": settings.media_handoff_ready,
        "defaults": HandoffRunRequest().model_dump(),
        "scenarios": [
            {"scenario_id":"missing-media","label":"Problem delivery · 2 blockers","description":"Circled Take 7 sound is absent and A017 has only one verified backup copy."},
            {"scenario_id":"clean-handoff","label":"Recovered delivery · ready","description":"All camera, sound and checksum evidence reconciles."},
        ],
    }


@app.post("/api/handoff/runs", response_model=HandoffRun)
async def create_handoff_run(payload: HandoffRunRequest, request: Request, response: Response):
    if settings.app_mode == "live":
        session_hash = signed_session_hash(settings, request, response)
        try:
            session_count, global_count = repository.public_events_in_window(session_hash, "handoff_run")
            if session_count >= settings.demo_runs_per_10_minutes or global_count >= settings.global_runs_per_10_minutes:
                raise HTTPException(status_code=429, detail="Public demo quota reached. Try again in ten minutes.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Demo quota service is unavailable.") from exc
    if settings.app_mode == "live":
        run = await _build_live_handoff(payload)
        repository.record_public_event(session_hash, "handoff_run", run.run_id)
    else:
        run, expected, media = fixture_handoff_run(payload)
        if database_state["seeded"]:
            try:
                repository.store_handoff_inputs(expected, media)
                repository.store_media_copies(media)
                repository.store_handoff_run(run)
                durable.save_run(run)
                run.audit.append(AuditEvent(
                    step="persist_demo_events", service="ClickHouse", status="complete", duration_ms=4,
                    summary="Curated demo records were appended and remain labelled as fixtures.",
                ))
            except Exception as exc:
                logger.info("Fixture handoff remains available without ClickHouse: %s", exc)
    handoff_runs[run.run_id] = run
    if not database_state["seeded"]:
        try:
            durable.save_run(run)
        except Exception:
            pass
    return run


@app.get("/api/handoff/runs/{run_id}", response_model=HandoffRun)
def get_handoff_run(run_id: str):
    run = durable.get_run(run_id) or handoff_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Media handoff run not found")
    return run


@app.post("/api/handoff/findings/{finding_id}/decision", response_model=HandoffRun)
def decide_handoff_finding(finding_id: str, payload: HandoffDecisionRequest):
    run = _find_handoff_by_finding(finding_id)
    if not run:
        raise HTTPException(status_code=404, detail="Media discrepancy not found")
    if run.released_at:
        raise HTTPException(status_code=409, detail="A released delivery is immutable. Start a new verification run.")
    finding = next(item for item in run.findings if item.finding_id == finding_id)
    finding.decision = payload.decision
    finding.reviewer_note = payload.note
    refresh_handoff(run)
    if run.mode == "live" or database_state["seeded"]:
        try:
            repository.store_handoff_decision(finding_id, payload.decision, payload.reviewer, payload.note)
            durable.save_run(run)
        except Exception as exc:
            logger.info("Handoff decision remains in session; ClickHouse append failed: %s", exc)
    return run


@app.post("/api/handoff/runs/{run_id}/release", response_model=HandoffRun)
def release_handoff(run_id: str, payload: HandoffReleaseRequest):
    run = durable.get_run(run_id) or handoff_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Media handoff run not found")
    if run.status.value != "ready_for_release":
        raise HTTPException(status_code=409, detail="Resolve every discrepancy before releasing source cards.")
    run.released_by = payload.reviewer
    run.released_at = datetime.now(timezone.utc)
    refresh_handoff(run)
    if run.mode == "live" or database_state["seeded"]:
        try:
            repository.store_handoff_release(run_id, payload.reviewer, payload.note)
            durable.save_run(run)
        except Exception as exc:
            logger.info("Handoff release remains in session; ClickHouse append failed: %s", exc)
    return run


@app.get("/api/handoff/runs/{run_id}/report")
def handoff_report(run_id: str, format: str = "html"):
    run = durable.get_run(run_id) or handoff_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Media handoff run not found")
    if format == "txt":
        return PlainTextResponse(
            render_handoff_text(run),
            headers={"Content-Disposition": 'attachment; filename="wrapcheck-media-release.txt"'},
        )
    return HTMLResponse(render_handoff_html(run))


@app.get("/api/handoff/demo-files/{filename}")
def download_handoff_demo_file(filename: str):
    allowed = {
        "camera_report.csv", "sound_report.csv", "script_notes.csv",
        "manifest_problem.csv", "manifest_clean.csv",
    }
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="Demo file not found")
    return FileResponse(DATA_ROOT / filename, media_type="text/csv", filename=filename)
