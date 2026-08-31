"""Typed concept extraction and relation judging for Retrieval Manager V2.

The old workflow treated every expansion as an undifferentiated keyword.  This
module keeps user concepts intact and gives a candidate topic a typed relation
to a query concept.  The small registry below is a seed ontology, not the
retriever itself; unknown concept pairs are handled by the generic lexical
judge and can later be upgraded by an optional model-backed judge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from backend.mentor_workflow.schemas import (
    InputSource,
    QueryConcept,
    QueryConceptRole,
)


class Relation:
    EXACT = "EXACT"
    SYNONYM = "SYNONYM"
    SUBFIELD = "SUBFIELD"
    SUPERFIELD = "SUPERFIELD"
    METHOD_FOR = "METHOD_FOR"
    APPLICATION_OF = "APPLICATION_OF"
    RELATED = "RELATED"
    UNKNOWN = "UNKNOWN"
    UNRELATED = "UNRELATED"


QUALIFYING_RELATIONS = {
    Relation.EXACT,
    Relation.SYNONYM,
    Relation.SUBFIELD,
}


@dataclass(frozen=True)
class ConceptFamily:
    concept_id: str
    aliases: tuple[str, ...]
    children: tuple[str, ...] = ()
    parents: tuple[str, ...] = ()
    canonical: str | None = None


# A deliberately small seed set covers the regressions already observed in the
# product.  New domains are not required to be added here: the generic judge
# still handles phrase containment and shared anchors without changing the raw
# query.
CONCEPT_FAMILIES: tuple[ConceptFamily, ...] = (
    ConceptFamily(
        "generative_ai",
        (
            "生成式人工智能",
            "generative ai",
            "生成模型",
            "大语言模型",
            "大模型",
            "llm",
            "扩散模型",
            "diffusion model",
            "foundation model",
        ),
        children=(
            "生成模型",
            "大语言模型",
            "大模型",
            "llm",
            "扩散模型",
            "diffusion model",
            "foundation model",
        ),
        parents=("人工智能", "ai", "机器学习", "深度学习"),
    ),
    ConceptFamily(
        "recommender_systems",
        (
            "推荐系统",
            "recommender system",
            "recommendation system",
            "推荐算法",
            "协同过滤",
            "collaborative filtering",
            "排序学习",
            "learning to rank",
            "ctr预估",
            "点击率预估",
            "推荐大模型",
        ),
        children=(
            "推荐算法",
            "协同过滤",
            "collaborative filtering",
            "排序学习",
            "learning to rank",
            "ctr预估",
            "点击率预估",
            "推荐大模型",
        ),
        parents=("人工智能", "ai", "机器学习", "数据科学", "大数据"),
    ),
    ConceptFamily(
        "multimodal_generation",
        (
            "多模态生成",
            "multimodal generation",
            "文生图",
            "text-to-image",
            "视觉语言生成",
        ),
        children=("文生图", "text-to-image", "视觉语言生成"),
        parents=("多模态", "multimodal", "人工智能", "机器学习"),
    ),
    ConceptFamily(
        "multi_agent_reinforcement_learning",
        (
            "multi-agent reinforcement learning",
            "multi agent reinforcement learning",
            "多智能体强化学习",
            "多智能体强化学习",
            "marl",
        ),
        children=("multi-agent reinforcement learning", "多智能体强化学习", "marl"),
        parents=("强化学习", "reinforcement learning", "人工智能", "机器学习"),
        canonical="multi-agent reinforcement learning",
    ),
    ConceptFamily(
        "graph_learning",
        (
            "图学习",
            "图神经网络",
            "graph learning",
            "graph neural network",
            "gnn",
        ),
        children=("图神经网络", "graph neural network", "gnn"),
        parents=("机器学习", "machine learning", "人工智能", "ai"),
        canonical="graph learning",
    ),
)


GENERIC_PARENTS = {
    normalize
    for normalize in (
        "人工智能",
        "ai",
        "artificial intelligence",
        "机器学习",
        "machine learning",
        "深度学习",
        "deep learning",
        "数据科学",
        "data science",
        "计算机科学",
        "computer science",
    )
}


_WRAPPER_RE = re.compile(
    r"^(?:请(?:问|帮我)?|麻烦|帮我)?(?:想要?)?"
    r"(?:找(?:一下|一找)?|搜索|检索|\bfind\b|\bsearch\b|\brecommend\b)(?:一下|\s+)?(?:做|研究)?",
    flags=re.IGNORECASE,
)
_RECOMMEND_WRAPPER_RE = re.compile(
    r"^推荐(?:(?:一下|一些|几个|几位)?(?:导师|老师|教授|方向|学者|人))",
    flags=re.IGNORECASE,
)
_TAIL_RE = re.compile(
    r"(?:方向)?(?:的)?(?:导师|老师|教授|博导|mentor|mentors|professor|professors)s?$",
    flags=re.IGNORECASE,
)
_SPLIT_RE = re.compile(r"\s*(?:和|与|以及|及|、|,|，|;|；|\+|/|或)\s*")
_STOP_CONCEPT_RE = re.compile(
    r"^(?:方向|研究方向|相关方向|导师|老师|教授|博导|领域|方面)$"
)


def clean_query_text(value: str) -> str:
    text = " ".join(str(value or "").split()).strip("。.!！?？,，;；")
    text = _WRAPPER_RE.sub("", text)
    # ``推荐`` is a wrapper only when it explicitly introduces a person or
    # direction request.  In ``推荐系统``/``推荐算法`` it is a core domain
    # token and must never be stripped.
    text = _RECOMMEND_WRAPPER_RE.sub("", text)
    text = _TAIL_RE.sub("", text)
    text = text.strip("。.!！?？,，;；")
    return text or " ".join(str(value or "").split()).strip("。.!！?？,，;；")


def extract_query_concepts(
    raw_query: str,
    topics: Iterable[str] = (),
    methods: Iterable[str] = (),
    applications: Iterable[str] = (),
) -> list[QueryConcept]:
    """Extract concepts while preserving user phrasing and field roles."""

    raw = clean_query_text(raw_query)
    topic_values = list(topics)
    method_values = list(methods)
    application_values = list(applications)
    supplied = _unique([*topic_values, *method_values, *application_values])
    surfaces: list[tuple[str, QueryConceptRole, bool, InputSource]] = []
    if raw:
        # Split only explicit coordination.  A phrase such as "大模型推荐"
        # remains intact instead of being silently rewritten to "大模型".
        pieces = [piece.strip() for piece in _SPLIT_RE.split(raw) if piece.strip()]
        for piece in pieces or [raw]:
            if not _STOP_CONCEPT_RE.fullmatch(piece):
                surfaces.append((piece, QueryConceptRole.core_topic, True, InputSource.text))
    if not surfaces:
        for value in supplied:
            if _normalize(value) in {_normalize(item[0]) for item in surfaces}:
                continue
            role = QueryConceptRole.core_topic
            if value in method_values:
                role = QueryConceptRole.method
            elif value in application_values:
                role = QueryConceptRole.application_domain
            surfaces.append((value, role, role == QueryConceptRole.core_topic, InputSource.keyword))
    # Explicit structured fields supplement the raw query but never replace it.
    for value in method_values:
        if not _contains_surface(surfaces, value):
            surfaces.append((value, QueryConceptRole.method, False, InputSource.keyword))
    for value in application_values:
        if not _contains_surface(surfaces, value):
            surfaces.append((value, QueryConceptRole.application_domain, False, InputSource.keyword))

    concepts: list[QueryConcept] = []
    for index, (surface, role, required, source) in enumerate(surfaces, start=1):
        canonical = canonical_for(surface)
        preserved = preserved_tokens(surface, canonical)
        concepts.append(
            QueryConcept(
                concept_id=f"query_concept_{index}",
                surface=surface,
                canonical=canonical,
                role=role,
                required=required,
                must_preserve=preserved,
                source=source,
            )
        )
    return concepts


def canonical_for(value: str) -> str:
    text = clean_query_text(value)
    normalized = _normalize(text)
    family = family_for(normalized)
    if family is None:
        return text
    # Only canonicalise when the family alias is the whole cleaned phrase or a
    # phrase separated by wrappers.  Compound text remains intact.
    matches = [alias for alias in family.aliases if _normalize(alias) == normalized]
    if family.canonical:
        return family.canonical
    return max(matches, key=lambda item: len(_normalize(item)), default=text)


def preserved_tokens(surface: str, canonical: str) -> list[str]:
    normalized = _normalize(canonical)
    family = family_for(normalized)
    if family:
        if family.concept_id == "generative_ai" and "生成式" in normalized:
            return ["生成式"]
        if family.concept_id == "recommender_systems" and "推荐" in normalized:
            return ["推荐"]
        if family.concept_id == "multimodal_generation":
            return [token for token in ("多模态", "生成") if token in normalized] or [canonical]
    return [canonical] if canonical else [surface]


def family_for(value: str) -> ConceptFamily | None:
    normalized = _normalize(value)
    matches = [
        family
        for family in CONCEPT_FAMILIES
        if any(_normalize(alias) in normalized for alias in family.aliases)
    ]
    return max(matches, key=lambda item: max(map(lambda alias: len(_normalize(alias)), item.aliases)), default=None)


def expanded_terms_for(concepts: Iterable[QueryConcept]) -> list[str]:
    terms: list[str] = []
    for concept in concepts:
        family = family_for(concept.canonical)
        if family:
            terms.extend(
                alias for alias in (*family.aliases, *family.children)
                if _normalize(alias) != _normalize(concept.canonical)
            )
    return _unique(terms)


def excluded_generalizations_for(concepts: Iterable[QueryConcept]) -> list[str]:
    values: list[str] = []
    for concept in concepts:
        family = family_for(concept.canonical)
        values.extend(family.parents if family else GENERIC_PARENTS)
    return _unique(values)


@dataclass(frozen=True)
class RelationJudgement:
    relation: str
    score: float
    matched_anchor: str | None = None
    reason: str = ""


def judge_relation(
    query: QueryConcept | str,
    candidate_topic: str,
    *,
    candidate_role: str = "PRIMARY_INTEREST",
) -> RelationJudgement:
    """Judge one query concept against one structured mentor assertion."""

    query_text = query.canonical if isinstance(query, QueryConcept) else str(query)
    query_norm = _normalize(query_text)
    candidate_norm = _normalize(candidate_topic)
    if not query_norm or not candidate_norm:
        return RelationJudgement(Relation.UNRELATED, 0.0, reason="empty_concept")
    if query_norm == candidate_norm:
        return RelationJudgement(
            Relation.EXACT,
            100.0,
            matched_anchor=query_text,
            reason="candidate assertion contains the canonical query",
        )
    query_family = family_for(query_norm)
    candidate_family = family_for(candidate_norm)
    if query_norm in candidate_norm:
        return RelationJudgement(
            Relation.EXACT,
            100.0,
            matched_anchor=query_text,
            reason="candidate assertion contains the canonical query",
        )
    if candidate_norm in query_norm and len(candidate_norm) >= 2:
        if query_family and candidate_norm in {
            _normalize(item) for item in query_family.parents
        }:
            return RelationJudgement(
                Relation.SUPERFIELD,
                35.0,
                matched_anchor=candidate_topic,
                reason="candidate is a parent concept",
            )
        return RelationJudgement(
            Relation.SUBFIELD,
            84.0,
            matched_anchor=candidate_topic,
            reason="candidate assertion is a narrower expression",
        )

    if query_family and candidate_family:
        if query_family.concept_id == candidate_family.concept_id:
            if candidate_norm in {
                _normalize(item) for item in candidate_family.children
            } and candidate_norm != query_norm:
                return RelationJudgement(
                    Relation.SUBFIELD,
                    84.0,
                    matched_anchor=candidate_topic,
                    reason="registered subfield of the query family",
                )
            if query_norm in {_normalize(item) for item in candidate_family.aliases} and candidate_norm in {
                _normalize(item) for item in candidate_family.aliases
            }:
                return RelationJudgement(
                    Relation.SYNONYM,
                    96.0,
                    matched_anchor=candidate_topic,
                    reason="same registered concept family",
                )
        if candidate_norm in {_normalize(item) for item in query_family.parents}:
            return RelationJudgement(
                Relation.SUPERFIELD,
                35.0,
                matched_anchor=candidate_topic,
                reason="candidate is a parent concept",
            )

    if query_family and candidate_norm in {
        _normalize(item) for item in query_family.parents
    }:
        return RelationJudgement(
            Relation.SUPERFIELD,
            35.0,
            matched_anchor=candidate_topic,
            reason="candidate is a parent concept",
        )

    must_preserve = (
        query.must_preserve if isinstance(query, QueryConcept) else preserved_tokens(query_text, query_text)
    )
    missing_preserve = [token for token in must_preserve if _normalize(token) not in candidate_norm]
    if missing_preserve and query_family:
        return RelationJudgement(
            Relation.UNRELATED,
            0.0,
            reason=f"missing must-preserve token: {','.join(missing_preserve)}",
        )

    q_tokens = _content_tokens(query_norm)
    c_tokens = _content_tokens(candidate_norm)
    shared = q_tokens & c_tokens
    if not shared:
        return RelationJudgement(Relation.UNRELATED, 0.0, reason="no_content_anchor")
    overlap = len(shared) / max(len(q_tokens), 1)
    similarity = SequenceMatcher(None, query_norm, candidate_norm).ratio()
    if overlap >= 0.75 or similarity >= 0.86:
        return RelationJudgement(
            Relation.SYNONYM,
            90.0,
            matched_anchor=next(iter(shared)),
            reason="high structured phrase overlap",
        )
    if overlap >= 0.35 and must_preserve and all(
        _normalize(token) in candidate_norm for token in must_preserve
    ):
        return RelationJudgement(
            Relation.SUBFIELD,
            76.0,
            matched_anchor=next(iter(shared)),
            reason="shared required anchor with a narrower assertion",
        )
    if overlap >= 0.25:
        return RelationJudgement(
            Relation.RELATED,
            55.0,
            matched_anchor=next(iter(shared)),
            reason="limited lexical relation; requires review",
        )
    return RelationJudgement(Relation.UNKNOWN, 20.0, reason="weak lexical signal")


def best_relation(
    concept: QueryConcept,
    topics: Iterable[str],
    methods: Iterable[str] = (),
    applications: Iterable[str] = (),
) -> RelationJudgement:
    topic_values = [str(value) for value in topics]
    method_values = [str(value) for value in methods]
    application_values = [str(value) for value in applications]
    # A core topic must be supported by a primary-interest assertion.  A
    # shared method (e.g. reinforcement learning) is not allowed to substitute
    # for an unrelated research topic (e.g. computer vision).
    if concept.role == QueryConceptRole.core_topic:
        values: list[tuple[str, str]] = [
            (value, "PRIMARY_INTEREST") for value in topic_values
        ]
    else:
        values = [(value, "PRIMARY_INTEREST") for value in topic_values]
        values.extend((value, "METHOD") for value in method_values)
        values.extend((value, "APPLICATION_DOMAIN") for value in application_values)
    if concept.role == QueryConceptRole.method:
        values = [(value, "METHOD") for value in method_values]
    elif concept.role == QueryConceptRole.application_domain:
        values = [(value, "APPLICATION_DOMAIN") for value in application_values]
    judgements = [
        judge_relation(concept, value, candidate_role=role) for value, role in values
    ]
    return max(judgements, key=lambda item: item.score, default=RelationJudgement(Relation.UNRELATED, 0.0))


def _content_tokens(value: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9][a-z0-9\-.]*", value.casefold()))
    chars = re.findall(r"[一-鿿]", value)
    words.update(chars)
    words.update(chars[index] + chars[index + 1] for index in range(len(chars) - 1))
    return {word for word in words if word not in {"的", "与", "和", "及", "相关"}}


def _contains_surface(surfaces: list[tuple[str, QueryConceptRole, bool, InputSource]], value: str) -> bool:
    return any(_normalize(surface) == _normalize(value) for surface, *_ in surfaces)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def normalize(value: str) -> str:
    """Public normalizer used by compatibility code and diagnostics."""

    return _normalize(value)


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value).split()).strip()
        key = _normalize(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result
