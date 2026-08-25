from fastapi.testclient import TestClient

from app.main import app, repository


def test_health_endpoint(monkeypatch):
    monkeypatch.setattr(repository, "ping", lambda: True)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_human_decision_is_stored(monkeypatch):
    stored = []
    monkeypatch.setattr(repository, "ping", lambda: True)
    monkeypatch.setattr(repository, "seed_demo", lambda *args: None)
    monkeypatch.setattr(repository, "store_decision", lambda *args: stored.append(args))
    with TestClient(app) as client:
        conflict = client.get("/api/review").json()["conflicts"][0]
        response = client.post(
            f"/api/conflicts/{conflict['conflict_id']}/decision",
            json={"decision": "intentional_change", "reviewer": "A. Rivera", "note": "Director approved"},
        )
    assert response.status_code == 200
    assert stored[0][1].value == "intentional_change"


def test_report_has_designed_html_and_download(monkeypatch):
    monkeypatch.setattr(repository, "seed_demo", lambda *args: None)
    monkeypatch.setattr(repository, "store_agent_run", lambda *args: None)
    with TestClient(app) as client:
        html = client.get("/api/report")
        text = client.get("/api/report?format=txt")
    assert html.status_code == 200
    assert html.headers["content-type"].startswith("text/html")
    assert "Pickup checklist" in html.text
    assert "Print / PDF" in html.text
    assert text.headers["content-disposition"].endswith('wrapcheck-continuity-report.txt"')
