from __future__ import annotations


def test_health(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mentor_ready_is_available_without_chat_when_deterministic(client):
    response = client.get("/api/mentor-ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["mode"] == "deterministic"
    assert payload["dependencies"]["chat_required"] is False
