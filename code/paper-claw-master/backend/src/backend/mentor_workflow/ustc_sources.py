from __future__ import annotations

import hashlib
import html
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from backend.integrations.paper_sources import paper_source_adapters_from_settings
from backend.mentor_workflow.schemas import (
    CandidateMentor,
    DomainJudgement,
    EvidenceFreshness,
    EvidenceRecord,
    IntentPacket,
    MentorResearchResult,
)
from backend.services.search import PaperSearchService

USTC_AFFILIATION = "中国科学技术大学"
USTC_FACULTY_SEARCH_PAGE = (
    "https://faculty.ustc.edu.cn/search.jsp?urltype=tree.TreeTempUrl&wbtreeid=1016"
)
USTC_FACULTY_SEARCH_ENDPOINT = (
    "https://faculty.ustc.edu.cn/system/resource/tsites/advancesearch.jsp"
)
USTC_ALL_TEACHING_UNITS_ID = ""
USTC_COLLEGE_IDS = {
    "数学科学学院": "1002",
    "信息科学技术学院": "1014",
    "计算机科学与技术学院": "1019",
    "人工智能与数据科学学院": "1155",
    "网络空间安全学院": "1154",
    "软件学院": "1023",
    "科技商学院、管理学院": "1010",
    "管理学院": "1010",
    "未来技术学院": "1280",
}
USTC_DOMAIN_COLLEGE_IDS = {
    "artificial_intelligence": ("1155", "1019", "1014", "1023", "1280"),
    "computer_systems": ("1019", "1014", "1023"),
    "cyber_security": ("1154", "1019", "1014"),
    "mathematics_statistics": ("1002", "1010"),
}


class InternalMentorRag(Protocol):
    """Interface reserved for the curated internal USTC mentor RAG store."""

    def retrieve(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult: ...


class NullInternalMentorRag:
    """Default until the curated internal RAG implementation is connected."""

    def retrieve(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult:
        return MentorResearchResult(
            warnings=[
                "The internal USTC mentor RAG adapter is not configured; "
                "continuing with official USTC sources."
            ],
            source_chain=["internal_ustc_rag"],
        )


@dataclass(frozen=True)
class UstcFacultyRecord:
    faculty_id: str
    name: str
    english_name: str
    college: str
    unit: str
    academic_title: str
    graduate_tutor_role: str
    doctoral_tutor_role: str
    profile_url: str

    @property
    def mentor_role(self) -> str:
        return "、".join(
            role
            for role in (self.doctoral_tutor_role, self.graduate_tutor_role)
            if role
        )

    @property
    def mentor_role_verified(self) -> bool:
        return bool(self.graduate_tutor_role or self.doctoral_tutor_role)


@dataclass(frozen=True)
class UstcFacultySearchPage:
    records: list[UstcFacultyRecord]
    total_pages: int
    total_records: int


class UstcFacultySearchGateway(Protocol):
    def search(
        self,
        *,
        teacher_name: str = "",
        research_direction: str = "",
        college_id: str = USTC_ALL_TEACHING_UNITS_ID,
        page_index: int = 1,
        page_size: int = 20,
    ) -> UstcFacultySearchPage: ...


class UstcProfileFetcher(Protocol):
    def fetch(self, url: str) -> str: ...


class HttpxUstcFacultyGateway:
    def __init__(
        self,
        *,
        endpoint: str = USTC_FACULTY_SEARCH_ENDPOINT,
        timeout_seconds: float = 15,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = _required_ustc_url(endpoint)
        self.timeout_seconds = timeout_seconds
        self.client = client

    def search(
        self,
        *,
        teacher_name: str = "",
        research_direction: str = "",
        college_id: str = USTC_ALL_TEACHING_UNITS_ID,
        page_index: int = 1,
        page_size: int = 20,
    ) -> UstcFacultySearchPage:
        params: dict[str, str | int] = {
            "collegeid": college_id,
            "disciplineid": "0",
            "enrollid": "0",
            "pageindex": max(1, page_index),
            "pagesize": max(1, min(page_size, 50)),
            "rankid": "",
            "degreeid": "0",
            "honorid": "",
            "pinyin": "",
            "profilelen": "100",
            "teacherName": teacher_name.strip(),
            "searchDirection": research_direction.strip(),
            "viewmode": "8",
            "viewid": "1066239",
            "siteOwner": "2006639312",
            "viewUniqueId": "1066239",
            "showlang": "zh_CN",
            "ispreview": "false",
            "basenum": "0",
            "ellipsis": "...",
            "alignright": "false",
            "productType": "0",
            "tutorType": "",
        }
        payload = self._get_json(params)
        raw_records = payload.get("teacherData")
        if not isinstance(raw_records, list):
            raise ValueError("USTC faculty search returned no teacherData list")
        return UstcFacultySearchPage(
            records=[
                record
                for item in raw_records
                if isinstance(item, dict)
                and (record := _faculty_record(item)) is not None
            ],
            total_pages=max(1, _safe_int(payload.get("totalpage"), 1)),
            total_records=max(0, _safe_int(payload.get("totalnum"), 0)),
        )

    def _get_json(self, params: dict[str, str | int]) -> dict:
        if self.client is not None:
            response = self.client.get(self.endpoint, params=params)
            return _validated_json_response(response)
        with httpx.Client(
            follow_redirects=True,
            timeout=self.timeout_seconds,
            trust_env=False,
            headers={"User-Agent": "Paper-Claw USTC mentor research"},
        ) as client:
            response = client.get(self.endpoint, params=params)
            return _validated_json_response(response)


class HttpxUstcProfileFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15,
        max_bytes: int = 2_000_000,
        client: httpx.Client | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.client = client

    def fetch(self, url: str) -> str:
        safe_url = _required_ustc_url(url)
        if self.client is not None:
            response = self.client.get(safe_url)
            return self._text(response)
        with httpx.Client(
            follow_redirects=True,
            timeout=self.timeout_seconds,
            trust_env=False,
            headers={"User-Agent": "Paper-Claw USTC mentor research"},
        ) as client:
            response = client.get(safe_url)
            return self._text(response)

    def _text(self, response: httpx.Response) -> str:
        response.raise_for_status()
        _required_ustc_url(str(response.url))
        content_type = response.headers.get("content-type", "").casefold()
        if "html" not in content_type:
            raise ValueError("USTC faculty profile did not return HTML")
        if len(response.content) > self.max_bytes:
            raise ValueError("USTC faculty profile exceeded the response size limit")
        return response.text


class UstcOfficialMentorSource:
    """Search the official USTC faculty portal, then inspect faculty profiles."""

    def __init__(
        self,
        gateway: UstcFacultySearchGateway,
        profile_fetcher: UstcProfileFetcher,
        *,
        college_id: str = USTC_ALL_TEACHING_UNITS_ID,
        page_size: int = 20,
        max_pages_per_query: int = 3,
        max_queries: int = 5,
        max_candidates: int = 30,
        broad_domain_discovery: bool = False,
    ) -> None:
        self.gateway = gateway
        self.profile_fetcher = profile_fetcher
        self.college_id = college_id
        self.page_size = page_size
        self.max_pages_per_query = max_pages_per_query
        self.max_queries = max_queries
        self.max_candidates = max_candidates
        self.broad_domain_discovery = broad_domain_discovery

    def search(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult:
        if not _scope_allows_ustc(intent):
            return MentorResearchResult(
                warnings=[
                    "The current deployment is limited to USTC, but the request "
                    "constrains results to a different institution."
                ],
                used_fallback=True,
                source_chain=["ustc_official_faculty"],
            )
        records, matched_terms, warnings = self._search_records(
            intent, domain_judgements
        )
        candidates: list[CandidateMentor] = []
        evidence: list[EvidenceRecord] = []
        unresolved: list[str] = []
        for record in records[: self.max_candidates]:
            if not _department_matches(intent, record):
                continue
            try:
                profile_html = self.profile_fetcher.fetch(record.profile_url)
            except Exception as exc:
                profile_html = ""
                warnings.append(
                    f"USTC profile fetch failed for {record.name}: "
                    f"{type(exc).__name__}: {exc}"
                )
            profile = parse_ustc_faculty_profile(profile_html)
            role_verified = record.mentor_role_verified or profile.mentor_role_verified
            if not role_verified:
                continue
            candidate, records_for_candidate = _official_candidate(
                record,
                profile,
                matched_terms.get(record.faculty_id, []),
                intent,
            )
            candidates.append(candidate)
            evidence.extend(records_for_candidate)
            if not candidate.research_topics:
                unresolved.append(candidate.candidate_id)
        return MentorResearchResult(
            candidates=candidates,
            evidence=evidence,
            warnings=_unique(warnings),
            used_fallback=True,
            source_chain=["ustc_official_faculty", "ustc_official_profile"],
            unresolved_candidate_ids=unresolved,
        )

    def _search_records(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> tuple[
        list[UstcFacultyRecord],
        dict[str, list[str]],
        list[str],
    ]:
        queries = _official_queries(intent, domain_judgements)[: self.max_queries]
        found: dict[str, UstcFacultyRecord] = {}
        matched_terms: dict[str, list[str]] = {}
        warnings: list[str] = []
        college_ids = self._college_ids(intent, domain_judgements)
        divisor = len(queries)
        if self.broad_domain_discovery:
            divisor *= len(college_ids)
        per_query_limit = max(1, math.ceil(self.max_candidates / max(1, divisor)))
        for query_kind, query in queries:
            query_found: set[str] = set()
            for college_id in college_ids:
                college_found: set[str] = set()
                page_index = 1
                while page_index <= self.max_pages_per_query:
                    try:
                        page = self.gateway.search(
                            teacher_name=query if query_kind == "name" else "",
                            research_direction=(
                                query if query_kind == "direction" else ""
                            ),
                            college_id=college_id,
                            page_index=page_index,
                            page_size=self.page_size,
                        )
                    except Exception as exc:
                        warnings.append(
                            f"USTC official faculty search failed for {query!r}: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        break
                    for record in page.records:
                        key = record.faculty_id or record.profile_url
                        already_found = key in found
                        found[key] = record
                        query_found.add(key)
                        if not already_found or not self.broad_domain_discovery:
                            college_found.add(key)
                        matched_terms.setdefault(key, [])
                        if query_kind == "direction":
                            matched_terms[key] = _unique([*matched_terms[key], query])
                        if already_found and self.broad_domain_discovery:
                            continue
                        if len(college_found) >= per_query_limit:
                            break
                    if (
                        page_index >= page.total_pages
                        or len(college_found) >= per_query_limit
                    ):
                        break
                    page_index += 1
                if (
                    not self.broad_domain_discovery
                    and len(query_found) >= per_query_limit
                ):
                    break
            if len(found) >= self.max_candidates:
                break
        if self.broad_domain_discovery and len(found) < self.max_candidates:
            self._extend_with_domain_faculty(found, college_ids, warnings)
        return list(found.values())[: self.max_candidates], matched_terms, warnings

    def _extend_with_domain_faculty(
        self,
        found: dict[str, UstcFacultyRecord],
        college_ids: list[str],
        warnings: list[str],
    ) -> None:
        remaining = self.max_candidates - len(found)
        per_college_limit = max(1, math.ceil(remaining / max(1, len(college_ids))))
        for college_id in college_ids:
            page_index = 1
            college_added = 0
            while (
                page_index <= self.max_pages_per_query
                and college_added < per_college_limit
                and len(found) < self.max_candidates
            ):
                try:
                    page = self.gateway.search(
                        teacher_name="",
                        research_direction="",
                        college_id=college_id,
                        page_index=page_index,
                        page_size=self.page_size,
                    )
                except Exception as exc:
                    warnings.append(
                        "USTC broad faculty discovery failed for college "
                        f"{college_id!r}: {type(exc).__name__}: {exc}"
                    )
                    break
                for record in page.records:
                    key = record.faculty_id or record.profile_url
                    if key in found:
                        continue
                    found[key] = record
                    college_added += 1
                    if (
                        college_added >= per_college_limit
                        or len(found) >= self.max_candidates
                    ):
                        break
                if page_index >= page.total_pages:
                    break
                page_index += 1

    def _college_ids(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> list[str]:
        if self.college_id:
            return [self.college_id]
        constrained = _unique(
            [
                college_id
                for requested in intent.constraints.departments
                for name, college_id in USTC_COLLEGE_IDS.items()
                if _normalize(requested) in _normalize(name)
                or _normalize(name) in _normalize(requested)
            ]
        )
        if constrained:
            return constrained
        domain_scoped = _unique(
            [
                college_id
                for judgement in domain_judgements
                for college_id in USTC_DOMAIN_COLLEGE_IDS.get(judgement.domain, ())
            ]
        )
        return domain_scoped or [USTC_ALL_TEACHING_UNITS_ID]


@dataclass(frozen=True)
class ParsedUstcProfile:
    text: str
    research_topics: list[str]
    mentor_role_verified: bool
    recruitment_status: str | None


def parse_ustc_faculty_profile(profile_html: str) -> ParsedUstcProfile:
    if not profile_html.strip():
        return ParsedUstcProfile(
            text="",
            research_topics=[],
            mentor_role_verified=False,
            recruitment_status=None,
        )
    parser = _VisibleTextParser()
    parser.feed(profile_html)
    text = parser.text()
    return ParsedUstcProfile(
        text=text,
        research_topics=_research_topics(text),
        mentor_role_verified=bool(
            re.search(r"博士生导师|硕士生导师|博士导师|硕士导师|博导|硕导", text)
        ),
        recruitment_status=_recruitment_status(text),
    )


@dataclass(frozen=True)
class PaperSearchHit:
    source: str
    title: str
    abstract: str | None
    authors: list[object]
    year: int | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    openalex_id: str | None
    landing_page_url: str | None
    pdf_url: str | None


@dataclass(frozen=True)
class PaperSearchPage:
    hits: list[PaperSearchHit]
    warnings: list[str]


class MentorPaperSearchGateway(Protocol):
    def search(
        self,
        query: str,
        *,
        source: str,
        mode: str,
        max_results: int,
    ) -> PaperSearchPage: ...


class SqlAlchemyMentorPaperSearchGateway:
    """Reuse the original PaperSearchService and its arXiv/OpenAlex adapters."""

    def __init__(self, session: Session) -> None:
        self.service = PaperSearchService(
            session, paper_source_adapters_from_settings()
        )

    def search(
        self,
        query: str,
        *,
        source: str,
        mode: str,
        max_results: int,
    ) -> PaperSearchPage:
        execution = self.service.search(
            query,
            source=source,
            mode=mode,
            max_results=max_results,
        )
        return PaperSearchPage(
            hits=[
                PaperSearchHit(
                    source=item.source,
                    title=item.title,
                    abstract=item.abstract,
                    authors=list(item.authors_json or []),
                    year=item.year,
                    venue=(item.raw_json or {}).get("venue"),
                    doi=item.doi,
                    arxiv_id=item.arxiv_id,
                    openalex_id=item.openalex_id,
                    landing_page_url=item.landing_page_url,
                    pdf_url=item.pdf_url,
                )
                for item in execution.search_session.candidates
            ],
            warnings=list(execution.warnings),
        )


class DirectMentorPaperSearchGateway:
    """Call the original arXiv/OpenAlex adapters without persisting a search session."""

    def __init__(self) -> None:
        self.adapters = paper_source_adapters_from_settings()

    def search(
        self,
        query: str,
        *,
        source: str,
        mode: str,
        max_results: int,
    ) -> PaperSearchPage:
        adapter = self.adapters.get(source)
        if adapter is None:
            raise ValueError(f"Unsupported paper source: {source}")
        response = adapter.search(query, max_results=max_results, mode=mode)
        return PaperSearchPage(
            hits=[
                PaperSearchHit(
                    source=item.source,
                    title=item.title,
                    abstract=item.abstract,
                    authors=list(item.authors),
                    year=item.year,
                    venue=item.venue,
                    doi=item.doi,
                    arxiv_id=item.arxiv_id,
                    openalex_id=item.openalex_id,
                    landing_page_url=item.landing_page_url,
                    pdf_url=item.pdf_url,
                )
                for item in response.results
            ],
            warnings=list(response.warnings),
        )


class MissingDirectionPaperEnricher:
    """Use broad paper discovery only for official mentors missing directions."""

    def __init__(
        self,
        gateway: MentorPaperSearchGateway,
        *,
        max_candidates: int = 10,
        max_results_per_source: int = 20,
        max_papers_per_candidate: int = 10,
    ) -> None:
        self.gateway = gateway
        self.max_candidates = max_candidates
        self.max_results_per_source = max_results_per_source
        self.max_papers_per_candidate = max_papers_per_candidate

    def enrich(
        self,
        result: MentorResearchResult,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult:
        enriched = result.model_copy(deep=True)
        concepts = _search_concepts(intent, domain_judgements)
        evidence = list(enriched.evidence)
        warnings = list(enriched.warnings)
        unresolved = set(enriched.unresolved_candidate_ids)
        missing = [
            candidate
            for candidate in enriched.candidates
            if candidate.candidate_id in unresolved or not candidate.research_topics
        ][: self.max_candidates]
        for candidate in missing:
            new_records, new_warnings = self._candidate_papers(
                candidate, concepts, intent.methods
            )
            warnings.extend(new_warnings)
            evidence.extend(new_records)
            if candidate.research_topics:
                unresolved.discard(candidate.candidate_id)
            else:
                unresolved.add(candidate.candidate_id)
            candidate.missing_fields = _candidate_missing_fields(candidate)
        enriched.evidence = evidence
        enriched.warnings = _unique(warnings)
        enriched.used_fallback = True
        enriched.source_chain = _unique(
            [*enriched.source_chain, "paper_search_arxiv_openalex"]
        )
        enriched.unresolved_candidate_ids = sorted(unresolved)
        return enriched

    def _candidate_papers(
        self,
        candidate: CandidateMentor,
        concepts: list[str],
        methods: list[str],
    ) -> tuple[list[EvidenceRecord], list[str]]:
        aliases = _unique(
            [
                candidate.mentor_name,
                str(candidate.source_metadata.get("english_name", "")),
            ]
        )
        english_alias = next(
            (alias for alias in aliases if re.search(r"[A-Za-z]", alias)), None
        )
        topic_query = " ".join(concepts[:2])
        search_specs: list[tuple[str, str, str]] = []
        if english_alias:
            search_specs.append(
                (
                    "arxiv",
                    "advanced",
                    f'au:"{english_alias}"'
                    + (f' AND all:"{topic_query}"' if topic_query else ""),
                )
            )
        primary_alias = english_alias or candidate.mentor_name
        search_specs.append(
            (
                "openalex",
                "auto",
                " ".join(value for value in (primary_alias, topic_query) if value),
            )
        )
        records: list[EvidenceRecord] = []
        warnings: list[str] = []
        seen: set[str] = set()
        for source, mode, query in search_specs:
            try:
                page = self.gateway.search(
                    query,
                    source=source,
                    mode=mode,
                    max_results=self.max_results_per_source,
                )
            except Exception as exc:
                warnings.append(
                    f"{source} paper search failed for {candidate.mentor_name}: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            warnings.extend(page.warnings)
            for hit in page.hits:
                if not _paper_author_matches(hit.authors, aliases):
                    continue
                text = " ".join(
                    value
                    for value in (hit.title, hit.abstract or "", hit.venue or "")
                    if value
                )
                matched_concepts = [
                    concept for concept in concepts if _contains(text, concept)
                ]
                if concepts and not matched_concepts:
                    continue
                if _freshness_from_year(hit.year) == EvidenceFreshness.stale:
                    continue
                paper_key = (
                    hit.doi or hit.arxiv_id or hit.openalex_id or _normalize(hit.title)
                )
                if not paper_key or paper_key in seen:
                    continue
                seen.add(paper_key)
                record = _paper_evidence(candidate, hit, matched_concepts, methods)
                records.append(record)
                candidate.evidence_refs = _unique(
                    [*candidate.evidence_refs, record.evidence_id]
                )
                candidate.research_topics = _unique(
                    [*candidate.research_topics, *matched_concepts]
                )
                candidate.methods = _unique(
                    [
                        *candidate.methods,
                        *[method for method in methods if _contains(text, method)],
                    ]
                )
                candidate.publications = _unique([*candidate.publications, hit.title])
                if len(records) >= self.max_papers_per_candidate:
                    return records, warnings
        return records, warnings


class _VisibleTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "br",
        "div",
        "p",
        "li",
        "section",
        "article",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
        "td",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = [
            " ".join(html.unescape(line).split())
            for line in "".join(self.parts).splitlines()
        ]
        return "\n".join(line for line in lines if line)


def mentor_candidate_id(name: str, *, faculty_id: str | None = None) -> str:
    if faculty_id:
        return f"ustc_faculty_{faculty_id}"
    digest = hashlib.sha256(
        f"{USTC_AFFILIATION}:{name.casefold()}".encode()
    ).hexdigest()[:16]
    return f"ustc_mentor_{digest}"


def _faculty_record(payload: dict) -> UstcFacultyRecord | None:
    name = _clean_text(payload.get("showName") or payload.get("name"))
    profile_url = _https_url(_clean_text(payload.get("url")))
    if not name or not profile_url:
        return None
    try:
        _required_ustc_url(profile_url)
    except ValueError:
        return None
    return UstcFacultyRecord(
        faculty_id=_clean_text(payload.get("a")) or _faculty_id_from_url(profile_url),
        name=name,
        english_name=_clean_text(payload.get("ename")),
        college=_clean_text(payload.get("collegeName")).replace("&nbsp;", " ")
        or _clean_text(payload.get("unit")),
        unit=_clean_text(payload.get("unit")),
        academic_title=_clean_text(payload.get("prorank")),
        graduate_tutor_role=_clean_text(payload.get("gtutor")),
        doctoral_tutor_role=_clean_text(payload.get("doctorTutor")),
        profile_url=profile_url,
    )


def _official_candidate(
    record: UstcFacultyRecord,
    profile: ParsedUstcProfile,
    matched_terms: list[str],
    intent: IntentPacket,
) -> tuple[CandidateMentor, list[EvidenceRecord]]:
    candidate_id = mentor_candidate_id(record.name, faculty_id=record.faculty_id)
    role = record.mentor_role or (
        "导师（个人主页明确标注）" if profile.mentor_role_verified else ""
    )
    identity = EvidenceRecord(
        candidate_id=candidate_id,
        source_type="ustc_official_faculty_directory",
        source_uri=USTC_FACULTY_SEARCH_PAGE,
        title=f"中国科学技术大学教师个人主页：{record.name}",
        extracted_fact=(
            f"中科大官方教师系统列出{record.name}，单位为"
            f"{record.college or record.unit or USTC_AFFILIATION}"
            + (f"，导师类型为{role}" if role else "")
            + "。"
        ),
        locator=f"teacherData[a={record.faculty_id}]",
        freshness=EvidenceFreshness.current,
        confidence=0.99,
        metadata={
            "identity_verified": True,
            "mentor_role_verified": bool(role),
            "supports_fields": "affiliation,department,homepage",
            "ustc_faculty_id": record.faculty_id,
            "source_priority": "official",
        },
    )
    records = [identity]
    profile_evidence: EvidenceRecord | None = None
    methods = [method for method in intent.methods if _contains(profile.text, method)]
    if profile.research_topics or methods or profile.recruitment_status:
        supported: list[str] = []
        facts: list[str] = []
        if profile.research_topics:
            supported.append("research_topics")
            facts.append(f"研究方向包括：{'；'.join(profile.research_topics)}")
        if methods:
            supported.append("methods")
            facts.append(f"明确涉及方法：{'；'.join(methods)}")
        if profile.recruitment_status:
            supported.append("recruitment_status")
            facts.append(f"招生信息：{profile.recruitment_status}")
        profile_evidence = EvidenceRecord(
            candidate_id=candidate_id,
            source_type="ustc_official_faculty_profile",
            source_uri=record.profile_url,
            title=f"{record.name}的中科大官方个人主页",
            extracted_fact=f"{record.name}官方个人主页" + "；".join(facts) + "。",
            locator="研究方向/研究领域/个人简介",
            freshness=EvidenceFreshness.current,
            confidence=0.98,
            metadata={
                "identity_verified": True,
                "mentor_role_verified": True,
                "supports_fields": ",".join(supported),
                "ustc_faculty_id": record.faculty_id,
                "source_priority": "official_profile",
            },
        )
        records.append(profile_evidence)
    evidence_refs = [record.evidence_id for record in records]
    candidate = CandidateMentor(
        candidate_id=candidate_id,
        mentor_name=record.name,
        affiliation=USTC_AFFILIATION,
        department=record.college or record.unit or None,
        research_topics=list(profile.research_topics),
        methods=methods,
        homepage=record.profile_url,
        recruitment_status=profile.recruitment_status,
        evidence_refs=evidence_refs,
        source_metadata={
            "ustc_faculty_id": record.faculty_id,
            "english_name": record.english_name,
            "academic_title": record.academic_title,
            "mentor_role": role,
            "official_search_terms": " | ".join(matched_terms),
        },
    )
    candidate.missing_fields = _candidate_missing_fields(candidate)
    return candidate, records


def _paper_evidence(
    candidate: CandidateMentor,
    hit: PaperSearchHit,
    concepts: list[str],
    methods: list[str],
) -> EvidenceRecord:
    source_uri = (
        hit.landing_page_url
        or hit.pdf_url
        or (f"https://doi.org/{hit.doi}" if hit.doi else "")
        or f"{hit.source}:{_normalize(hit.title)}"
    )
    matched_methods = [
        method
        for method in methods
        if _contains(
            " ".join(value for value in (hit.title, hit.abstract or "") if value),
            method,
        )
    ]
    return EvidenceRecord(
        candidate_id=candidate.candidate_id,
        source_type=f"{hit.source}_paper_metadata",
        source_uri=source_uri,
        title=hit.title,
        extracted_fact=(
            f"{candidate.mentor_name}列为论文《{hit.title}》作者；"
            f"论文元数据明确匹配：{'、'.join(_unique([*concepts, *matched_methods]))}。"
        ),
        locator="paper title/abstract/authors",
        freshness=_freshness_from_year(hit.year),
        confidence=0.9,
        metadata={
            "identity_verified": False,
            "supports_fields": "research_topics,methods,publications",
            "year": hit.year or 0,
            "source_priority": "paper_fallback",
        },
    )


def _official_queries(
    intent: IntentPacket,
    domain_judgements: list[DomainJudgement],
) -> list[tuple[str, str]]:
    if intent.constraints.mentor_names:
        return [("name", name) for name in intent.constraints.mentor_names]
    return [
        ("direction", concept)
        for concept in _search_concepts(intent, domain_judgements)
    ]


def _search_concepts(
    intent: IntentPacket,
    domain_judgements: list[DomainJudgement],
) -> list[str]:
    return _unique(
        [
            *intent.research_topics,
            *intent.methods,
            *intent.application_domains,
            *[
                concept
                for judgement in domain_judgements
                for concept in judgement.search_concepts
            ],
        ]
    )


def _scope_allows_ustc(intent: IntentPacket) -> bool:
    if not intent.constraints.colleges:
        return True
    aliases = ("中国科学技术大学", "中科大", "ustc")
    return any(
        alias in college.casefold()
        for college in intent.constraints.colleges
        for alias in aliases
    )


def _department_matches(intent: IntentPacket, record: UstcFacultyRecord) -> bool:
    if not intent.constraints.departments:
        return True
    haystack = _normalize(f"{record.college} {record.unit}")
    return any(
        _normalize(department) in haystack
        for department in intent.constraints.departments
    )


def _research_topics(text: str) -> list[str]:
    values: list[str] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    stop_markers = (
        "社会兼职",
        "团队成员",
        "教育经历",
        "工作经历",
        "科研项目",
        "论文成果",
        "招生信息",
        "学生信息",
        "个人信息",
        "联系方式",
        "其他联系方式",
        "社会服务",
        "获奖信息",
    )
    label_pattern = re.compile(
        r"^(?:主要)?(?:研究方向|研究领域)"
        r"(?:\s*Research (?:Focus|Interests?|Areas?))?"
        r"\s*(?:包括|为)?\s*[:：]?\s*",
        flags=re.IGNORECASE,
    )
    english_label_pattern = re.compile(
        r"^Research (?:Focus|Interests?|Areas?)\s*[:：]?\s*",
        flags=re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        content = label_pattern.sub("", line)
        content = english_label_pattern.sub("", content)
        if content != line and content:
            values.extend(_split_topics(content))
            continue
        if not label_pattern.search(line) and not english_label_pattern.search(line):
            continue
        for following in lines[index + 1 : index + 9]:
            if any(marker in following for marker in stop_markers) or re.search(
                r"(?:欢迎|招收|招生).{0,60}(?:博士|硕士|研究生|本科生|学生)",
                following,
            ):
                break
            values.extend(_split_topics(following))
    patterns = [
        r"主要研究方向包括\s*([^\n。]{2,400})",
        r"主要从事\s*([^\n。]{2,300}?)(?:的研究|研究)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            values.extend(_split_topics(match.group(1)))
    return _unique(values)[:20]


def _split_topics(value: str) -> list[str]:
    cleaned = re.sub(
        r"(?:社会兼职|团队成员|教育经历|工作经历|科研项目|论文成果).*$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    parts = re.split(r"[、，,；;|•·]|\s{2,}", cleaned)
    result: list[str] = []
    for part in parts:
        topic = re.sub(r"^\[?\d+\]?[.)、]?\s*", "", part)
        topic = topic.strip(" []()（）.。:：-*")
        if (
            2 <= len(topic) <= 120
            and "暂无内容" not in topic
            and topic.casefold() not in {"research focus", "research interests"}
        ):
            result.append(topic)
    return result


def _recruitment_status(text: str) -> str | None:
    for line in text.splitlines():
        normalized = " ".join(line.split())
        if re.search(
            r"(?:欢迎|招收|招生).{0,60}(?:博士|硕士|研究生|本科生|学生)",
            normalized,
        ):
            return normalized[:300]
    return None


def _paper_author_matches(authors: list[object], aliases: list[str]) -> bool:
    normalized_aliases = {_person_key(alias) for alias in aliases if alias}
    for author in authors:
        name = _author_name(author)
        key = _person_key(name)
        if key and key in normalized_aliases:
            return True
        if re.search(r"[A-Za-z]", name):
            tokens = sorted(re.findall(r"[a-z]+", name.casefold()))
            if any(
                tokens == sorted(re.findall(r"[a-z]+", alias.casefold()))
                for alias in aliases
                if re.search(r"[A-Za-z]", alias)
            ):
                return True
    return False


def _author_name(author: object) -> str:
    if isinstance(author, str):
        return author
    if isinstance(author, dict):
        for key in ("name", "display_name", "full_name"):
            value = author.get(key)
            if isinstance(value, str):
                return value
    return ""


def _candidate_missing_fields(candidate: CandidateMentor) -> list[str]:
    fields = {
        "affiliation": candidate.affiliation,
        "department": candidate.department,
        "research_topics": candidate.research_topics,
        "methods": candidate.methods,
        "projects": candidate.projects,
        "homepage": candidate.homepage,
        "recruitment_status": candidate.recruitment_status,
    }
    return [name for name, value in fields.items() if not value]


def _validated_json_response(response: httpx.Response) -> dict:
    response.raise_for_status()
    _required_ustc_url(str(response.url))
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("USTC faculty search returned a non-object response")
    return payload


def _required_ustc_url(value: str) -> str:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("USTC source URL must use HTTP or HTTPS")
    if hostname != "ustc.edu.cn" and not hostname.endswith(".ustc.edu.cn"):
        raise ValueError("USTC source URL must stay under an official ustc.edu.cn host")
    return _https_url(value)


def _https_url(value: str) -> str:
    return re.sub(r"^http://", "https://", value.strip(), flags=re.IGNORECASE)


def _faculty_id_from_url(value: str) -> str:
    digest = hashlib.sha256(value.casefold().encode()).hexdigest()[:16]
    return digest


def _safe_int(value: object, default: int) -> int:
    if not isinstance(value, str | int):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _clean_text(value: object) -> str:
    return " ".join(html.unescape(str(value or "")).replace("\xa0", " ").split())


def _person_key(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", value.casefold())


def _contains(text: str, term: str) -> bool:
    normalized_term = _normalize(term)
    return bool(normalized_term and normalized_term in _normalize(text))


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value).split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _freshness_from_year(year: int | None) -> EvidenceFreshness:
    if year is None:
        return EvidenceFreshness.unknown
    current_year = datetime.now(UTC).year
    if year >= current_year - 2:
        return EvidenceFreshness.current
    if year >= current_year - 5:
        return EvidenceFreshness.recent
    return EvidenceFreshness.stale
