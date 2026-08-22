from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

import tiktoken
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.db.models import ParsedDocument, ProcessedDocument
from backend.db.repositories import ParsingRepository
from backend.db.types import PaperStatus, ParseQualityStatus, ProcessedDocumentStatus, SectionRole
from backend.integrations.parsers.cleaning import clean_markdown_text
from backend.services.embeddings import EmbeddingService

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_PAGE_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->", re.IGNORECASE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_ARXIV_RE = re.compile(r"\b(?:arXiv:)?(\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s)\]]+")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_SPACE_RE = re.compile(r"\s+")
_REFERENCE_START_RE = re.compile(r"^(?P<label>(?:\[\d+\]|\d+\.|\d+\)|-))\s+(?P<body>.+)")
_TITLE_QUOTE_RE = re.compile(r"[\"“](?P<title>[^\"”]{8,})[\"”]")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?;:])\s+")
_WORD_BOUNDARY_RE = re.compile(r"\s+")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_LIST_LINE_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
_CAPTION_RE = re.compile(r"^(?P<kind>Figure|Fig\.|Table|Algorithm|Listing)\s+(?P<label>[A-Za-z0-9.\-]+)\s*[:.]\s*(?P<body>.+)", re.IGNORECASE | re.DOTALL)
_MENTION_RE = re.compile(r"\b(?P<kind>Figure|Fig\.|Table|Algorithm|Listing)\s+(?P<label>[A-Za-z0-9.\-]+)", re.IGNORECASE)
_DISPLAY_MATH_STARTS = ("$$", r"\[", r"\begin{equation", r"\begin{align", r"\begin{gather", r"\begin{multline")
_DISPLAY_MATH_ENDS = ("$$", r"\]", r"\end{equation}", r"\end{equation*}", r"\end{align}", r"\end{align*}", r"\end{gather}", r"\end{gather*}", r"\end{multline}", r"\end{multline*}")
_ATOMIC_BLOCK_TYPES = {"markdown_table", "display_math"}
_PROCESSING_PROFILE = "normalized_heading_structured_chunk_v4"


@dataclass(frozen=True)
class SectionPayload:
    heading_path: list[str]
    role: str
    raw_text: str
    cleaned_text: str
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedDocumentPayload:
    markdown: str
    text: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class SectionClassification:
    role: str
    role_detail: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class ContentBlock:
    text: str
    block_type: str
    ordinal: int
    heading_path: list[str]
    role: str
    relation_id: str | None = None
    relation_type: str | None = None
    object_type: str | None = None
    label: str | None = None
    caption: str | None = None
    mentions: list[dict[str, object]] = field(default_factory=list)
    atomic: bool = False


@dataclass(frozen=True)
class ChunkPayload:
    text: str
    body_text: str
    heading_context: str
    block_types: list[str]
    source_block_ordinals: list[int]
    token_count: int
    metadata: dict[str, Any]


class DocumentProcessingService:
    def __init__(
        self,
        session: Session,
        *,
        chunk_size_chars: int = 1800,
        chunk_overlap_chars: int = 200,
        chunk_size_tokens: int | None = None,
        chunk_overlap_tokens: int | None = None,
        tokenizer_encoding: str = "cl100k_base",
    ) -> None:
        self.session = session
        self.chunk_size_chars = chunk_size_chars
        self.chunk_overlap_chars = chunk_overlap_chars
        self.tokenizer_encoding = tokenizer_encoding
        self.encoding = tiktoken.get_encoding(tokenizer_encoding)
        self.chunk_size_tokens = chunk_size_tokens or max(1, chunk_size_chars // 4)
        self.chunk_overlap_tokens = chunk_overlap_tokens if chunk_overlap_tokens is not None else max(0, chunk_overlap_chars // 4)

    def process_latest_parsed_document(self, paper_id: int, *, regenerate: bool = True) -> ProcessedDocument:
        parsed = self.session.scalar(
            select(ParsedDocument)
            .where(ParsedDocument.paper_id == paper_id)
            .order_by(ParsedDocument.created_at.desc(), ParsedDocument.id.desc())
        )
        if parsed is None:
            raise ValueError(f"Paper {paper_id} has no parsed document.")
        return self.process_parsed_document(parsed.id, regenerate=regenerate)

    def process_parsed_document(self, parsed_document_id: int, *, regenerate: bool = True) -> ProcessedDocument:
        parsed = self.session.get(ParsedDocument, parsed_document_id)
        if parsed is None:
            raise ValueError(f"Parsed document {parsed_document_id} does not exist.")
        if regenerate:
            self.session.execute(delete(ProcessedDocument).where(ProcessedDocument.parsed_document_id == parsed.id))
            self.session.flush()
        else:
            existing = self.session.scalar(select(ProcessedDocument).where(ProcessedDocument.parsed_document_id == parsed.id))
            if existing is not None:
                return existing
        normalized = normalize_parsed_document(parsed)
        sections = split_markdown_sections(normalized.markdown)
        analysis_text = _clean_section_text("\n\n".join(section.cleaned_text for section in sections if section.role != SectionRole.reference.value))
        chunking_metadata = _chunking_metadata(self.chunk_size_tokens, self.chunk_overlap_tokens, self.tokenizer_encoding)
        version = _next_version(self.session, parsed.paper_id)
        repo = ParsingRepository(self.session)
        processed = repo.create_processed_document(
            parsed.paper_id,
            parsed.id,
            parsed.parse_job_id,
            version=version,
            status=ProcessedDocumentStatus.processing.value,
            content_markdown=normalized.markdown,
            content_text=analysis_text,
            quality_status=ParseQualityStatus.usable.value,
            quality_summary="Normalized parsed document into frontend markdown, token-aware heading-context chunks, structured sections, relations, references, and processing diagnostics.",
            processing_profile=_PROCESSING_PROFILE,
            metadata_json={**normalized.metadata, "processing_profile": _PROCESSING_PROFILE, "chunking": chunking_metadata},
        )
        section_ids: list[int] = []
        stored_chunks: list[ChunkPayload] = []
        skipped_chunk_roles: set[str] = set()
        next_chunk_index = 1
        for index, section in enumerate(sections, start=1):
            blocks = _split_content_blocks(section)
            section_metadata = {
                **section.metadata,
                "block_summary": _block_summary(blocks),
            }
            row = repo.add_section(
                processed.id,
                index,
                role=section.role,
                heading_path_json=section.heading_path,
                page_start=section.page_start,
                page_end=section.page_end,
                raw_text=section.raw_text,
                cleaned_text=section.cleaned_text,
                token_estimate=_estimate_tokens(section.cleaned_text, self.encoding),
                metadata_json=section_metadata,
            )
            section_ids.append(row.id)
            if section.role == SectionRole.reference.value:
                skipped_chunk_roles.add(section.role)
                continue
            for chunk_index, chunk in enumerate(_chunk_section(section, blocks, self.chunk_size_tokens, self.chunk_overlap_tokens, self.encoding), start=1):
                repo.add_chunk(
                    processed.id,
                    f"s{index}-c{chunk_index}",
                    next_chunk_index,
                    chunk.text,
                    role=section.role,
                    heading_path_json=section.heading_path,
                    source_section_ids_json=[row.id],
                    page_start=section.page_start,
                    page_end=section.page_end,
                    token_estimate=chunk.token_count,
                    metadata_json=chunk.metadata,
                )
                stored_chunks.append(chunk)
                next_chunk_index += 1
        references, reference_debug = extract_references_from_parsed(parsed, sections)
        for reference_index, reference in enumerate(references, start=1):
            repo.add_reference(processed.id, reference_index, reference["raw_text"], **{key: value for key, value in reference.items() if key != "raw_text"})
        self.session.flush()
        metadata = {
            **processed.metadata_json,
            "section_count": len(sections),
            "section_ids": section_ids,
            "skipped_chunk_roles": sorted(skipped_chunk_roles),
        }
        metadata["processing_debug_report"] = _build_processing_quality_report(
            sections=sections,
            chunks=stored_chunks,
            references=references,
            reference_debug=reference_debug,
            tokenizer_encoding=self.tokenizer_encoding,
            chunk_size_tokens=self.chunk_size_tokens,
            skipped_chunk_roles=skipped_chunk_roles,
        )
        try:
            metadata["embedded_chunk_count"] = EmbeddingService(self.session).embed_missing_chunks(parsed.paper_id)
        except Exception as exc:
            metadata["embedding_error"] = str(exc)
        processed.status = ProcessedDocumentStatus.ready.value
        processed.metadata_json = metadata
        processed.paper.status = PaperStatus.processed.value
        self.session.flush()
        return processed


def normalize_parsed_document(parsed: ParsedDocument) -> NormalizedDocumentPayload:
    markdown = clean_markdown_text(parsed.markdown_content or parsed.plain_text or "")
    return NormalizedDocumentPayload(
        markdown=markdown,
        text=_clean_text(markdown),
        metadata={
            "source_parser": parsed.parser_kind,
            "normalization_profile": "markdown_structure_v1",
            "analysis_excludes_roles": [SectionRole.reference.value],
        },
    )


def split_markdown_sections(markdown: str) -> list[SectionPayload]:
    lines = markdown.splitlines()
    sections: list[SectionPayload] = []
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[str] = []
    current_page: int | None = None
    section_start_page: int | None = None

    def current_path() -> list[str]:
        path = [heading for _, heading in heading_stack if heading]
        return path or ["Document"]

    def flush() -> None:
        nonlocal current_lines, section_start_page
        raw = "\n".join(current_lines).strip()
        if raw:
            cleaned = _clean_section_text(raw)
            path = current_path()
            classification = _classify_section(path, cleaned)
            sections.append(
                SectionPayload(
                    heading_path=path,
                    role=classification.role,
                    raw_text=raw,
                    cleaned_text=cleaned,
                    page_start=section_start_page,
                    page_end=current_page,
                    metadata=_section_metadata(path, classification),
                )
            )
        current_lines = []
        section_start_page = current_page

    for line in lines:
        page_match = _PAGE_RE.search(line)
        if page_match:
            current_page = int(page_match.group(1))
            if section_start_page is None:
                section_start_page = current_page
            continue
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            heading = heading_match.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            if not heading_stack and level > 1:
                heading_stack.append((0, "Document"))
            heading_stack.append((level, heading))
            if level == 1:
                path = current_path()
                sections.append(
                    SectionPayload(
                        heading_path=path,
                        role=SectionRole.title.value,
                        raw_text=heading,
                        cleaned_text=heading,
                        page_start=current_page,
                        page_end=current_page,
                        metadata=_section_metadata(path, SectionClassification(SectionRole.title.value, "title", 1.0, "level-1 heading")),
                    )
                )
            continue
        current_lines.append(line)
    flush()
    if not sections and markdown.strip():
        cleaned = _clean_section_text(markdown)
        classification = _classify_section(["Document"], cleaned)
        sections.append(SectionPayload(["Document"], classification.role, markdown.strip(), cleaned, metadata=_section_metadata(["Document"], classification)))
    return sections


def extract_references(sections: list[SectionPayload]) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    for section in sections:
        if section.role != SectionRole.reference.value:
            continue
        for raw_label, entry in _split_reference_entries(section.raw_text):
            parsed = _parse_reference_text(entry, raw_label, reference_source="markdown_reference_section")
            if parsed:
                references.append(parsed)
    return references


def extract_references_from_parsed(parsed: ParsedDocument, sections: list[SectionPayload]) -> tuple[list[dict[str, object]], dict[str, object]]:
    parser_refs = _references_from_parser_json(parsed.json_content or {})
    if parser_refs:
        references = [reference for item in parser_refs if (reference := _normalize_parser_reference(item))]
        if references:
            return references, {
                "source": "parser_structure",
                "parser_reference_count": len(parser_refs),
                "extracted_reference_count": len(references),
                "fallback_used": False,
            }
    references = extract_references(sections)
    return references, {
        "source": "markdown_reference_section",
        "parser_reference_count": len(parser_refs),
        "extracted_reference_count": len(references),
        "fallback_used": bool(parser_refs),
    }


def _references_from_parser_json(json_content: dict[str, object]) -> list[object]:
    value = json_content.get("references")
    return value if isinstance(value, list) else []


def _normalize_parser_reference(value: object) -> dict[str, object] | None:
    if isinstance(value, str):
        return _parse_reference_text(value, None, reference_source="parser_structure")
    if not isinstance(value, dict):
        return None
    raw = str(value.get("raw_text") or value.get("text") or value.get("normalized_text") or value.get("title") or "").strip()
    parsed = _parse_reference_text(raw, str(value.get("label")) if value.get("label") is not None else None, reference_source="parser_structure") if raw else None
    if parsed is None:
        return None
    for key in ("title", "authors_json", "year", "doi", "arxiv_id", "url", "confidence"):
        if value.get(key) not in (None, ""):
            parsed[key] = value[key]
    return parsed


def _parse_reference_text(entry: str, raw_label: str | None, *, reference_source: str) -> dict[str, object] | None:
    normalized = _clean_text(entry)
    if not normalized:
        return None
    doi = _first_match(_DOI_RE, normalized)
    arxiv_id = _first_match(_ARXIV_RE, normalized)
    url = _first_match(_URL_RE, normalized)
    year = _extract_year(normalized)
    authors = _extract_reference_authors(normalized)
    title = _extract_reference_title(normalized, authors)
    source, other = _extract_reference_source(normalized, title, authors, year, doi, arxiv_id, url)
    return {
        "raw_text": entry,
        "label": raw_label,
        "normalized_text": normalized,
        "title": title,
        "authors_json": authors,
        "year": year,
        "doi": doi.lower() if doi else None,
        "arxiv_id": arxiv_id,
        "url": url,
        "confidence": _reference_confidence(title, authors, doi, arxiv_id, url),
        "metadata_json": {"parser": "deterministic_reference_v2", "reference_source": reference_source, "source": source, "other": other},
    }


def _split_reference_entries(text: str) -> list[tuple[str | None, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    entries: list[tuple[str | None, list[str]]] = []
    for line in lines:
        line = re.sub(r"^[-*]\s+", "- ", line)
        match = _REFERENCE_START_RE.match(line)
        if match:
            entries.append((match.group("label").strip("[]().-"), [match.group("body").strip()]))
        elif entries:
            entries[-1][1].append(line)
        else:
            entries.append((None, [line]))
    if len(entries) <= 1 and text.strip():
        parts = re.split(r"\s+(?=(?:\[\d+\]|\d+\.|\d+\))\s+)", _clean_text(text))
        parsed = []
        for part in parts:
            match = _REFERENCE_START_RE.match(part.strip())
            parsed.append((match.group("label").strip("[]().-") if match else None, match.group("body").strip() if match else part.strip()))
        return [(label, body) for label, body in parsed if body]
    return [(label, _strip_reference_label(" ".join(parts))) for label, parts in entries if " ".join(parts).strip()]


def _strip_reference_label(text: str) -> str:
    return re.sub(r"^(?:\[\d+\]|\d+\.|\d+\)|[-*])\s*", "", text).strip()


def _extract_reference_authors(text: str) -> list[str]:
    match = re.match(
        r"^(?P<authors>(?:(?:[A-Z]\.\s*)*[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+)?)(?:\s*(?:,|and|&)\s*(?:[A-Z]\.\s*)*[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+)?)*)\.\s+",
        text,
    )
    if match is None:
        return []
    author_segment = match.group("authors").strip()
    if not author_segment or len(author_segment) > 300:
        return []
    authors = [part.strip() for part in re.split(r"\s+(?:and|&)\s+|,\s*", author_segment) if part.strip()]
    return authors[:20]


def _extract_reference_title(text: str, authors: list[str]) -> str | None:
    quote_match = _TITLE_QUOTE_RE.search(text)
    if quote_match:
        return quote_match.group("title").strip().rstrip(".")
    remainder = text
    if authors and "." in remainder:
        remainder = remainder.split(".", 1)[1].strip()
    sentences = [part.strip() for part in re.split(r"\.\s+", remainder) if part.strip()]
    for sentence in sentences:
        cleaned = re.sub(r"\b(?:In )?(?:Proceedings|Proc\.|Journal|Conference|arXiv|doi:)\b.*", "", sentence, flags=re.IGNORECASE).strip(" .")
        if 8 <= len(cleaned) <= 300 and not _DOI_RE.search(cleaned) and not _URL_RE.search(cleaned):
            return cleaned
    return None


def _extract_reference_source(
    text: str,
    title: str | None,
    authors: list[str],
    year: int | None,
    doi: str | None,
    arxiv_id: str | None,
    url: str | None,
) -> tuple[str | None, str | None]:
    remaining = text
    for value in [title, str(year) if year else None, doi, arxiv_id, url, *authors]:
        if value:
            remaining = remaining.replace(value, " ")
    remaining = re.sub(r"\b(?:DOI|doi|arXiv)\s*:?\s*", " ", remaining)
    remaining = _clean_text(remaining).strip(" .,-")
    source = None
    source_match = re.search(r"\b(?:In\s+)?((?:Proceedings|Proc\.|Journal|Conference|Transactions|arXiv)[^.]{3,160})", text, flags=re.IGNORECASE)
    if source_match:
        source = source_match.group(1).strip(" .,")
    return source, remaining or None


def _extract_year(text: str) -> int | None:
    match = _YEAR_RE.search(text)
    return int(match.group(1)) if match else None


def _reference_confidence(title: str | None, authors: list[str], doi: str | None, arxiv_id: str | None, url: str | None) -> float:
    score = 0.35
    if title:
        score += 0.2
    if authors:
        score += 0.15
    if doi or arxiv_id:
        score += 0.2
    elif url:
        score += 0.1
    return min(score, 0.95)


def _chunk_section(section: SectionPayload, blocks: list[ContentBlock], size_tokens: int, overlap_tokens: int, encoding: tiktoken.Encoding) -> list[ChunkPayload]:
    if not blocks:
        return []
    context = _heading_context_text(section)
    context_tokens = _estimate_tokens(context, encoding)
    body_budget = max(16, size_tokens - context_tokens - 2)
    chunks: list[ChunkPayload] = []
    current: list[ContentBlock] = []
    for block in blocks:
        parts = _split_oversized_content_block(block, body_budget, encoding) if not block.atomic and _estimate_tokens(block.text, encoding) > body_budget else [block]
        for part in parts:
            candidate = [*current, part]
            if current and _blocks_tokens(candidate, encoding) > body_budget:
                chunks.append(_build_chunk_payload(section, current, context, size_tokens, encoding))
                overlap_blocks = _tail_overlap_blocks(current, overlap_tokens, encoding)
                current = [*overlap_blocks, part]
            else:
                current.append(part)
    if current:
        chunks.append(_build_chunk_payload(section, current, context, size_tokens, encoding))
    return chunks


def _split_content_blocks(section: SectionPayload) -> list[ContentBlock]:
    raw_blocks = _split_blocks(section.cleaned_text)
    blocks: list[ContentBlock] = []
    for ordinal, raw in enumerate(raw_blocks, start=1):
        block_type = _detect_block_type(raw)
        relation = _caption_relation(raw) if block_type == "caption" else None
        mentions = _mentions(raw) if block_type != "caption" else []
        blocks.append(
            ContentBlock(
                text=raw,
                block_type=block_type,
                ordinal=ordinal,
                heading_path=section.heading_path,
                role=section.role,
                relation_id=relation.get("relation_id") if relation else None,
                relation_type="caption_for" if relation else None,
                object_type=relation.get("object_type") if relation else None,
                label=relation.get("label") if relation else None,
                caption=relation.get("caption") if relation else None,
                mentions=mentions,
                atomic=block_type in _ATOMIC_BLOCK_TYPES,
            )
        )
    return _attach_nearby_caption_relations(blocks)


def _detect_block_type(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if _is_markdown_table(lines):
        return "markdown_table"
    if _is_display_math_block(text):
        return "display_math"
    if lines and all(_LIST_LINE_RE.match(line) for line in lines):
        return "list"
    if _CAPTION_RE.match(text.strip()):
        return "caption"
    return "paragraph"


def _is_markdown_table(lines: list[str]) -> bool:
    return len(lines) >= 2 and any(_TABLE_SEPARATOR_RE.match(line) for line in lines) and all("|" in line for line in lines[:2])


def _is_display_math_block(text: str) -> bool:
    stripped = text.strip()
    return (stripped.startswith(_DISPLAY_MATH_STARTS) and stripped.endswith(_DISPLAY_MATH_ENDS)) or (stripped.startswith("$$") and "\n" in stripped and stripped.endswith("$$"))


def _caption_relation(text: str) -> dict[str, object] | None:
    match = _CAPTION_RE.match(text.strip())
    if match is None:
        return None
    object_type = _normalize_object_type(match.group("kind"))
    label = match.group("label").strip(" .")
    return {"relation_id": f"{object_type}:{label.lower()}", "object_type": object_type, "label": label, "caption": _clean_text(match.group("body"))}


def _mentions(text: str) -> list[dict[str, object]]:
    mentions: list[dict[str, object]] = []
    seen: set[str] = set()
    for match in _MENTION_RE.finditer(text):
        object_type = _normalize_object_type(match.group("kind"))
        label = match.group("label").strip(" .")
        relation_id = f"{object_type}:{label.lower()}"
        if relation_id in seen:
            continue
        seen.add(relation_id)
        mentions.append({"relation_id": relation_id, "object_type": object_type, "label": label, "relation_types": ["mentions"]})
    return mentions


def _normalize_object_type(kind: str) -> str:
    normalized = kind.rstrip(".").lower()
    if normalized == "fig":
        return "figure"
    return normalized


def _attach_nearby_caption_relations(blocks: list[ContentBlock]) -> list[ContentBlock]:
    captions = {block.relation_id: block for block in blocks if block.relation_id and block.relation_type == "caption_for"}
    attached: list[ContentBlock] = []
    for index, block in enumerate(blocks):
        if block.block_type != "markdown_table":
            attached.append(block)
            continue
        nearby = [probe for probe in blocks[max(0, index - 1): min(len(blocks), index + 2)] if probe.relation_id and probe.object_type == "table"]
        caption = nearby[0] if nearby else None
        if caption is None:
            attached.append(block)
            continue
        attached.append(
            ContentBlock(
                text=block.text,
                block_type=block.block_type,
                ordinal=block.ordinal,
                heading_path=block.heading_path,
                role=block.role,
                relation_id=caption.relation_id,
                relation_type="table_for",
                object_type="table",
                label=caption.label,
                caption=caption.caption,
                mentions=block.mentions,
                atomic=block.atomic,
            )
        )
    return attached


def _split_oversized_content_block(block: ContentBlock, budget_tokens: int, encoding: tiktoken.Encoding) -> list[ContentBlock]:
    text_parts = _split_text_by_tokens(block.text, budget_tokens, encoding)
    return [
        ContentBlock(
            text=part,
            block_type=block.block_type,
            ordinal=block.ordinal,
            heading_path=block.heading_path,
            role=block.role,
            relation_id=block.relation_id,
            relation_type=block.relation_type,
            object_type=block.object_type,
            label=block.label,
            caption=block.caption,
            mentions=block.mentions,
            atomic=block.atomic,
        )
        for part in text_parts
    ]


def _split_text_by_tokens(text: str, budget_tokens: int, encoding: tiktoken.Encoding) -> list[str]:
    if _estimate_tokens(text, encoding) <= budget_tokens:
        return [text]
    units = _split_sentences(text)
    parts = _pack_text_units(units, budget_tokens, encoding)
    if parts:
        return parts
    words = [word for word in _WORD_BOUNDARY_RE.split(text) if word]
    parts = _pack_text_units(words, budget_tokens, encoding, separator=" ")
    if parts:
        return parts
    tokens = encoding.encode(text)
    return [encoding.decode(tokens[index:index + budget_tokens]).strip() for index in range(0, len(tokens), budget_tokens) if encoding.decode(tokens[index:index + budget_tokens]).strip()]


def _split_sentences(text: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(text):
        pieces.append(text[start:match.end()].strip())
        start = match.end()
    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    return pieces or [text]


def _pack_text_units(units: list[str], budget_tokens: int, encoding: tiktoken.Encoding, *, separator: str = " ") -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for unit in units:
        if _estimate_tokens(unit, encoding) > budget_tokens:
            return []
        candidate = separator.join([*current, unit]).strip()
        if current and _estimate_tokens(candidate, encoding) > budget_tokens:
            parts.append(separator.join(current).strip())
            current = [unit]
        else:
            current.append(unit)
    if current:
        parts.append(separator.join(current).strip())
    return parts


def _tail_overlap_blocks(blocks: list[ContentBlock], overlap_tokens: int, encoding: tiktoken.Encoding) -> list[ContentBlock]:
    if overlap_tokens <= 0:
        return []
    selected: list[ContentBlock] = []
    total = 0
    for block in reversed(blocks):
        block_tokens = _estimate_tokens(block.text, encoding)
        if block.atomic and block_tokens > overlap_tokens:
            continue
        if total + block_tokens <= overlap_tokens:
            selected.append(_overlap_block(block, block.text))
            total += block_tokens
            continue
        if block.block_type in {"paragraph", "list"}:
            tail = _tail_text_by_tokens(block.text, overlap_tokens - total, encoding)
            if tail:
                selected.append(_overlap_block(block, tail))
        break
    return list(reversed(selected))


def _tail_text_by_tokens(text: str, budget_tokens: int, encoding: tiktoken.Encoding) -> str:
    if budget_tokens <= 0:
        return ""
    sentences = _split_sentences(text)
    selected: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        tokens = _estimate_tokens(sentence, encoding)
        if total + tokens <= budget_tokens:
            selected.append(sentence)
            total += tokens
        elif not selected:
            words = [word for word in _WORD_BOUNDARY_RE.split(sentence) if word]
            tail_words: list[str] = []
            for word in reversed(words):
                candidate = " ".join(reversed([*tail_words, word]))
                if _estimate_tokens(candidate, encoding) > budget_tokens:
                    break
                tail_words.append(word)
            return " ".join(reversed(tail_words)).strip()
        else:
            break
    return " ".join(reversed(selected)).strip()


def _overlap_block(block: ContentBlock, text: str) -> ContentBlock:
    return ContentBlock(
        text=text,
        block_type="overlap",
        ordinal=block.ordinal,
        heading_path=block.heading_path,
        role=block.role,
        relation_id=block.relation_id,
        relation_type=block.relation_type,
        object_type=block.object_type,
        label=block.label,
        caption=block.caption,
        mentions=block.mentions,
        atomic=False,
    )


def _build_chunk_payload(section: SectionPayload, blocks: list[ContentBlock], context: str, size_tokens: int, encoding: tiktoken.Encoding) -> ChunkPayload:
    body = _join_chunk_parts([block.text for block in blocks])
    text = _join_chunk_parts([context, body])
    block_types = _unique([block.block_type for block in blocks])
    relations = _merge_related_objects(blocks)
    token_count = _estimate_tokens(text, encoding)
    classification = section.metadata.get("classification", {}) if section.metadata else {}
    metadata = {
        "heading_context": {"text": context, "included_in_content": True, "path": section.heading_path},
        "section_classification": classification,
        "block_types": block_types,
        "source_block_ordinals": _unique([block.ordinal for block in blocks]),
        "overlap_from_previous": any(block.block_type == "overlap" for block in blocks),
        "overlap_strategy": "tail_blocks_or_sentences",
        "atomic_blocks": {
            "contains_atomic": any(block.block_type in _ATOMIC_BLOCK_TYPES for block in blocks),
            "oversized_atomic": any(block.atomic and _estimate_tokens(block.text, encoding) > size_tokens for block in blocks),
            "atomic_split": False,
        },
        "related_objects": relations,
    }
    return ChunkPayload(text, body, context, block_types, _unique([block.ordinal for block in blocks]), token_count, metadata)


def _merge_related_objects(blocks: list[ContentBlock]) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for block in blocks:
        if block.relation_id:
            entry = merged.setdefault(
                block.relation_id,
                {
                    "relation_id": block.relation_id,
                    "object_type": block.object_type,
                    "label": block.label,
                    "relation_types": [],
                },
            )
            if block.relation_type and block.relation_type not in entry["relation_types"]:
                entry["relation_types"].append(block.relation_type)
            if block.caption:
                entry["caption"] = block.caption
        for mention in block.mentions:
            relation_id = str(mention["relation_id"])
            entry = merged.setdefault(relation_id, {"relation_id": relation_id, "object_type": mention["object_type"], "label": mention["label"], "relation_types": []})
            for relation_type in mention.get("relation_types", []):
                if relation_type not in entry["relation_types"]:
                    entry["relation_types"].append(relation_type)
    return list(merged.values())


def _blocks_tokens(blocks: list[ContentBlock], encoding: tiktoken.Encoding) -> int:
    return _estimate_tokens(_join_chunk_parts([block.text for block in blocks]), encoding)


def _heading_context_text(section: SectionPayload) -> str:
    path = " > ".join(part.strip() for part in section.heading_path if part.strip()) or "Document"
    classification = section.metadata.get("classification", {}) if section.metadata else {}
    detail = classification.get("role_detail", section.role)
    return f"Context: {path}\nRole: {section.role}\nDetail: {detail}"


def _chunk_text(text: str, size: int, overlap: int) -> list[str]:
    encoding = tiktoken.get_encoding("cl100k_base")
    section = SectionPayload(["Document"], SectionRole.body.value, text, _clean_section_text(text), metadata=_section_metadata(["Document"], _classify_section(["Document"], text)))
    blocks = _split_content_blocks(section)
    return [chunk.text for chunk in _chunk_section(section, blocks, max(1, size // 4), max(0, overlap // 4), encoding)]


def _split_blocks(text: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n+", text) if block.strip()]


def _join_chunk_parts(parts: list[str]) -> str:
    return "\n\n".join(part.strip() for part in parts if part.strip()).strip()


def _block_summary(blocks: list[ContentBlock]) -> dict[str, object]:
    return {"block_count": len(blocks), "block_types": dict(Counter(block.block_type for block in blocks))}


def _classify_section(heading_path: list[str], text: str) -> SectionClassification:
    heading = " ".join(heading_path).strip().lower()
    last = heading_path[-1].strip().lower() if heading_path else ""
    rules = [
        (SectionRole.abstract.value, "abstract", 0.98, "heading matched abstract", ("abstract",)),
        (SectionRole.reference.value, "references", 0.98, "heading matched references", ("references", "bibliography", "works cited", "reference")),
        (SectionRole.appendix.value, "supplementary", 0.9, "heading matched appendix/supplement", ("appendix", "supplementary", "supplement")),
        (SectionRole.front_matter.value, "front_matter", 0.85, "heading matched front matter", ("keywords", "author", "affiliation", "funding")),
        (SectionRole.body.value, "introduction", 0.9, "heading matched introduction", ("introduction", "intro")),
        (SectionRole.body.value, "related_work", 0.88, "heading matched related/background work", ("related work", "prior work")),
        (SectionRole.body.value, "background", 0.82, "heading matched background", ("background", "preliminaries", "notation")),
        (SectionRole.body.value, "method", 0.88, "heading matched method", ("method", "methodology", "approach", "framework", "model", "architecture", "algorithm")),
        (SectionRole.body.value, "experiment", 0.88, "heading matched experiment/evaluation", ("experiment", "evaluation", "benchmark", "empirical")),
        (SectionRole.body.value, "result", 0.84, "heading matched result", ("result", "findings")),
        (SectionRole.body.value, "discussion", 0.84, "heading matched discussion", ("discussion", "analysis")),
        (SectionRole.body.value, "conclusion", 0.9, "heading matched conclusion", ("conclusion", "future work")),
        (SectionRole.body.value, "limitations", 0.9, "heading matched limitations", ("limitation", "limitations")),
        (SectionRole.body.value, "ethics", 0.88, "heading matched ethics/impact", ("ethics", "broader impact", "societal impact")),
        (SectionRole.front_matter.value, "acknowledgements", 0.9, "heading matched acknowledgements", ("acknowledgement", "acknowledgment")),
    ]
    for role, detail, confidence, reason, keywords in rules:
        if any(keyword == last or keyword in heading for keyword in keywords):
            return SectionClassification(role, detail, confidence, reason)
    if _CAPTION_RE.match(text.strip()):
        kind = _normalize_object_type(_CAPTION_RE.match(text.strip()).group("kind"))
        return SectionClassification(SectionRole.caption.value, f"{kind}_caption", 0.82, "content matched caption")
    if _is_markdown_table([line for line in text.splitlines() if line.strip()]):
        return SectionClassification(SectionRole.table.value, "table", 0.82, "content matched markdown table")
    if last in {"title", "document"} and len(text) < 500:
        return SectionClassification(SectionRole.title.value, "title", 0.75, "short document/title text")
    return SectionClassification(SectionRole.body.value, "body", 0.5, "default body")


def _classify_role(heading: str, text: str) -> str:
    return _classify_section([heading], text).role


def _section_metadata(path: list[str], classification: SectionClassification) -> dict[str, Any]:
    return {
        "classification": {
            "role": classification.role,
            "role_detail": classification.role_detail,
            "confidence": classification.confidence,
            "reason": classification.reason,
        },
        "heading": {"path": path, "depth": max(0, len(path) - 1)},
    }


def _build_processing_quality_report(
    *,
    sections: list[SectionPayload],
    chunks: list[ChunkPayload],
    references: list[dict[str, object]],
    reference_debug: dict[str, object],
    tokenizer_encoding: str,
    chunk_size_tokens: int,
    skipped_chunk_roles: set[str],
) -> dict[str, object]:
    token_counts = [chunk.token_count for chunk in chunks]
    block_type_counts = Counter(block_type for chunk in chunks for block_type in chunk.block_types)
    relation_count = sum(len(chunk.metadata.get("related_objects", [])) for chunk in chunks)
    return {
        "profile": _PROCESSING_PROFILE,
        "tokenizer_encoding": tokenizer_encoding,
        "section_count": len(sections),
        "chunk_count": len(chunks),
        "reference_count": len(references),
        "role_counts": dict(Counter(section.role for section in sections)),
        "role_detail_counts": dict(Counter(str(section.metadata.get("classification", {}).get("role_detail", "unknown")) for section in sections)),
        "chunk_token_stats": {
            "min": min(token_counts) if token_counts else 0,
            "max": max(token_counts) if token_counts else 0,
            "mean": mean(token_counts) if token_counts else 0,
            "target": chunk_size_tokens,
            "over_target_count": sum(1 for count in token_counts if count > chunk_size_tokens),
        },
        "block_type_counts": dict(block_type_counts),
        "atomic_blocks": {
            "markdown_table": block_type_counts.get("markdown_table", 0),
            "display_math": block_type_counts.get("display_math", 0),
            "oversized_atomic_count": sum(1 for chunk in chunks if chunk.metadata.get("atomic_blocks", {}).get("oversized_atomic")),
            "atomic_split_count": sum(1 for chunk in chunks if chunk.metadata.get("atomic_blocks", {}).get("atomic_split")),
        },
        "heading_context": {
            "included_in_chunks": True,
            "missing_heading_path_count": sum(1 for section in sections if not section.heading_path),
        },
        "relations": {
            "related_object_count": relation_count,
            "caption_count": block_type_counts.get("caption", 0),
        },
        "references": reference_debug,
        "skipped_chunk_roles": sorted(skipped_chunk_roles),
        "warnings": [],
    }


def _chunking_metadata(chunk_size_tokens: int, chunk_overlap_tokens: int, tokenizer_encoding: str) -> dict[str, object]:
    return {
        "unit": "tokens",
        "chunk_size_tokens": chunk_size_tokens,
        "chunk_overlap_tokens": chunk_overlap_tokens,
        "tokenizer_encoding": tokenizer_encoding,
        "atomic_block_types": sorted(_ATOMIC_BLOCK_TYPES),
        "overlap_strategy": "tail_blocks_or_sentences",
        "heading_context": "prepended_context_header",
    }


def _unique(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _clean_section_text(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    cleaned: list[str] = []
    blank = False
    for line in lines:
        value = _SPACE_RE.sub(" ", line.strip())
        if not value:
            if cleaned and not blank:
                cleaned.append("")
                blank = True
            continue
        cleaned.append(value)
        blank = False
    return "\n".join(cleaned).strip()


def _clean_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _estimate_tokens(text: str, encoding: tiktoken.Encoding | None = None) -> int:
    if not text:
        return 0
    encoding = encoding or tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


def _next_version(session: Session, paper_id: int) -> int:
    current = session.scalar(select(func.max(ProcessedDocument.version)).where(ProcessedDocument.paper_id == paper_id))
    return int(current or 0) + 1


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1 if pattern is _ARXIV_RE else 0).rstrip(".,;") if match else None
