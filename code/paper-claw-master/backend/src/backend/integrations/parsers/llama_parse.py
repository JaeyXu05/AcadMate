from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.db.types import ParseStrategy
from backend.integrations.parsers.cleaning import clean_extracted_text, clean_markdown_text
from backend.schemas import ParsedDocumentPayload


@dataclass(frozen=True)
class LlamaParseConfig:
    api_key: str
    tier: str = "cost_effective"
    result_type: str = "markdown"
    timeout_seconds: float = 300.0
    extra_time_per_page_seconds: float = 45.0


class LlamaParseParser:
    def __init__(self, config: LlamaParseConfig, *, parser: Any | None = None) -> None:
        self.config = config
        self.parser = parser

    def parse(self, artifact_path: Path, warnings: list[str] | None = None) -> ParsedDocumentPayload:
        pdf_path = artifact_path.expanduser().resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF path does not exist: {pdf_path}")
        parser = self.parser or self._make_parser()
        documents = parser.load_data(str(pdf_path))
        markdown = clean_markdown_text("\n\n".join(_document_text(document) for document in documents))
        return ParsedDocumentPayload(
            strategy=ParseStrategy.llama_parse.value,
            parser_kind="llama_parse",
            plain_text=clean_extracted_text(markdown),
            markdown_content=markdown,
            json_content={"source_pdf": str(pdf_path), "document_count": len(documents), "tier": self.config.tier},
            quality_summary=f"Parsed PDF with LlamaParse into {len(documents)} document parts.",
            warnings=warnings or [],
        )

    def _make_parser(self) -> Any:
        try:
            from llama_cloud_services import LlamaParse
        except ImportError as exc:
            raise RuntimeError("llama-cloud-services is required for LlamaParse parsing.") from exc
        return LlamaParse(
            api_key=self.config.api_key,
            result_type=self.config.result_type,
            premium_mode=self.config.tier == "premium",
            parsing_instruction="Parse the academic paper preserving headings, equations, tables, and references.",
        )


def _document_text(document: Any) -> str:
    if isinstance(document, str):
        return document
    for attr in ("text", "markdown", "content"):
        value = getattr(document, attr, None)
        if value:
            return str(value)
    return str(document)
