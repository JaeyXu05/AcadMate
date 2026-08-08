from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.db.types import ParseStrategy
from backend.integrations.parsers.cleaning import clean_extracted_text, html_to_markdownish
from backend.schemas import ParsedDocumentPayload

DEFAULT_LOCAL_OCR_PROMPT = "QwenVL HTML"


@dataclass(frozen=True)
class LocalOCRConfig:
    base_url: str
    model: str
    api_key: str = "EMPTY"
    prompt: str = DEFAULT_LOCAL_OCR_PROMPT
    max_tokens: int = 16384
    temperature: float = 0.1
    top_p: float = 0.5
    repetition_penalty: float = 1.05
    dpi: int = 200
    timeout_seconds: float = 300.0


@dataclass(frozen=True)
class LocalOCRPageResult:
    page_number: int
    raw_html: str
    markdown: str
    usage: dict[str, Any]


class LocalOCRParser:
    def __init__(self, config: LocalOCRConfig, *, client: Any | None = None, fitz_module: Any | None = None) -> None:
        self.config = config
        self.client = client or _make_openai_client(config)
        self.fitz = fitz_module

    def parse(self, artifact_path: Path, warnings: list[str] | None = None) -> ParsedDocumentPayload:
        pdf_path = artifact_path.expanduser().resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF path does not exist: {pdf_path}")
        fitz = self.fitz or _require_fitz()
        page_results: list[LocalOCRPageResult] = []
        with fitz.open(pdf_path) as document:
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                image_url = _page_to_data_url(page.get_pixmap(dpi=self.config.dpi))
                page_results.append(self._parse_page(page_index + 1, image_url))
        markdown = _compose_markdown_document(page_results)
        plain_text = clean_extracted_text(markdown)
        return ParsedDocumentPayload(
            strategy=ParseStrategy.local_ocr.value,
            parser_kind="local_ocr",
            plain_text=plain_text,
            markdown_content=markdown,
            json_content={
                "provider": "openai_compatible_multimodal",
                "model": self.config.model,
                "prompt": self.config.prompt,
                "page_count": len(page_results),
                "sampling": {
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "top_p": self.config.top_p,
                    "repetition_penalty": self.config.repetition_penalty,
                    "dpi": self.config.dpi,
                },
                "pages": [
                    {"page": item.page_number, "usage": item.usage, "raw_html_chars": len(item.raw_html), "markdown_chars": len(item.markdown)}
                    for item in page_results
                ],
                "source_pdf": str(pdf_path),
            },
            quality_summary=f"Parsed {len(page_results)} PDF pages with local OCR.",
            warnings=warnings or [],
        )

    def _parse_page(self, page_number: int, image_url: str) -> LocalOCRPageResult:
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": self.config.prompt},
                    ],
                }
            ],
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            extra_body={"repetition_penalty": self.config.repetition_penalty},
        )
        if not response.choices:
            raise RuntimeError(f"Local OCR model returned no choices for page {page_number}.")
        raw_html = _extract_message_text(response.choices[0].message.content)
        return LocalOCRPageResult(page_number=page_number, raw_html=raw_html, markdown=html_to_markdownish(raw_html), usage=_usage_dict(response))


def _make_openai_client(config: LocalOCRConfig) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai is required for local OCR parsing.") from exc
    return OpenAI(api_key=config.api_key, base_url=config.base_url.rstrip("/"), timeout=config.timeout_seconds)


def _require_fitz() -> Any:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for local OCR parsing.") from exc
    return fitz


def _page_to_data_url(pixmap: Any) -> str:
    image_bytes = pixmap.tobytes("png")
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text")
    return str(content)


def _usage_dict(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return dict(usage)


def _compose_markdown_document(page_results: list[LocalOCRPageResult]) -> str:
    return "\n\n".join(f"<!-- page {item.page_number} -->\n{item.markdown.strip()}" for item in page_results if item.markdown.strip()).strip()
