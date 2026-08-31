from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers import mentor_workflows
from backend.api.routers.mentor_workflows import MentorWorkflowRuntime
from backend.mentor_workflow.orchestrator import MentorWorkflowOrchestrator
from backend.mentor_workflow.schemas import (
    CandidateMentor,
    EvidenceFreshness,
    EvidenceRecord,
    MentorResearchResult,
)
from backend.mentor_workflow.state_store import InMemoryStateStore


class OfflineResearchTool:
    def __init__(self) -> None:
        evidence = EvidenceRecord(
            evidence_id="ev-api-1",
            candidate_id="mentor-api-1",
            source_type="ustc_official_faculty_profile",
            source_uri="fixture://mentor-api-1",
            title="Verified MARL Paper",
            extracted_fact="Professor A authored verified work on multi-agent reinforcement learning.",
            locator="fixture:1",
            freshness=EvidenceFreshness.current,
            confidence=0.95,
            query="multi-agent reinforcement learning",
            query_relevance=0.92,
            entity_verified=True,
            support_type="DIRECT",
            source_level="L1",
            metadata={
                "identity_verified": True,
                "mentor_role_verified": True,
                "supports_fields": "research_topics,methods,publications",
            },
        )
        self.result = MentorResearchResult(
            candidates=[
                CandidateMentor(
                    candidate_id="mentor-api-1",
                    mentor_name="Professor A",
                    research_topics=[
                        "multi-agent reinforcement learning",
                        "graph learning",
                    ],
                    methods=["reinforcement learning"],
                    publications=["Verified MARL Paper"],
                    evidence_refs=[evidence.evidence_id],
                    missing_fields=[
                        "affiliation",
                        "department",
                        "projects",
                        "homepage",
                        "recruitment_status",
                    ],
                    source_metadata={"topics_source": 1},
                )
            ],
            evidence=[evidence],
        )

    def search_local(self, _intent, _judgements) -> MentorResearchResult:
        return self.result.model_copy(deep=True)

    def search_fallback(self, _intent, _judgements) -> MentorResearchResult:
        return MentorResearchResult(used_fallback=True)


@pytest.fixture()
def mentor_client():
    store = InMemoryStateStore()
    orchestrator = MentorWorkflowOrchestrator(store, OfflineResearchTool())
    runtime = MentorWorkflowRuntime(
        store=store,
        orchestrator=orchestrator,
        commit=lambda: None,
        run_id=lambda _trace_id: None,
    )
    app = FastAPI()
    app.include_router(mentor_workflows.router, prefix="/api")
    app.dependency_overrides[mentor_workflows.get_mentor_workflow_runtime] = lambda: (
        runtime
    )
    with TestClient(app) as client:
        yield client


def test_create_and_query_pending_mentor_workflow(mentor_client):
    response = mentor_client.post(
        "/api/mentor-workflows",
        json={
            "message": "find AI mentors",
            "research_topics": ["artificial intelligence"],
            "execute_immediately": False,
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["status"] == "PENDING"
    assert created["run_id"] is None

    status = mentor_client.get(f"/api/mentor-workflows/{created['trace_id']}/status")
    events = mentor_client.get(f"/api/mentor-workflows/{created['trace_id']}/events")

    assert status.status_code == 200
    assert status.json()["current_stage"] == "input_understanding"
    assert [event["event_type"] for event in events.json()] == ["WORKFLOW_CREATED"]


def test_mentor_workflow_api_requests_clarification(mentor_client):
    response = mentor_client.post(
        "/api/mentor-workflows",
        json={"message": "帮我找导师"},
    )

    assert response.status_code == 200
    trace_id = response.json()["trace_id"]
    state = mentor_client.get(f"/api/mentor-workflows/{trace_id}").json()

    assert state["status"] == "CLARIFICATION_REQUIRED"
    assert state["candidates"] == []
    assert state["clarification_request"]["missing_fields"] == ["research_topics"]


def test_mentor_workflow_api_exposes_completed_auditable_result(mentor_client):
    response = mentor_client.post(
        "/api/mentor-workflows",
        json={
            "message": "find MARL mentors",
            "research_topics": ["multi-agent reinforcement learning"],
            "methods": ["reinforcement learning"],
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["status"] == "COMPLETED"
    trace_id = created["trace_id"]

    candidates = mentor_client.get(f"/api/mentor-workflows/{trace_id}/candidates")
    matches = mentor_client.get(f"/api/mentor-workflows/{trace_id}/matches")
    evidence = mentor_client.get(f"/api/mentor-workflows/{trace_id}/evidence")
    review = mentor_client.get(f"/api/mentor-workflows/{trace_id}/review")
    audit = mentor_client.get(f"/api/mentor-workflows/{trace_id}/audit")
    result = mentor_client.get(f"/api/mentor-workflows/{trace_id}/result")

    assert candidates.status_code == matches.status_code == evidence.status_code == 200
    assert candidates.json()[0]["mentor_name"] == "Professor A"
    assert matches.json()[0]["evidence_refs"] == candidates.json()[0]["evidence_refs"]
    assert evidence.json()[0]["source_uri"].startswith("fixture:")
    assert review.json()["status"] == "PASS"
    assert audit.status_code == 200
    assert audit.json() is None
    assert result.json()["mentors"][0]["candidate"]["mentor_name"] == "Professor A"


def test_mentor_workflow_api_accepts_supplement_and_resumes(mentor_client):
    created = mentor_client.post(
        "/api/mentor-workflows", json={"message": "帮我找导师"}
    ).json()

    response = mentor_client.post(
        f"/api/mentor-workflows/{created['trace_id']}/input",
        json={
            "message": "帮我找图学习导师",
            "research_topics": ["graph learning"],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["candidates"][0]["mentor_name"] == "Professor A"


def test_mentor_workflow_unknown_trace_returns_404(mentor_client):
    assert mentor_client.get("/api/mentor-workflows/not-found").status_code == 404
