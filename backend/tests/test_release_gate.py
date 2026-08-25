from fastapi.testclient import TestClient

from app.fixtures import fixture_gate_run
from app.gate import evaluate_requirements, gate_status
from app.main import app, repository, runs
from app.models import DemoRunRequest, FindingDecision, ObservationResult


def test_flawed_candidate_creates_two_blocking_findings():
    run, _ = fixture_gate_run(DemoRunRequest(candidate_asset_id="candidate-flawed"))
    assert run.status == "hold_setup"
    assert {item.finding_type.value for item in run.findings} == {
        "mismatch", "missing_required_beat",
    }
    assert all(item.severity == "blocking" for item in run.findings)


def test_clean_candidate_is_ready_for_human_signoff():
    run, _ = fixture_gate_run(DemoRunRequest(candidate_asset_id="candidate-clean"))
    assert run.findings == []
    assert run.status == "ready_for_supervisor_signoff"


def test_uncertain_evidence_never_blocks_or_creates_pickup():
    run, observations = fixture_gate_run(DemoRunRequest(candidate_asset_id="candidate-flawed"))
    reference = [item for item in observations if item.take_id == "take-reference"]
    candidate = [item for item in observations if item.take_id == "take-flawed"]
    candidate[0] = candidate[0].model_copy(
        update={"result": ObservationResult.uncertain, "confidence": 0.4}
    )
    findings = evaluate_requirements(run.run_id, run.brief.requirements, reference, candidate)
    mug = next(item for item in findings if item.requirement_id == "mug-position")
    assert mug.severity == "review"
    assert mug.finding_type == "uncertain"
    assert gate_status([mug])[0] == "needs_supervisor_review"


def _disable_persistence(monkeypatch):
    for name in (
        "seed_demo", "store_agent_run", "store_scene_requirements",
        "store_requirement_observations", "store_wrap_run",
        "store_finding_decision", "store_clearance",
    ):
        monkeypatch.setattr(repository, name, lambda *args, **kwargs: None)


def test_release_gate_api_requires_human_resolution_and_clearance(monkeypatch):
    _disable_persistence(monkeypatch)
    runs.values.clear()
    with TestClient(app) as client:
        created = client.post(
            "/api/demo/runs", json={"candidate_asset_id": "candidate-flawed"}
        )
        assert created.status_code == 200
        run = created.json()
        assert run["status"] == "hold_setup"

        for finding in run["findings"]:
            response = client.post(
                f"/api/findings/{finding['finding_id']}/decision",
                json={
                    "decision": FindingDecision.intentional_change,
                    "reviewer": "A. Rivera",
                    "note": "Director-approved story change",
                },
            )
            assert response.status_code == 200

        resolved = response.json()
        assert resolved["status"] == "ready_for_supervisor_signoff"
        cleared = client.post(
            f"/api/runs/{resolved['run_id']}/clearance",
            json={"reviewer": "A. Rivera", "note": "Evidence reviewed"},
        )
        assert cleared.status_code == 200
        assert cleared.json()["status"] == "cleared_by_supervisor"

        report = client.get(f"/api/runs/{resolved['run_id']}/report?format=txt")
        assert report.status_code == 200
        assert "SETUP RELEASE HANDOFF" in report.text
        assert "A. Rivera" in report.text


def test_pickup_decision_keeps_setup_on_hold(monkeypatch):
    _disable_persistence(monkeypatch)
    runs.values.clear()
    with TestClient(app) as client:
        run = client.post(
            "/api/demo/runs", json={"candidate_asset_id": "candidate-flawed"}
        ).json()
        finding = run["findings"][0]
        response = client.post(
            f"/api/findings/{finding['finding_id']}/decision",
            json={"decision": "pickup", "reviewer": "A. Rivera", "note": "Reset and go again"},
        )
    assert response.json()["status"] == "hold_setup"
    assert response.json()["pickup_count"] == 1
