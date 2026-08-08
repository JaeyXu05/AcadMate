from __future__ import annotations

import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_DISPLAY_MATH_RE = re.compile(r"(\$\$.*?\$\$|\\\[.*?\\\]|\\begin\{(?:equation\*?|align\*?|gather\*?)\}.*?\\end\{(?:equation\*?|align\*?|gather\*?)\})", re.DOTALL)
_MARKDOWN_TABLE_RE = re.compile(r"(^\|.*\|\n^\|(?:\s*:?-{3,}:?\s*\|)+\s*$\n(?:^\|.*\|(?:\n|$))+)" , re.MULTILINE)
_EMBEDDED_CAPTION_RE = re.compile(r"(?<!\n)(\s+)((?:Figure|Fig\.|Table)\s+\d+\s*[:.].+?)(?=(?:\n|\s{2,}|$))", re.IGNORECASE)


def clean_markdown_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text, protected = _protect_blocks(text)
    text = _SPACE_RE.sub(" ", text)
    text = _EMBEDDED_CAPTION_RE.sub(lambda match: f"\n\n{match.group(2).strip()}\n\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    text = _restore_blocks(text, protected)
    return text.strip()


def clean_extracted_text(text: str) -> str:
    text = _HTML_TAG_RE.sub(" ", text)
    text = clean_markdown_text(text)
    return re.sub(r"\s+", " ", text).strip()


def html_to_markdownish(text: str) -> str:
    text = re.sub(r"</?(?:p|div|section|article)[^>]*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<h([1-6])[^>]*>(.*?)</h\1>", lambda match: f"\n\n{'#' * int(match.group(1))} {match.group(2)}\n\n", text, flags=re.IGNORECASE | re.DOTALL)
    return clean_markdown_text(_HTML_TAG_RE.sub("", text))


def _protect_blocks(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = f"PAPERCLAWPROTECTEDBLOCK{len(protected)}"
        protected[token] = match.group(0).strip()
        return f"\n\n{token}\n\n"

    text = _DISPLAY_MATH_RE.sub(replace, text)
    text = _MARKDOWN_TABLE_RE.sub(replace, text)
    return text, protected


def _restore_blocks(text: str, protected: dict[str, str]) -> str:
    for token, value in protected.items():
        text = text.replace(token, value)
    return text
