from fastapi.testclient import TestClient

from app.main import app, handoff_runs, repository


def _disable_persistence(monkeypatch):
    for name in ("seed_demo", "store_agent_run", "store_handoff_inputs", "store_media_copies", "store_handoff_run", "store_handoff_decision", "store_handoff_release"):
        monkeypatch.setattr(repository, name, lambda *args, **kwargs: None)


def test_handoff_api_recovery_release_and_report(monkeypatch):
    _disable_persistence(monkeypatch)
    handoff_runs.clear()
    with TestClient(app) as client:
        run = client.post("/api/handoff/runs", json={"scenario_id": "missing-media"}).json()
        assert run["status"] == "hold_media"
        assert len(run["findings"]) == 2
        for finding in run["findings"]:
            response = client.post(
                f"/api/handoff/findings/{finding['finding_id']}/decision",
                json={"decision": "recovered", "reviewer": "Ari Kapoor", "note": "Verified"},
            )
            assert response.status_code == 200
        resolved = response.json()
        assert resolved["status"] == "ready_for_release"
        released = client.post(
            f"/api/handoff/runs/{resolved['run_id']}/release",
            json={"reviewer": "Ari Kapoor", "note": "Two copies verified"},
        )
        assert released.status_code == 200
        assert released.json()["status"] == "released_by_dit"
        report = client.get(f"/api/handoff/runs/{resolved['run_id']}/report?format=txt")
        assert "WRAPCHECK MEDIA DELIVERY RELEASE" in report.text
        assert "Ari Kapoor" in report.text


def test_released_handoff_is_immutable(monkeypatch):
    _disable_persistence(monkeypatch)
    handoff_runs.clear()
    with TestClient(app) as client:
        run = client.post("/api/handoff/runs", json={"scenario_id": "clean-handoff"}).json()
        released = client.post(
            f"/api/handoff/runs/{run['run_id']}/release",
            json={"reviewer": "Ari Kapoor", "note": "Verified"},
        ).json()
        assert released["status"] == "released_by_dit"
        second = client.post(
            f"/api/handoff/runs/{run['run_id']}/release",
            json={"reviewer": "Ari Kapoor", "note": "Again"},
        )
        assert second.status_code == 409
