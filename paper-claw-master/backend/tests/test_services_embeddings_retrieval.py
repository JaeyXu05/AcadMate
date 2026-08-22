from __future__ import annotations

import numpy as np

from backend.db.models import Paper
from backend.db.repositories import ParsingRepository
from backend.db.types import ProcessedDocumentStatus, SectionRole
from backend.schemas import ResolvedProviderConfig
from backend.services.embeddings import EmbeddingService
from backend.services.retrieval import RetrievalService


def fixture_embedding_provider(*, dimension: int = 3) -> ResolvedProviderConfig:
    return ResolvedProviderConfig(
        id=0,
        name="fixture-embedding",
        kind="embedding",
        provider="fixture",
        model="fixture-embedding-v1",
        settings={"dimension": dimension},
    )


def embedding_service(session, *, dimension: int = 3) -> EmbeddingService:
    return EmbeddingService(session, embedding_provider=fixture_embedding_provider(dimension=dimension))


def create_processed_chunks(session):
    paper = Paper(title="Embedding Paper")
    session.add(paper)
    session.flush()
    repo = ParsingRepository(session)
    job = repo.create_parse_job(paper.id, status="succeeded", strategy="fixture")
    parsed = repo.create_parsed_document(paper.id, job.id, "fixture", plain_text="text", markdown_content="text")
    processed = repo.create_processed_document(
        paper.id,
        parsed.id,
        job.id,
        status=ProcessedDocumentStatus.ready.value,
        content_text="text",
        content_markdown="text",
    )
    alpha = repo.add_chunk(processed.id, "alpha", 1, "retrieval evidence alpha alpha", role=SectionRole.body.value)
    beta = repo.add_chunk(processed.id, "beta", 2, "vision ocr image beta beta", role=SectionRole.body.value)
    gamma = repo.add_chunk(processed.id, "gamma", 3, "citation reference bibliography gamma", role=SectionRole.reference.value)
    session.commit()
    return paper, [alpha, beta, gamma]


def test_fixture_embeddings_persist_to_chunks(session):
    paper, chunks = create_processed_chunks(session)

    count = embedding_service(session).embed_missing_chunks(paper.id)

    assert count == 3
    for chunk in chunks:
        assert chunk.embedding is not None
        assert chunk.embedding_model == "fixture-embedding-v1"
        assert chunk.embedding_dimension == 3


def test_embed_missing_chunks_skips_existing_vectors(session):
    paper, chunks = create_processed_chunks(session)
    chunks[0].embedding = [1.0, 0.0, 0.0]
    chunks[0].embedding_model = "manual"
    chunks[0].embedding_dimension = 3
    session.commit()

    count = embedding_service(session).embed_missing_chunks(paper.id)

    assert count == 2
    assert chunks[0].embedding_model == "manual"


def test_vector_retrieval_ranks_expected_chunk(session):
    paper, _ = create_processed_chunks(session)
    service = embedding_service(session)
    service.embed_missing_chunks(paper.id)

    results = RetrievalService(session, service).retrieve(paper.id, "retrieval evidence", limit=2)

    assert results[0].metadata["chunk_key"] == "alpha"
    assert results[0].retrieval_mode == "vector"


def test_vector_retrieval_accepts_numpy_embeddings(session):
    paper, chunks = create_processed_chunks(session)
    chunks[0].embedding = np.array([1.0, 0.0, 0.0])
    chunks[0].embedding_model = "manual"
    chunks[0].embedding_dimension = 3
    service = embedding_service(session)

    results = RetrievalService(session, service).retrieve(paper.id, "retrieval evidence", limit=1)

    assert results[0].metadata["chunk_key"] == "alpha"
    assert results[0].retrieval_mode == "vector"


def test_lexical_fallback_without_embeddings(session):
    paper, _ = create_processed_chunks(session)

    results = RetrievalService(session).retrieve(paper.id, "citation bibliography", limit=1)

    assert results[0].metadata["chunk_key"] == "gamma"
    assert results[0].retrieval_mode == "lexical"


def test_embedding_dimension_from_provider_settings(session):
    paper, chunks = create_processed_chunks(session)

    embedding_service(session, dimension=5).embed_missing_chunks(paper.id)

    assert chunks[0].embedding_dimension == 5
    assert len(chunks[0].embedding) == 5
