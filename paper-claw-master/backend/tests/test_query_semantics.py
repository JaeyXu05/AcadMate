from backend.mentor_workflow.query_semantics import (
    build_query_contract,
    candidate_relevance,
    qualifies,
)
from backend.mentor_workflow.schemas import CandidateMentor


def _candidate(topics: list[str], *, topics_source: int = 1) -> CandidateMentor:
    return CandidateMentor(
        candidate_id="ustc_test",
        mentor_name="测试导师",
        research_topics=topics,
        source_metadata={"topics_source": topics_source},
    )


def test_query_contract_preserves_specificity():
    contract = build_query_contract("生成式人工智能", ["生成式人工智能"])
    assert contract.canonical_query == "生成式人工智能"
    assert contract.must_preserve == ["生成式"]
    assert "人工智能" in contract.excluded_generalizations


def test_parent_ai_does_not_qualify_for_generative_ai():
    contract = build_query_contract("生成式人工智能", ["生成式人工智能"])
    score, match_type, _ = candidate_relevance(contract, _candidate(["人工智能", "机器学习"]))
    assert not qualifies(score, match_type)


def test_same_boundary_child_can_qualify_but_fallback_is_discounted():
    contract = build_query_contract("生成式人工智能", ["生成式人工智能"])
    candidate = _candidate(["大语言模型", "扩散模型"])
    primary, match_type, _ = candidate_relevance(contract, candidate)
    fallback, _, _ = candidate_relevance(contract, candidate, fallback=True)
    assert match_type == "ADJACENT"
    assert qualifies(primary, match_type)
    assert fallback < primary


def test_inferred_topic_cannot_qualify_as_fact():
    contract = build_query_contract("推荐系统", ["推荐系统"])
    score, match_type, _ = candidate_relevance(contract, _candidate(["推荐系统"], topics_source=2))
    assert not qualifies(score, match_type)


def test_application_ai_is_not_generative_research():
    contract = build_query_contract("生成式人工智能", ["生成式人工智能"])
    score, match_type, _ = candidate_relevance(contract, _candidate(["人工智能", "地震预测"]))
    assert not qualifies(score, match_type)


def test_parent_token_overlap_does_not_qualify():
    contract = build_query_contract("图神经网络", ["图神经网络"])
    score, match_type, _ = candidate_relevance(contract, _candidate(["人工智能"]))
    assert not qualifies(score, match_type)


def test_raw_query_overrides_model_topic_collapse():
    contract = build_query_contract(
        "请帮我找生成式人工智能方向的导师",
        ["人工智能", "机器学习"],
    )
    assert contract.canonical_query == "生成式人工智能"
    assert contract.must_preserve == ["生成式"]
    assert "人工智能" in contract.excluded_generalizations


def test_explicit_or_is_preserved_in_contract():
    contract = build_query_contract("推荐系统或信息检索", ["推荐系统", "信息检索"])
    assert contract.logic == "OR"
    assert [item.canonical for item in contract.concepts] == ["推荐系统", "信息检索"]


def test_explicit_and_remains_required_intersection():
    contract = build_query_contract("计算机视觉和多模态生成")
    assert contract.logic == "AND"
    assert len(contract.concepts) == 2


def test_query_contract_records_all_family_boundaries():
    contract = build_query_contract("图神经网络和推荐系统")
    assert contract.semantic_boundary == "multi_concept"
    assert set(contract.semantic_boundaries) == {"graph_learning", "recommender_systems"}
