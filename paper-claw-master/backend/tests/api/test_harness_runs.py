from __future__ import annotations

from backend.db.models import AgentRun
from backend.db.types import RunStatus, WorkflowName
from backend.schemas import RetrievedChunk
from backend.settings import clear_settings_cache


def test_paper_harness_creates_real_agent_run_and_reviews_retrieval(
    client,
    session,
    monkeypatch,
):
    monkeypatch.setenv("PAPER_CLAW_CHAT_MODEL", "openai:gpt-test")
    clear_settings_cache()
    monkeypatch.setattr(
        "backend.harness.paper_skill._load_mentor",
        lambda candidate_id: {
            "candidate_id": candidate_id,
            "mentor_name": "测试导师",
            "research_topics": ["computer vision"],
            "publications": ["Evidence Driven Vision"],
        },
    )
    monkeypatch.setattr(
        "backend.api.routers.runs.execute_agent_run",
        lambda run_id: None,
    )
    monkeypatch.setattr(
        "backend.harness.paper_skill.RetrievalService.retrieve",
        lambda self, paper_id, query, limit=8: [
            RetrievedChunk(
                chunk_id=41,
                processed_document_id=7,
                content_text="The method uses an evidence-aware visual encoder.",
                score=0.91,
                retrieval_mode="vector",
                metadata={"heading_path": ["Method"]},
            ),
            RetrievedChunk(
                chunk_id=42,
                processed_document_id=7,
                content_text="Experiments compare the encoder on detection benchmarks.",
                score=0.88,
                retrieval_mode="vector",
                metadata={"heading_path": ["Experiments"]},
            ),
        ],
    )

    response = client.post(
        "/api/runs",
        json={
            "skill_id": "paper_qa",
            "message": "阅读这位导师的论文",
            "context": {
                "user_id": "student-1",
                "candidate_id": "ustc_faculty_test",
                "growth": {"matched_mentors": [{"id": "ustc_faculty_test"}]},
            },
        },
    )

    assert response.status_code == 200
    created = response.json()
    run_id = int(created["run_id"])
    run = session.get(AgentRun, run_id)
    assert run is not None
    assert run.workflow == WorkflowName.paper_qa.value
    assert run.input_json["metadata"]["harness_skill_id"] == "paper_qa"
    assert created["review_status"] == "PENDING"

    run.status = RunStatus.succeeded.value
    run.output_json = {"message": "没有引用 chunk 的阅读结论"}
    session.commit()

    revise_response = client.get(f"/api/runs/{run_id}/harness-result")
    assert revise_response.status_code == 200
    assert revise_response.json()["review_status"] == "REVISE"
    assert revise_response.json()["suggested_next_skill"] == "paper_qa"

    run.output_json = {"message": "只引用一条证据 [chunk:41]"}
    session.commit()
    one_cite = client.get(f"/api/runs/{run_id}/harness-result")
    assert one_cite.status_code == 200
    assert one_cite.json()["review_status"] == "REVISE"

    run.output_json = {
        "message": (
            "方法使用 evidence-aware visual encoder [chunk:41]，"
            "并在 detection benchmarks 上比较 [chunk:42]。"
        )
    }
    session.commit()
    result_response = client.get(f"/api/runs/{run_id}/harness-result")
    assert result_response.status_code == 200
    result = result_response.json()
    assert result["review_status"] == "PASS"
    assert result["evidence_refs"] == [
        f"paper_chunk:{run.input_json['active_paper_id']}:41",
        f"paper_chunk:{run.input_json['active_paper_id']}:42",
    ]
    assert result["artifact"]["retrieved_chunks"][0]["content"].startswith("The method")
    assert result["artifact"]["research_tasks"][0]["status"] == "pending"
    assert result["artifact"]["retry"] is None


def test_paper_harness_does_not_pass_without_retrieved_evidence(session):
    from backend.harness.paper_skill import paper_qa_result

    run = AgentRun(
        workflow=WorkflowName.paper_qa.value,
        status=RunStatus.succeeded.value,
        input_json={
            "active_paper_id": 999999,
            "metadata": {
                "candidate_id": "ustc_faculty_test",
                "mentor_name": "测试导师",
                "publication_titles": ["Missing Paper"],
                "query": "Missing Paper",
            },
        },
        output_json={"message": "无证据回答"},
    )
    session.add(run)
    session.commit()

    result = paper_qa_result(run.id, session)

    assert result.review_status == "NEED_MORE_INPUT"
    assert result.evidence_refs == []
    assert result.artifact is not None
    assert result.artifact["research_tasks"] == []
    assert result.artifact["retry"]["skill_id"] == "paper_qa"
    assert result.artifact["retry"]["target"] == "paper_artifacts"


def test_paper_harness_waits_for_existing_artifact_upload_when_no_chunks(
    client,
    session,
    monkeypatch,
):
    monkeypatch.setenv("PAPER_CLAW_CHAT_MODEL", "openai:gpt-test")
    clear_settings_cache()
    monkeypatch.setattr(
        "backend.harness.paper_skill._load_mentor",
        lambda candidate_id: {
            "candidate_id": candidate_id,
            "mentor_name": "测试导师",
            "research_topics": ["computer vision"],
            "publications": ["Evidence Driven Vision"],
        },
    )
    monkeypatch.setattr(
        "backend.api.routers.runs.execute_agent_run",
        lambda run_id: None,
    )
    monkeypatch.setattr(
        "backend.harness.paper_skill.RetrievalService.retrieve",
        lambda self, paper_id, query, limit=8: [],
    )

    response = client.post(
        "/api/runs",
        json={
            "skill_id": "paper_qa",
            "message": "阅读这位导师的论文",
            "context": {"candidate_id": "ustc_faculty_test"},
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["status"] == "waiting_for_user"
    assert created["review_status"] == "NEED_MORE_INPUT"
    assert created["artifact"]["retry"]["skill_id"] == "paper_qa"
    assert created["artifact"]["retry"]["target"] == "paper_artifacts"
    assert created["artifact"]["retry"]["existing_api"] == "POST /api/agent/paper-upload"
    run = session.get(AgentRun, int(created["run_id"]))
    assert run is not None
    assert run.status == "waiting_for_user"


def test_pdf_analyze_does_not_invent_mentors_without_text(client):
    response = client.post(
        "/api/runs",
        json={
            "skill_id": "pdf_analyze",
            "message": "分析这份 PDF",
            "context": {"document_id": "doc-scan", "pages": []},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["review_status"] == "NEED_MORE_INPUT"
    assert payload["artifact"]["advisors"] == []
    assert "不会按论文数" in payload["artifact"]["error"]


def test_direction_explore_needs_reviewed_mentors(client):
    response = client.post(
        "/api/runs",
        json={
            "skill_id": "direction_explore",
            "message": "形成探索方向",
            "context": {"growth": {}},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["review_status"] == "NEED_MORE_INPUT"
    assert payload["skill_id"] == "direction_explore"


def test_direction_explore_emits_evidence_backed_hypotheses(client):
    response = client.post(
        "/api/runs",
        json={
            "skill_id": "direction_explore",
            "message": "形成探索方向",
            "context": {
                "growth": {
                    "matched_mentors": [
                        {
                            "id": "ustc_faculty_test",
                            "tags": ["computer vision"],
                            "evidence_refs": ["ustc_faculty_test_profile"],
                        }
                    ]
                }
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["review_status"] == "PASS"
    assert payload["artifact"]["direction_hypotheses"][0]["evidence_refs"] == [
        "ustc_faculty_test_profile"
    ]


def test_research_task_requires_cited_paper_evidence(client):
    blocked = client.post(
        "/api/runs",
        json={
            "skill_id": "research_task",
            "message": "随便写一个问题",
            "context": {"growth": {"read_papers": []}},
        },
    )
    assert blocked.json()["review_status"] == "NEED_MORE_INPUT"

    revise = client.post(
        "/api/runs",
        json={
            "skill_id": "research_task",
            "message": "研究问题不够具体",
            "context": {
                "growth": {
                    "read_papers": [
                        {
                            "candidate_id": "ustc_faculty_test",
                            "review_status": "PASS",
                            "evidence_refs": ["paper_chunk:1:41", "paper_chunk:1:42"],
                        }
                    ]
                }
            },
        },
    )
    assert revise.json()["review_status"] == "REVISE"

    passed = client.post(
        "/api/runs",
        json={
            "skill_id": "research_task",
            "message": "视觉编码器是否可迁移？ paper_chunk:1:41 paper_chunk:1:42",
            "context": {
                "task_id": "research-question:ustc_faculty_test",
                "growth": {
                    "read_papers": [
                        {
                            "candidate_id": "ustc_faculty_test",
                            "review_status": "PASS",
                            "evidence_refs": ["paper_chunk:1:41", "paper_chunk:1:42"],
                        }
                    ],
                    "research_tasks": [
                        {
                            "id": "research-question:ustc_faculty_test",
                            "status": "pending",
                            "evidence_refs": ["paper_chunk:1:41"],
                        }
                    ],
                },
            },
        },
    )
    assert passed.json()["review_status"] == "PASS"
    assert passed.json()["evidence_refs"] == ["paper_chunk:1:41", "paper_chunk:1:42"]
