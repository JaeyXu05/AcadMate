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


def test_academic_label_alias_qualifies_without_lowering_threshold():
    contract = build_query_contract("概率论", ["概率论"])
    score, match_type, _ = candidate_relevance(contract, _candidate(["概率统计"]))

    assert match_type == "ADJACENT"
    assert qualifies(score, match_type)


def test_cross_discipline_alias_qualifies_but_incidental_words_do_not():
    contract = build_query_contract("隐私保护机器学习", ["隐私保护机器学习"])
    score, match_type, _ = candidate_relevance(contract, _candidate(["隐私计算"]))
    assert qualifies(score, match_type)

    remote = build_query_contract("遥感变化检测", ["遥感变化检测"])
    score, match_type, _ = candidate_relevance(
        remote,
        _candidate(["气候变化背景下的极端事件检测归因"]),
    )
    assert not qualifies(score, match_type)


def test_raw_query_overrides_model_topic_collapse():
    contract = build_query_contract(
        "请帮我找生成式人工智能方向的导师",
        ["人工智能", "机器学习"],
    )
    assert contract.canonical_query == "生成式人工智能"
    assert contract.must_preserve == ["生成式"]
    assert "人工智能" in contract.excluded_generalizations


def test_english_llm_alias_matches_chinese_profile_label():
    contract = build_query_contract("large language model", ["large language model"])
    score, match_type, _ = candidate_relevance(contract, _candidate(["大语言模型"]))

    assert match_type == "DIRECT"
    assert qualifies(score, match_type)


def test_natural_language_request_is_not_collapsed_to_one_embedded_alias():
    contract = build_query_contract(
        "我想做用大模型辅助医学文本分析的研究",
        ["我想做用大模型辅助医学文本分析的研究"],
    )

    assert "医学文本分析" in contract.canonical_query
    score, match_type, _ = candidate_relevance(
        contract,
        _candidate(["大语言模型", "自然语言处理"]),
    )
    assert not qualifies(score, match_type)


def test_retrieval_signal_breaks_same_relation_score_ties():
    contract = build_query_contract("计算机视觉", ["计算机视觉"])
    high = _candidate(["计算机视觉"])
    low = _candidate(["计算机视觉"])
    high.source_metadata["retrieve_score"] = 35.0
    low.source_metadata["retrieve_score"] = 7.0

    high_score, _, high_breakdown = candidate_relevance(contract, high)
    low_score, _, low_breakdown = candidate_relevance(contract, low)

    assert high_score > low_score
    assert high_breakdown["retrieval_signal"] > low_breakdown["retrieval_signal"]


def test_dense_signal_uses_its_native_scale_without_lexical_saturation():
    contract = build_query_contract("计算机视觉", ["计算机视觉"])
    high = _candidate(["计算机视觉"])
    low = _candidate(["计算机视觉"])
    high.source_metadata.update({"dense_score": 0.80, "retrieve_score": 80.0})
    low.source_metadata.update({"dense_score": 0.70, "retrieve_score": 70.0})

    high_score, _, _ = candidate_relevance(contract, high)
    low_score, _, _ = candidate_relevance(contract, low)

    assert high_score > low_score
    assert high_score < 100


def test_compound_hydrogen_fuel_cell_field_is_not_split_into_hard_and():
    contract = build_query_contract("氢能与燃料电池", ["氢能与燃料电池"])
    score, match_type, _ = candidate_relevance(
        contract,
        _candidate(["氢燃料电池系统设计与优化"]),
    )

    assert contract.logic == "OR"
    assert contract.canonical_query == "氢能与燃料电池"
    assert qualifies(score, match_type)


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
