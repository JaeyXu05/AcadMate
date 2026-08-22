from __future__ import annotations

from backend.db.models import Paper
from backend.db.repositories import ParsingRepository
from backend.db.types import ProcessedDocumentStatus, SectionRole
import tiktoken

from backend.services.document_processing import DocumentProcessingService, extract_references, split_markdown_sections


MARKDOWN = """# Sample Paper

<!-- page 1 -->

## Abstract

This paper studies retrieval augmented generation.

## Method

We use evidence chunks for grounded answers.

## References

[1] A. Author. A DOI paper. doi:10.1000/ABC123.
[2] B. Author. An arXiv paper. arXiv:2401.00001v2 https://example.com/paper
"""


def create_parsed_document(session, markdown: str = MARKDOWN):
    paper = Paper(title="Sample Paper")
    session.add(paper)
    session.flush()
    repo = ParsingRepository(session)
    job = repo.create_parse_job(paper.id, status="succeeded", strategy="tex")
    parsed = repo.create_parsed_document(
        paper.id,
        job.id,
        "tex_source",
        markdown_content=markdown,
        plain_text=markdown,
        quality_status="usable",
    )
    session.commit()
    return paper, parsed

def test_split_markdown_sections_classifies_roles():
    sections = split_markdown_sections(MARKDOWN)

    assert [section.heading_path[-1] for section in sections] == ["Sample Paper", "Abstract", "Method", "References"]
    assert [section.role for section in sections] == [SectionRole.title.value, SectionRole.abstract.value, SectionRole.body.value, SectionRole.reference.value]
    assert sections[1].page_start == 1

def test_extract_references():
    references = extract_references(split_markdown_sections(MARKDOWN))

    assert references[0]["doi"] == "10.1000/abc123"
    assert references[0]["title"] == "A DOI paper"
    assert references[0]["authors_json"] == ["A. Author"]
    assert references[1]["arxiv_id"] == "2401.00001"
    assert references[1]["url"] == "https://example.com/paper"


def test_split_markdown_sections_preserves_block_structure():
    markdown = """# Structured Paper

## Method

First paragraph has extra   spaces.

Second paragraph stays separate.

- first item
- second item

| Metric | Value |
| --- | --- |
| Accuracy | 90% |

$$
a = b + c
$$
"""

    method = split_markdown_sections(markdown)[1]

    assert "First paragraph has extra spaces.\n\nSecond paragraph stays separate." in method.cleaned_text
    assert "- first item\n- second item" in method.cleaned_text
    assert "| Metric | Value |\n| --- | --- |\n| Accuracy | 90% |" in method.cleaned_text
    assert "$$\na = b + c\n$$" in method.cleaned_text

def test_process_parsed_document_creates_ready_document_sections_chunks_references(session):
    paper, parsed = create_parsed_document(session)

    processed = DocumentProcessingService(session, chunk_size_chars=80, chunk_overlap_chars=10).process_parsed_document(parsed.id)

    assert processed.status == ProcessedDocumentStatus.ready.value
    assert processed.content_markdown == MARKDOWN.strip()
    assert processed.metadata_json["analysis_excludes_roles"] == [SectionRole.reference.value]
    assert processed.metadata_json["skipped_chunk_roles"] == [SectionRole.reference.value]
    assert len(processed.sections) == 4
    assert len(processed.chunks) >= 3
    assert all(chunk.role != SectionRole.reference.value for chunk in processed.chunks)
    assert all("A DOI paper" not in chunk.content_text for chunk in processed.chunks)
    assert len(processed.references) == 2
    assert processed.references[0].doi == "10.1000/abc123"
    assert processed.references[0].authors_json == ["A. Author"]
    assert processed.references[0].title == "A DOI paper"

def test_chunk_key_and_index_are_unique(session):
    _, parsed = create_parsed_document(session, "# Body\n\n" + "abcdef " * 100)

    processed = DocumentProcessingService(session, chunk_size_chars=120, chunk_overlap_chars=20).process_parsed_document(parsed.id)

    chunk_keys = [chunk.chunk_key for chunk in processed.chunks]
    chunk_indexes = [chunk.chunk_index for chunk in processed.chunks]
    assert len(chunk_keys) == len(set(chunk_keys))
    assert chunk_indexes == list(range(1, len(chunk_indexes) + 1))


def test_processing_chunks_preserve_blocks_and_boundaries(session):
    markdown = """# Chunk Paper

## Method

Alpha sentence one. Alpha sentence two.

- beta item one
- beta item two

| Metric | Value |
| --- | --- |
| Accuracy | 90% |

Gamma sentence one. Gamma sentence two.
"""
    _, parsed = create_parsed_document(session, markdown)

    processed = DocumentProcessingService(session, chunk_size_chars=95, chunk_overlap_chars=20).process_parsed_document(parsed.id)
    chunk_texts = [chunk.content_text for chunk in processed.chunks]

    assert all(chunk.strip() == chunk for chunk in chunk_texts)
    assert any("\n\n" in chunk for chunk in chunk_texts)
    assert any("- beta item one\n- beta item two" in chunk for chunk in chunk_texts)
    assert any("| Metric | Value |\n| --- | --- |" in chunk for chunk in chunk_texts)
    assert all(not chunk.endswith("senten") for chunk in chunk_texts)


def test_oversized_paragraph_splits_on_sentence_boundaries(session):
    sentence = "This sentence should remain intact for chunk splitting."
    _, parsed = create_parsed_document(session, "# Body\n\n" + " ".join([sentence] * 8))

    processed = DocumentProcessingService(session, chunk_size_chars=120, chunk_overlap_chars=0).process_parsed_document(parsed.id)
    chunk_texts = [chunk.content_text for chunk in processed.chunks if chunk.role == SectionRole.body.value]

    assert len(chunk_texts) > 1
    assert all(chunk for chunk in chunk_texts)
    assert all(chunk.endswith(".") for chunk in chunk_texts)

def test_chunk_content_includes_heading_context_and_role_detail(session):
    markdown = """# Paper

## Method

We train the model with evidence chunks.
"""
    _, parsed = create_parsed_document(session, markdown)

    processed = DocumentProcessingService(session, chunk_size_tokens=80, chunk_overlap_tokens=8).process_parsed_document(parsed.id)
    method_chunk = next(chunk for chunk in processed.chunks if chunk.role == SectionRole.body.value)

    assert method_chunk.content_text.startswith("Context: Paper > Method\nRole: body\nDetail: method")
    assert method_chunk.metadata_json["heading_context"]["included_in_content"] is True
    assert method_chunk.metadata_json["section_classification"]["role_detail"] == "method"


def test_fine_role_details_stored_in_section_metadata():
    markdown = """# Paper

## Introduction

Intro text.

## Related Work

Prior work.

## Experiments

Experiment text.

## Limitations

Limitation text.
"""

    sections = split_markdown_sections(markdown)
    details = [section.metadata["classification"]["role_detail"] for section in sections]

    assert details == ["title", "introduction", "related_work", "experiment", "limitations"]
    assert all(section.role == SectionRole.body.value for section in sections[1:])


def test_token_aware_chunking_counts_with_tiktoken(session):
    _, parsed = create_parsed_document(session, "# Paper\n\n## Method\n\n" + "Token aware sentence. " * 12)

    processed = DocumentProcessingService(session, chunk_size_tokens=45, chunk_overlap_tokens=6).process_parsed_document(parsed.id)
    encoding = tiktoken.get_encoding("cl100k_base")

    assert processed.metadata_json["chunking"]["unit"] == "tokens"
    assert processed.metadata_json["chunking"]["chunk_size_tokens"] == 45
    assert all(chunk.token_estimate == len(encoding.encode(chunk.content_text)) for chunk in processed.chunks)


def test_atomic_table_and_display_math_metadata(session):
    markdown = """# Paper

## Results

Table 1: Accuracy results.

| Metric | Value |
| --- | --- |
| Accuracy | 90% |

$$
a = b + c
$$
"""
    _, parsed = create_parsed_document(session, markdown)

    processed = DocumentProcessingService(session, chunk_size_tokens=90, chunk_overlap_tokens=0).process_parsed_document(parsed.id)
    block_types = [block_type for chunk in processed.chunks for block_type in chunk.metadata_json["block_types"]]

    assert "markdown_table" in block_types
    assert "display_math" in block_types
    assert any("| Metric | Value |\n| --- | --- |\n| Accuracy | 90% |" in chunk.content_text for chunk in processed.chunks)
    assert any("$$\na = b + c\n$$" in chunk.content_text for chunk in processed.chunks)


def test_tail_overlap_uses_complete_sentence_metadata(session):
    sentence = "This sentence should overlap cleanly."
    _, parsed = create_parsed_document(session, "# Paper\n\n## Method\n\n" + " ".join([sentence] * 10))

    processed = DocumentProcessingService(session, chunk_size_tokens=35, chunk_overlap_tokens=8).process_parsed_document(parsed.id)
    overlapped = [chunk for chunk in processed.chunks if chunk.metadata_json.get("overlap_from_previous")]

    assert overlapped
    assert all(chunk.metadata_json["overlap_strategy"] == "tail_blocks_or_sentences" for chunk in overlapped)
    assert any(sentence in chunk.content_text for chunk in overlapped)


def test_heading_hierarchy_handles_nested_and_skipped_levels():
    normal = split_markdown_sections("# Paper\n\n## Method\n\n### Training\n\nBody.")
    skipped = split_markdown_sections("## Abstract\n\nText.\n\n#### Detail\n\nMore.")

    assert normal[-1].heading_path == ["Paper", "Method", "Training"]
    assert skipped[0].heading_path == ["Document", "Abstract"]
    assert skipped[1].heading_path == ["Document", "Abstract", "Detail"]


def test_caption_and_body_relation_metadata(session):
    markdown = """# Paper

## Results

Figure 1: System overview.

The result in Figure 1 improves accuracy.

Table 2: Ablation.

| Metric | Value |
| --- | --- |
| Accuracy | 90% |
"""
    _, parsed = create_parsed_document(session, markdown)

    processed = DocumentProcessingService(session, chunk_size_tokens=140, chunk_overlap_tokens=0).process_parsed_document(parsed.id)
    related = [relation for chunk in processed.chunks for relation in chunk.metadata_json.get("related_objects", [])]

    assert any(relation["relation_id"] == "figure:1" and "caption_for" in relation["relation_types"] for relation in related)
    assert any(relation["relation_id"] == "figure:1" and "mentions" in relation["relation_types"] for relation in related)
    assert any(relation["relation_id"] == "table:2" and "table_for" in relation["relation_types"] for relation in related)


def test_parser_references_preferred_over_markdown_references(session):
    markdown = """# Paper

## References

[1] Markdown Author. Markdown fallback reference. doi:10.1000/fallback.
"""
    paper, parsed = create_parsed_document(session, markdown)
    parsed.json_content = {"references": ["Parser Author. Parser structured reference. doi:10.1000/parser."]}
    session.commit()

    processed = DocumentProcessingService(session).process_parsed_document(parsed.id)

    assert len(processed.references) == 1
    assert processed.references[0].doi == "10.1000/parser"
    assert processed.references[0].metadata_json["reference_source"] == "parser_structure"
    assert processed.metadata_json["processing_debug_report"]["references"]["source"] == "parser_structure"
    assert processed.paper_id == paper.id


def test_processing_debug_report_counts_quality_metrics(session):
    _, parsed = create_parsed_document(session)

    processed = DocumentProcessingService(session, chunk_size_tokens=80, chunk_overlap_tokens=8).process_parsed_document(parsed.id)
    report = processed.metadata_json["processing_debug_report"]

    assert report["profile"] == "normalized_heading_structured_chunk_v4"
    assert report["section_count"] == len(processed.sections)
    assert report["chunk_count"] == len(processed.chunks)
    assert report["reference_count"] == len(processed.references)
    assert report["chunk_token_stats"]["target"] == 80
    assert report["heading_context"]["included_in_chunks"] is True


def test_process_latest_parsed_document(session):
    paper, _ = create_parsed_document(session)

    processed = DocumentProcessingService(session).process_latest_parsed_document(paper.id)

    assert processed.paper_id == paper.id
    assert processed.status == ProcessedDocumentStatus.ready.value

def test_repeated_processing_regenerates_deterministically(session):
    _, parsed = create_parsed_document(session)
    service = DocumentProcessingService(session, chunk_size_chars=100, chunk_overlap_chars=10)

    first = service.process_parsed_document(parsed.id)
    first_shape = ([section.cleaned_text for section in first.sections], [chunk.content_text for chunk in first.chunks])
    second = service.process_parsed_document(parsed.id)
    second_shape = ([section.cleaned_text for section in second.sections], [chunk.content_text for chunk in second.chunks])

    assert first.id != second.id
    assert second.version == 1
    assert first_shape == second_shape
