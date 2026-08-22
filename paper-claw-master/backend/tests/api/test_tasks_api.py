from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.api.routers import tasks
from backend.db.models import ArxivTaskPaper, ArxivTaskPaperSubscription, ArxivTaskSubscription
from backend.db.types import ArxivTaskJobStatus


def test_arxiv_task_status_includes_subscriptions(client, session):
    subscription = ArxivTaskSubscription(name="Machine learning", query="cat:cs.LG", description="ML query", enabled=True)
    session.add(subscription)
    session.commit()

    response = client.get("/api/tasks/arxiv/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled_subscription_ids"] == [subscription.id]
    assert payload["coverage_subscription_ids"] == []
    assert payload["daily_config"]["run_time"] == "08:00"
    item = payload["subscriptions"][0]
    assert item["name"] == "Machine learning"
    assert item["query"] == "cat:cs.LG"
    assert item["description"] == "ML query"
    assert item["enabled"] is True


def test_arxiv_task_subscription_create_preserves_query_source(client, session):
    response = client.post(
        "/api/tasks/arxiv/subscriptions",
        json={"name": "Agents", "query": "  cat:cs.AI AND (ti:agent OR abs:agent)  ", "description": None, "enabled": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "  cat:cs.AI AND (ti:agent OR abs:agent)  "


def test_arxiv_task_subscription_test_query_reports_timeout(client, monkeypatch):
    class FailingService:
        def __init__(self, session):
            pass

        def test_query(self, query: str, *, max_results: int = 5):
            import httpx

            raise httpx.ReadTimeout("read operation timed out")

    monkeypatch.setattr(tasks, "ArxivTaskService", FailingService)

    response = client.post("/api/tasks/arxiv/subscriptions/test-query", json={"query": "cat:cs.AI", "max_results": 3})

    assert response.status_code == 504
    assert response.json()["detail"] == "arXiv query test timed out after 45 seconds. Refine the query and try again."


def test_arxiv_task_subscription_test_query_reports_rate_limit(client, monkeypatch):
    class FailingService:
        def __init__(self, session):
            pass

        def test_query(self, query: str, *, max_results: int = 5):
            import httpx

            request = httpx.Request("GET", "https://export.arxiv.org/api/query")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("too many requests", request=request, response=response)

    monkeypatch.setattr(tasks, "ArxivTaskService", FailingService)

    response = client.post("/api/tasks/arxiv/subscriptions/test-query", json={"query": "cat:cs.AI", "max_results": 3})

    assert response.status_code == 429
    assert response.json()["detail"] == "arXiv rate limit reached. Wait a few seconds and try again."


def test_arxiv_task_papers_accepts_published_window_filter(client, session):
    subscription = ArxivTaskSubscription(name="Machine learning", query="cat:cs.LG", enabled=True)
    paper = ArxivTaskPaper(
        arxiv_id="2401.00001v1",
        arxiv_base_id="2401.00001",
        title="A harvested paper",
        authors_json=["Ada Lovelace"],
        categories_json=["cs.LG"],
        published_at=datetime(2024, 1, 1, 12, tzinfo=UTC),
        first_seen_at=datetime(2024, 1, 1, 12, tzinfo=UTC),
        last_seen_at=datetime(2024, 1, 1, 12, tzinfo=UTC),
        raw_json={},
    )
    session.add_all([subscription, paper])
    session.flush()
    session.add(ArxivTaskPaperSubscription(paper_id=paper.id, subscription_id=subscription.id, query_snapshot=subscription.query, created_at=datetime(2024, 1, 1, tzinfo=UTC)))
    session.commit()

    response = client.get(
        "/api/tasks/arxiv/papers",
        params={
            "subscription_id": subscription.id,
            "published_start": "2024-01-01T00:00:00Z",
            "published_end": "2024-01-02T00:00:00Z",
        },
    )

    assert response.status_code == 200
    assert [item["arxiv_base_id"] for item in response.json()] == ["2401.00001"]


    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=1)

    response = client.post(
        "/api/tasks/arxiv/history-jobs",
        json={"subscription_ids": [999], "start_time": start.isoformat(), "end_time": end.isoformat()},
    )

    assert response.status_code == 400


def test_arxiv_history_job_lifecycle(client, session):
    subscription = ArxivTaskSubscription(name="Machine learning", query="cat:cs.LG", enabled=False)
    session.add(subscription)
    session.commit()
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=1)

    create_response = client.post(
        "/api/tasks/arxiv/history-jobs",
        json={"subscription_ids": [subscription.id], "start_time": start.isoformat(), "end_time": end.isoformat()},
    )
    assert create_response.status_code == 200
    job_id = create_response.json()["id"]
    assert create_response.json()["status"] == ArxivTaskJobStatus.paused.value
    assert create_response.json()["subscription_ids"] == [subscription.id]

    start_response = client.post(f"/api/tasks/arxiv/history-jobs/{job_id}/start")
    assert start_response.status_code == 200
    assert start_response.json()["status"] == ArxivTaskJobStatus.running.value

    pause_response = client.post(f"/api/tasks/arxiv/history-jobs/{job_id}/pause")
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == ArxivTaskJobStatus.paused.value

    stop_response = client.post(f"/api/tasks/arxiv/history-jobs/{job_id}/stop")
    assert stop_response.status_code == 200
    assert stop_response.json()["status"] == ArxivTaskJobStatus.stopped.value
