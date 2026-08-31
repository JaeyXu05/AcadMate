from __future__ import annotations

from backend.harness.contracts import RunCreate, SharedContext
from backend.harness.mentor_skill import start_mentor_match


class _FakeState:
    trace_id = "trace-mentor"
    status = "created"


def test_growth_directions_go_to_background_not_research_topics():
    captured: dict = {}

    class FakeOrchestrator:
        def create(self, request):
            captured["request"] = request
            return _FakeState()

    start_mentor_match(
        RunCreate(
            message="推荐系统",
            context=SharedContext(
                growth={
                    "directions": ["几何拓扑", "邮政编码：230026", "动力系统"],
                    "direction_hypotheses": [
                        {"direction": "表示论", "review_status": "PASS"}
                    ],
                },
                profile={"interests": ["代数几何"]},
            ),
        ),
        FakeOrchestrator(),
        lambda: None,
        lambda _trace: 7,
    )

    request = captured["request"]
    assert request.message == "推荐系统"
    assert request.research_topics == []
    assert "代数几何" in request.user_profile.background
    assert "几何拓扑" in request.user_profile.background
    assert "表示论" in request.user_profile.background
    assert "邮政编码：230026" not in request.user_profile.background
