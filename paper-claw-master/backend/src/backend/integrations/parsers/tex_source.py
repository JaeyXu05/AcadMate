from __future__ import annotations

import re
import shutil
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from backend.db.types import ParseStrategy
from backend.integrations.parsers.cleaning import clean_extracted_text, clean_markdown_text
from backend.schemas import ParsedDocumentPayload


@dataclass
class _State:
    warnings: list[str] = field(default_factory=list)
    used_files: list[str] = field(default_factory=list)
    missing_includes: list[str] = field(default_factory=list)
    simple_macros: dict[str, str] = field(default_factory=dict)


_HEADING_COMMANDS: tuple[tuple[str, str], ...] = (
    ("part", "#"),
    ("chapter", "#"),
    ("section", "##"),
    ("subsection", "###"),
    ("subsubsection", "####"),
    ("paragraph", "#####"),
)
_INLINE_COMMANDS = "textbf|textit|emph|underline|texttt|textrm|mathrm|mathbf|mathit|operatorname|textsc|small|footnotesize|scriptsize|large|Large"
_DOCUMENT_ENV_RE = re.compile(r"\\begin\{document\}(.*?)\\end\{document\}", re.IGNORECASE | re.DOTALL)
_ABSTRACT_ENV_RE = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.IGNORECASE | re.DOTALL)
_ABSTRACT_COMMAND_RE = re.compile(r"\\(?:abstract|setabstract)\*?(?:\[[^\]]*\])?\s*\{", re.IGNORECASE)
_CENTERLINE_ABSTRACT_RE = re.compile(r"\\centerline\s*\{\s*\\bf\s+Abstract\s*\}", re.IGNORECASE)
_TITLE_COMMAND_RE = re.compile(r"\\(?:title|icmltitle)\*?(?:\[[^\]]*\])?\s*\{", re.IGNORECASE)
_RUNNING_TITLE_RE = re.compile(r"\\runningtitle\*?(?:\[[^\]]*\])?\s*\{", re.IGNORECASE)
_LEGACY_TITLE_RE = re.compile(r"\\(?:long)?papertitle\s*\{", re.IGNORECASE)
_CENTERLINE_REFERENCES_RE = re.compile(r"\\centerline\s*\{\s*\\bf\s+References\s*\}", re.IGNORECASE)
_LEGACY_REFERENCES_HEADING_RE = re.compile(r"\\section\*?\s*\{\s*References\s*\}|\\centerline\s*\{\s*\\bf\s+References\s*\}", re.IGNORECASE)
_AUTHOR_COMMAND_RE = re.compile(r"\\author\*?(?:\[[^\]]*\])?\s*\{", re.IGNORECASE)
_INCLUDE_RE = re.compile(r"\\(?:input|include)\s*(?:\[[^\]]*\])?\{([^}]+)\}")
_BIB_RESOURCE_RE = re.compile(r"\\(?:bibliography|addbibresource)\s*\{([^}]*)\}", re.IGNORECASE)
_THEBIB_ENV_RE = re.compile(r"\\begin\{thebibliography\}(?:\{[^}]*\})?(.*?)\\end\{thebibliography\}", re.IGNORECASE | re.DOTALL)
_FLOAT_ENV_RE = re.compile(r"\\begin\{(figure\*?|table\*?)\}(?:\[[^\]]*\])?(.*?)\\end\{\1\}", re.IGNORECASE | re.DOTALL)
_TABLE_ENV_RE = re.compile(r"\\begin\{(?:tabular\*?|tabularx|longtable)\}(?:\{[^}]*\}){0,2}(.*?)\\end\{(?:tabular\*?|tabularx|longtable)\}", re.IGNORECASE | re.DOTALL)
_MATH_ENV_RE = re.compile(r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|flalign\*?)\}(.*?)\\end\{\1\}", re.IGNORECASE | re.DOTALL)
_DISPLAY_MATH_RE = re.compile(r"\\\[(.*?)\\\]|\$\$(.*?)\$\$", re.DOTALL)
_INLINE_MATH_RE = re.compile(r"\\\((.*?)\\\)|(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)")
_SIMPLE_MACRO_RE = re.compile(
    r"(?:\\def\\(?P<def_name>[A-Za-z@]+)(?!\s*#)\s*\{(?P<def_value>(?:[^{}]|\{[^{}]*\})*)\}|"
    r"\\newcommand\s*\{\\(?P<new_name>[A-Za-z@]+)\}\s*(?:\[0\])?\s*\{(?P<new_value>(?:[^{}]|\{[^{}]*\})*)\})",
    re.IGNORECASE | re.DOTALL,
)
_SPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")



class TexSourceParser:
    def parse(self, artifact_path: Path, warnings: list[str] | None = None) -> ParsedDocumentPayload:
        artifact_path = artifact_path.expanduser().resolve()
        state = _State(warnings=list(warnings or []))
        with _prepare_source_root(artifact_path, state) as source_root:
            main_tex = _resolve_main_tex(artifact_path, source_root)
            tex_files = sorted(path for path in source_root.rglob("*.tex") if path.is_file())
            bib_files = sorted(path for path in source_root.rglob("*.bib") if path.is_file())
            expanded = _expand_tex_file(main_tex, source_root, state=state, seen=set(), depth=0)
            title = _extract_title(expanded) or _cleanup_inline_tex(main_tex.stem.replace("_", " "))
            authors = _extract_command_value(expanded, _AUTHOR_COMMAND_RE)
            abstract = _extract_abstract(expanded)
            label_contexts = _collect_label_contexts(expanded)
            references = _extract_reference_entries(expanded, source_root, main_tex, state)
            markdown = _build_markdown(
                expanded,
                title=title,
                authors=authors,
                abstract=abstract,
                references=references,
                label_contexts=label_contexts,
                source_root=source_root,
                image_dir=Path(),
                state=state,
                copy_images=False,
            )
            markdown = clean_markdown_text(markdown)
            plain_text = clean_extracted_text(_markdown_to_plain(markdown))
            return ParsedDocumentPayload(
                strategy=ParseStrategy.tex.value,
                parser_kind="tex_source",
                plain_text=plain_text,
                markdown_content=markdown,
                json_content={
                    "source_path": str(artifact_path),
                    "source_root": str(source_root),
                    "main_tex": _relative_path(main_tex, source_root),
                    "tex_files": [_relative_path(path, source_root) for path in tex_files],
                    "bib_files": [_relative_path(path, source_root) for path in bib_files],
                    "used_files": state.used_files,
                    "missing_includes": state.missing_includes,
                    "references_count": len(references),
                    "references": references,
                },
                quality_summary=f"Parsed TeX source from {_relative_path(main_tex, source_root)} with {len(state.used_files)} source files and {len(references)} references.",
                warnings=state.warnings,
            )


@contextmanager
def _prepare_source_root(path: Path, state: _State) -> Iterator[Path]:
    if path.is_dir():
        yield path
        return
    if path.suffix.lower() == ".tex":
        yield path.parent
        return
    with tempfile.TemporaryDirectory(prefix="tex2md-") as temp_dir:
        root = Path(temp_dir) / "source"
        root.mkdir(parents=True, exist_ok=True)
        if zipfile.is_zipfile(path):
            _safe_extract_zip(path, root, state)
            yield root
            return
        if tarfile.is_tarfile(path):
            with tarfile.open(path) as archive:
                _safe_extract_tar(archive, root, state)
            yield root
            return
        raise ValueError(f"Unsupported input type: {path}")


def _safe_extract_zip(path: Path, destination: Path, state: _State) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            target = (destination / info.filename.lstrip("/")).resolve()
            if not _is_relative_to(target, destination):
                state.warnings.append(f"Skipped unsafe archive member: {info.filename}")
                continue
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def _safe_extract_tar(archive: tarfile.TarFile, destination: Path, state: _State) -> None:
    destination = destination.resolve()
    members = []
    for member in archive.getmembers():
        target = (destination / member.name.lstrip("/")).resolve()
        if not _is_relative_to(target, destination):
            state.warnings.append(f"Skipped unsafe archive member: {member.name}")
            continue
        if member.issym() or member.islnk():
            state.warnings.append(f"Skipped linked archive member: {member.name}")
            continue
        members.append(member)
    archive.extractall(destination, members=members, filter="data")


def _resolve_main_tex(input_path: Path, source_root: Path) -> Path:
    if input_path.suffix.lower() == ".tex":
        return input_path
    tex_files = sorted(path for path in source_root.rglob("*.tex") if path.is_file())
    if not tex_files:
        raise ValueError(f"No .tex files found in {input_path}.")
    return _select_main_tex(tex_files, source_root)


def _select_main_tex(tex_files: list[Path], source_root: Path) -> Path:
    def score(path: Path) -> tuple[int, int, int]:
        text = _read_text_file(path)
        name = path.name.lower()
        lowered_path = _relative_path(path, source_root).lower()
        value = 0
        if "\\documentclass" in text:
            value += 10
        if "\\begin{document}" in text:
            value += 10
        if name in {"main.tex", "paper.tex", "ms.tex", "article.tex", "manuscript.tex", "main_arxiv.tex"}:
            value += 5
        if name.startswith("main"):
            value += 4
        if any(part in lowered_path for part in ("supplement", "appendix", "response", "rebuttal", "template")):
            value -= 5
        if name.startswith("acl_") or "lualatex" in name or "xelatex" in name:
            value -= 8
        value += min(len(re.findall(r"\\(?:section|subsection|subsubsection)\*?\{", text)), 8)
        value += min(len(_INCLUDE_RE.findall(text)), 4)
        return value, -len(path.parts), -path.stat().st_size

    return max(tex_files, key=score)


def _expand_tex_file(path: Path, source_root: Path, *, state: _State, seen: set[Path], depth: int) -> str:
    resolved = path.resolve()
    if resolved in seen:
        state.warnings.append(f"Skipped recursive include: {_relative_path(resolved, source_root)}")
        return ""
    if depth > 60:
        state.warnings.append(f"Maximum include depth exceeded at {_relative_path(resolved, source_root)}")
        return ""
    seen.add(resolved)
    try:
        relative = _relative_path(resolved, source_root)
        if relative not in state.used_files:
            state.used_files.append(relative)
        text = _strip_comments(_read_text_file(resolved)).split("\\endinput", 1)[0]
        _collect_simple_macros(text, state)

        def replace_include(match: re.Match[str]) -> str:
            raw = match.group(1).strip()
            include_path = _resolve_include_path(resolved.parent, raw, source_root)
            if include_path is None:
                state.missing_includes.append(raw)
                state.warnings.append(f"Missing include file: {raw}")
                return "\n\n"
            return "\n\n" + _expand_tex_file(include_path, source_root, state=state, seen=seen, depth=depth + 1) + "\n\n"

        return _INCLUDE_RE.sub(replace_include, text)
    finally:
        seen.remove(resolved)


def _resolve_include_path(base_dir: Path, raw: str, source_root: Path) -> Path | None:
    value = raw.strip().strip('"').strip("'")
    if not value:
        return None
    candidate = Path(value)
    possibilities = [candidate] if candidate.suffix else [candidate.with_suffix(".tex"), candidate]
    roots = [base_dir.resolve(), source_root.resolve()]
    seen: set[Path] = set()
    for possibility in possibilities:
        for root in roots:
            resolved = (root / possibility).resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if resolved.is_file() and _is_relative_to(resolved, source_root.resolve()):
                return resolved
        for matched in source_root.resolve().rglob(possibility.name):
            resolved = matched.resolve()
            if resolved not in seen and resolved.is_file() and _is_relative_to(resolved, source_root.resolve()):
                return resolved
    return None


def _build_markdown(text: str, *, title: str | None, authors: str | None, abstract: str | None, references: list[str], label_contexts: dict[str, str], source_root: Path, image_dir: Path, state: _State, copy_images: bool = True) -> str:
    body = _extract_document_body(text)
    body = _expand_simple_macros(body, state)
    body = _replace_cross_references(body, label_contexts)
    body = body.replace("\\maketitle", "\n\n")
    body = _ABSTRACT_ENV_RE.sub("\n\n", body)
    body = _remove_abstract_commands(body)
    body = _remove_legacy_abstract_block(body)
    body = _remove_legacy_reference_blocks(body)
    body = _THEBIB_ENV_RE.sub("\n\n", body)
    body = _BIB_RESOURCE_RE.sub("\n\n", body)
    body = re.sub(r"\\bibliographystyle\s*\{[^}]*\}", "\n\n", body, flags=re.IGNORECASE)
    body = re.sub(r"\\printbibliography\b", "\n\n", body, flags=re.IGNORECASE)
    body = re.sub(r"\\appendix\b", "\n\n## Appendix\n\n", body, count=1)
    body = _FLOAT_ENV_RE.sub(lambda match: _render_float_block(match.group(1), match.group(2), source_root, image_dir, state, copy_images), body)
    body = _TABLE_ENV_RE.sub(lambda match: _render_table_block(match.group(1)), body)
    body = _render_statement_environments(body)
    body = _unwrap_passthrough_environments(body)
    body = _drop_latex_environment_options(body)
    body = _MATH_ENV_RE.sub(lambda match: _render_display_math(match.group(2)), body)
    body = _DISPLAY_MATH_RE.sub(lambda match: _render_display_math(match.group(1) or match.group(2) or ""), body)
    body = _replace_heading_commands(body)
    body = _render_list_environments(body)
    body = _cleanup_structured_tex_body(body)

    parts: list[str] = []
    if title:
        parts.append(f"# {title}")
    if authors:
        cleaned_authors = _cleanup_inline_tex(authors)
        if cleaned_authors:
            parts.append(f"**Author:** {cleaned_authors}")
    if abstract:
        parts.append(f"## Abstract\n\n{abstract}")
    if body.strip():
        parts.append(body.strip())
    if references:
        parts.append("## References\n\n" + "\n".join(f"- {entry}" for entry in references))
    return "\n\n".join(parts)


def _render_float_block(env_name: str, content: str, source_root: Path, image_dir: Path, state: _State, copy_images: bool = True) -> str:
    label = "Figure" if env_name.lower().startswith("figure") else "Table"
    caption = _extract_command_argument(content, "caption")
    pieces = []
    if label == "Figure":
        pieces.extend(_render_graphics_sequence(content, caption, source_root, image_dir, state, copy_images))
    else:
        pieces.append(_render_table_block(content).strip())
    content = _remove_latex_command_arguments(content, "caption", 1)
    content = _remove_latex_command_arguments(content, "subcaption", 1)
    content = _remove_latex_command_arguments(content, "subfloat", 1)
    content = re.sub(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]*\}", " ", content, flags=re.IGNORECASE)
    content = re.sub(r"\\label\{[^}]*\}", " ", content, flags=re.IGNORECASE)
    body = _cleanup_structured_tex_body(content)
    if caption:
        pieces.append(f"{label}: {_cleanup_inline_tex(caption)}")
    if body and body.casefold() not in {piece.casefold() for piece in pieces}:
        pieces.append(body)
    return "\n\n" + "\n\n".join(piece for piece in pieces if piece and piece.strip()) + "\n\n"


def _render_graphics_sequence(content: str, caption: str | None, source_root: Path, image_dir: Path, state: _State, copy_images: bool = True) -> list[str]:
    pieces: list[str] = []
    subcaptions = _extract_ordered_command_values(content, "subcaption") + _extract_subfloat_captions(content)
    for index, graphic in enumerate(_extract_graphics_paths(content)):
        subcaption = subcaptions[index] if index < len(subcaptions) else None
        alt = _cleanup_inline_tex(subcaption or caption or Path(graphic).stem)
        copied = _copy_graphic(graphic, source_root, image_dir, state) if copy_images else None
        pieces.append(f"![{alt}]({copied})" if copied else f"![{alt}]({graphic})")
        if subcaption:
            pieces.append(f"Subfigure: {_cleanup_inline_tex(subcaption)}")
    return pieces


def _extract_ordered_command_values(text: str, command: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(rf"\\{re.escape(command)}\*?(?:\[[^\]]*\])?\s*\{{", text, re.IGNORECASE):
        value, _ = _read_braced_value(text, match.end() - 1)
        if value.strip():
            values.append(value.strip())
    return values


def _extract_subfloat_captions(text: str) -> list[str]:
    captions: list[str] = []
    for match in re.finditer(r"\\subfloat\s*(?:\[([^\]]*)\])?", text, re.IGNORECASE):
        if match.group(1) and match.group(1).strip():
            captions.append(match.group(1).strip())
    return captions


def _extract_graphics_paths(content: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}", content, flags=re.IGNORECASE)]


def _copy_graphic(raw: str, source_root: Path, image_dir: Path, state: _State) -> str | None:
    value = raw.strip().strip('"').strip("'")
    if not value or "#" in value or re.search(r"\\[A-Za-z@]+", value):
        return None
    candidate = Path(value)
    possibilities = [candidate] if candidate.suffix else [candidate.with_suffix(ext) for ext in (".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg")] + [candidate]
    for possibility in possibilities:
        for root in [source_root, *source_root.rglob("figures")]:
            path = (root / possibility).resolve()
            if path.is_file() and _is_relative_to(path, source_root.resolve()):
                image_dir.mkdir(parents=True, exist_ok=True)
                target = image_dir / path.name
                if not target.exists():
                    shutil.copy2(path, target)
                return str(target.relative_to(image_dir.parent)) if _is_relative_to(target, image_dir.parent) else str(target)
            case_match = _find_case_insensitive_path(root, possibility, source_root)
            if case_match is not None:
                image_dir.mkdir(parents=True, exist_ok=True)
                target = image_dir / case_match.name
                if not target.exists():
                    shutil.copy2(case_match, target)
                return str(target.relative_to(image_dir.parent)) if _is_relative_to(target, image_dir.parent) else str(target)
    if value:
        state.warnings.append(f"Missing image file: {value}")
    return None


def _render_table_block(content: str) -> str:
    cleaned = _normalize_table_content(content)
    rows = []
    for raw_row in re.split(r"\\\\", cleaned):
        row = raw_row.strip()
        if not row:
            continue
        cells = [_cleanup_inline_tex(cell) for cell in re.split(r"(?<!\\)&", row)]
        cells = [cell for cell in cells if cell and not _is_table_layout_cell(cell)]
        if cells:
            rows.append(cells)
    if not rows:
        return "\n\n"
    width = max(len(row) for row in rows)
    for row in rows:
        row.extend([""] * (width - len(row)))
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return "\n\n" + "\n".join(lines) + "\n\n"


def _collect_label_contexts(text: str) -> dict[str, str]:
    contexts: dict[str, str] = {}
    for match in re.finditer(r"\\label\s*\{([^}]*)\}", text):
        label = match.group(1).strip()
        if not label or label in contexts:
            continue
        before = text[max(0, match.start() - 2500):match.start()]
        after = text[match.end():min(len(text), match.end() + 600)]
        context = _label_context_from_window(label, before) or _label_context_from_window(label, after)
        if context:
            contexts[label] = context
    return contexts


def _label_context_from_window(label: str, window: str) -> str | None:
    captions = list(re.finditer(r"\\caption\*?(?:\[[^\]]*\])?\s*\{", window, re.IGNORECASE))
    if captions:
        caption = _extract_command_argument(window[captions[-1].start():], "caption")
        if caption:
            kind = "Table" if label.lower().startswith(("tab:", "table:")) else "Figure" if label.lower().startswith(("fig:", "figure:")) else "Caption"
            return f"{kind}: {_cleanup_inline_tex(caption)}"
    headings = list(re.finditer(r"\\(?:section|subsection|subsubsection|paragraph)\*?(?:\[[^\]]*\])?\s*\{", window, re.IGNORECASE))
    if headings:
        command = re.match(r"\\([A-Za-z]+)", headings[-1].group(0))
        value, _ = _read_braced_value(window, window.find("{", headings[-1].start()))
        kind = (command.group(1).capitalize() if command else "Section")
        return f"{kind}: {_cleanup_inline_tex(value)}"
    if label.lower().startswith(("eq:", "equation:")):
        return f"Equation: {label}"
    return None


def _replace_cross_references(text: str, contexts: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        command = match.group(1).lower()
        labels = [part.strip() for part in match.group(2).split(",") if part.strip()]
        rendered = [contexts.get(label, label) for label in labels]
        if command in {"cref", "autoref", "eqref"}:
            return "[" + "; ".join(rendered) + "]"
        return "[" + "; ".join(rendered) + "]"

    return re.sub(r"\\(ref|eqref|autoref|cref|Cref)\s*\{([^}]*)\}", replace, text)


def _normalize_table_content(content: str) -> str:
    cleaned = content
    cleaned = re.sub(r"\\(?:toprule|midrule|bottomrule|hline|cline|cmidrule)\*?(?:\([^)]*\))?\s*\{[^}]*\}", "", cleaned)
    cleaned = re.sub(r"\\(?:toprule|midrule|bottomrule|hline)\b", "", cleaned)
    cleaned = _rewrite_latex_command(cleaned, "multicolumn", 3, lambda args: args[2])
    cleaned = _rewrite_latex_command(cleaned, "multirow", 3, lambda args: args[2])
    cleaned = _remove_latex_command_arguments(cleaned, "caption", 1)
    cleaned = re.sub(r"\\label\{[^}]*\}", "", cleaned)
    cleaned = re.sub(r"\\begin\{(?:tabular\*?|tabularx|longtable|array)\}(?:\[[^\]]*\])?(?:\{[^{}]*\}){0,3}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\\end\{(?:tabular\*?|tabularx|longtable|array)\}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r">\s*\{[^{}]*\}|<\s*\{[^{}]*\}|@\s*\{[^{}]*\}|[lcr]\s*\{[^{}]*\}|[pmbX]\s*\{[^{}]*\}", "", cleaned)
    cleaned = re.sub(r"\\(?:arraystretch|tabcolsep)\b\s*=?\s*[^&\\\n]*", "", cleaned)
    return cleaned


def _is_table_layout_cell(cell: str) -> bool:
    return bool(re.fullmatch(r"[lcr|@>{}<pmbxX.\s\\]+", cell.strip()))


def _extract_reference_entries(text: str, source_root: Path, main_tex: Path, state: _State) -> list[str]:
    entries: list[str] = []
    for block in _extract_legacy_reference_blocks(text):
        entries.extend(_parse_legacy_reference_entries(block))
    if entries:
        return entries
    for match in _THEBIB_ENV_RE.finditer(text):
        entries.extend(_parse_thebibliography_entries(match.group(1)))
    if entries:
        return entries
    resource_names = _collect_bibliography_resource_names(text)
    bib_files = _resolve_bibliography_files(source_root, resource_names)
    for bib_file in bib_files:
        entries.extend(_parse_bib_file(bib_file))
    if entries:
        return entries
    bbl_files = _resolve_bbl_files(source_root, main_tex, resource_names)
    for bbl_file in bbl_files:
        entries.extend(_parse_bbl_file(bbl_file))
    if not entries and (resource_names or "\\printbibliography" in text):
        state.warnings.append("Bibliography resources were referenced but no .bib or .bbl entries were found")
    return entries


def _collect_bibliography_resource_names(text: str) -> list[str]:
    names: list[str] = []
    for match in _BIB_RESOURCE_RE.finditer(text):
        for part in match.group(1).split(","):
            value = part.strip().strip('"').strip("'")
            if value:
                names.append(value)
    return names


def _resolve_bibliography_files(source_root: Path, names: list[str]) -> list[Path]:
    if not names:
        return sorted(path for path in source_root.rglob("*.bib") if path.is_file())
    resolved: list[Path] = []
    seen: set[Path] = set()
    for name in names:
        raw = Path(name)
        candidates = [raw] if raw.suffix else [raw.with_suffix(".bib"), raw]
        for candidate in candidates:
            direct = (source_root / candidate).resolve()
            if direct.is_file() and direct not in seen and _is_relative_to(direct, source_root.resolve()):
                resolved.append(direct)
                seen.add(direct)
                continue
            for matched in source_root.rglob(candidate.name):
                matched = matched.resolve()
                if matched.is_file() and matched not in seen and _is_relative_to(matched, source_root.resolve()):
                    resolved.append(matched)
                    seen.add(matched)
    return resolved


def _resolve_bbl_files(source_root: Path, main_tex: Path, names: list[str]) -> list[Path]:
    candidates: list[Path] = [main_tex.with_suffix(".bbl")]
    for name in names:
        raw = Path(name)
        candidates.append(raw if raw.suffix == ".bbl" else raw.with_suffix(".bbl"))
    resolved: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        direct = candidate if candidate.is_absolute() else (source_root / candidate)
        direct = direct.resolve()
        if direct.is_file() and direct not in seen and _is_relative_to(direct, source_root.resolve()):
            resolved.append(direct)
            seen.add(direct)
        for matched in source_root.rglob(candidate.name):
            matched = matched.resolve()
            if matched.is_file() and matched not in seen and _is_relative_to(matched, source_root.resolve()):
                resolved.append(matched)
                seen.add(matched)
    if not resolved:
        for matched in sorted(source_root.rglob("*.bbl")):
            matched = matched.resolve()
            if matched.is_file() and matched not in seen and _is_relative_to(matched, source_root.resolve()):
                resolved.append(matched)
                seen.add(matched)
    return resolved


def _extract_legacy_reference_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    for match in _LEGACY_REFERENCES_HEADING_RE.finditer(text):
        start = match.end()
        end_match = re.search(r"\\bye\b|\\end\b|\\centerline\s*\{\s*\\bf\s+[^}]+\}", text[start:], re.IGNORECASE)
        end = start + end_match.start() if end_match else len(text)
        blocks.append(text[start:end])
    return blocks


def _remove_legacy_reference_blocks(text: str) -> str:
    while True:
        match = _LEGACY_REFERENCES_HEADING_RE.search(text)
        if match is None:
            return text
        start = match.start()
        tail_start = match.end()
        end_match = re.search(r"\\bye\b|\\end\b|\\centerline\s*\{\s*\\bf\s+[^}]+\}", text[tail_start:], re.IGNORECASE)
        end = tail_start + end_match.start() if end_match else len(text)
        text = text[:start] + "\n\n" + text[end:]


def _parse_legacy_reference_entries(content: str) -> list[str]:
    entries: list[str] = []
    matches = list(re.finditer(r"\\ref\s*(\[[^\]\n]{1,30}\])", content))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        body = content[match.end():end]
        cleaned = _cleanup_inline_tex(body)
        cleaned = re.sub(r"^[-\d.\s]*pt\s*", "", cleaned).strip()
        if cleaned:
            entries.append(f"{match.group(1)} {cleaned}")
    if entries:
        return entries
    for part in re.split(r"(?=\[[A-Za-z][^\]\n]{1,30}\])", content):
        cleaned = _cleanup_inline_tex(part)
        cleaned = re.sub(r"^[-\d.\s]*pt\s*", "", cleaned).strip()
        if cleaned.startswith("[") and len(cleaned) > 20:
            entries.append(cleaned)
    if entries:
        return entries
    for part in re.split(r"\n\s*\n", content):
        cleaned = _cleanup_inline_tex(part)
        cleaned = re.sub(r"^[-\d.\s]*pt\s*", "", cleaned).strip()
        if _looks_like_plain_reference(cleaned):
            entries.append(cleaned)
    return entries


def _looks_like_plain_reference(text: str) -> bool:
    if len(text) < 30:
        return False
    if re.search(r"\b(?:19|20)\d{2}\b", text) is None:
        return False
    if re.search(r"^[A-Z][A-Za-zÀ-ÿ'\-]+", text):
        return True
    return bool(re.search(r"\b(?:doi|https?://|In:|Press|Journal|Proceedings|arXiv|Comput|Psychol|Soc|Conference|Review)\b", text, re.IGNORECASE))


def _parse_thebibliography_entries(content: str) -> list[str]:
    parts = re.split(r"\\bibitem(?:\[[^\]]*\])?\{[^}]+\}", content)
    return [cleaned for part in parts[1:] if (cleaned := _cleanup_inline_tex(part))]


def _parse_bbl_file(path: Path) -> list[str]:
    text = _read_text_file(path)
    entries = _parse_ios_bbl_entries(text)
    if entries:
        return entries
    entries = []
    for match in _THEBIB_ENV_RE.finditer(text):
        entries.extend(_parse_thebibliography_entries(match.group(1)))
    if entries:
        return entries
    entries = _parse_thebibliography_entries(text)
    if entries:
        return entries
    return _parse_biblatex_bbl_entries(text)


def _parse_ios_bbl_entries(text: str) -> list[str]:
    entries: list[str] = []
    parts = re.split(r"\\bibitem(?:\[[^\]]*\])?\{[^}]+\}", text)
    for part in parts[1:]:
        end = part.find(r"\endbibitem")
        block = part[:end] if end >= 0 else part
        rendered = _render_ios_bbl_entry(block)
        if rendered:
            entries.append(rendered)
    return entries


def _render_ios_bbl_entry(block: str) -> str | None:
    authors = _extract_ios_bbl_names(block, "bauthor")
    editors = _extract_ios_bbl_names(block, "beditor")
    title = _cleanup_inline_tex(_extract_command_argument(block, "batitle") or _extract_command_argument(block, "bctitle") or "")
    journal = _cleanup_inline_tex(_extract_command_argument(block, "bjtitle") or "")
    booktitle = _cleanup_inline_tex(_extract_command_argument(block, "bbtitle") or "")
    publisher = _cleanup_inline_tex(_extract_command_argument(block, "bpublisher") or "")
    year = _cleanup_inline_tex(_extract_command_argument(block, "byear") or "")
    volume = _cleanup_inline_tex(_extract_command_argument(block, "bvolume") or "")
    first_page = _cleanup_inline_tex(_extract_command_argument(block, "bfpage") or "")
    last_page = _cleanup_inline_tex(_extract_command_argument(block, "blpage") or "")
    pages = f"{first_page}-{last_page}" if first_page and last_page else first_page or last_page
    rendered = _join_authors(authors)
    if title:
        rendered = _append_reference_part(rendered, title, separator=", ")
    if journal:
        venue = journal
        if volume:
            venue += f" {volume}"
        if year:
            venue += f" ({year})"
        if pages:
            venue += f", {pages}"
        rendered = _append_reference_part(rendered, venue, separator=", ")
    elif booktitle:
        proceedings = f"in: {booktitle}"
        if editors:
            proceedings += f", {_join_authors(editors)}, eds"
        if publisher:
            proceedings += f", {publisher}"
        if year:
            proceedings += f", {year}"
        if pages:
            proceedings += f", pp. {pages}"
        rendered = _append_reference_part(rendered, proceedings, separator=", ")
    else:
        tail = ", ".join(part for part in [publisher, year, pages] if part)
        rendered = _append_reference_part(rendered, tail, separator=", ")
    return f"{rendered.strip(' ,.')} .".replace(" .", ".") if rendered.strip(" ,.") else None


def _extract_ios_bbl_names(block: str, command: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(rf"\\{re.escape(command)}\s*\{{", block, re.IGNORECASE):
        value, _ = _read_braced_value(block, match.end() - 1)
        cleaned = _cleanup_inline_tex(value)
        if cleaned:
            names.append(cleaned)
    return names


def _join_authors(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _append_reference_part(prefix: str, value: str, *, separator: str) -> str:
    value = value.strip(" ,.")
    if not value:
        return prefix
    return f"{prefix.rstrip(' ,.')}{separator}{value}" if prefix.strip() else value


def _parse_biblatex_bbl_entries(text: str) -> list[str]:
    entries: list[str] = []
    starts = list(re.finditer(r"\\entry\s*\{", text))
    for index, match in enumerate(starts):
        end_match = re.search(r"\\endentry\b", text[match.end():], re.IGNORECASE)
        if end_match is None:
            end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        else:
            end = match.end() + end_match.end()
        rendered = _render_biblatex_bbl_entry(text[match.start():end])
        if rendered:
            entries.append(rendered)
    return entries


def _render_biblatex_bbl_entry(block: str) -> str | None:
    authors = _extract_biblatex_bbl_authors(block)
    title = _cleanup_inline_tex(_extract_biblatex_bbl_field(block, "title") or "")
    year = _cleanup_inline_tex(_extract_biblatex_bbl_field(block, "year") or "")
    venue = _cleanup_inline_tex(
        _extract_biblatex_bbl_field(block, "journaltitle")
        or _extract_biblatex_bbl_field(block, "booktitle")
        or _extract_biblatex_bbl_field(block, "publisher")
        or ""
    )
    doi = _cleanup_inline_tex(_extract_biblatex_bbl_verb(block, "doi") or _extract_biblatex_bbl_field(block, "doi") or "")
    url = _cleanup_inline_tex(_extract_biblatex_bbl_verb(block, "url") or _extract_biblatex_bbl_field(block, "url") or "")
    parts = [", ".join(authors), title, venue, year, f"DOI: {doi}" if doi else "", url]
    rendered = ". ".join(part.strip(" .") for part in parts if part and part.strip(" ."))
    return f"{rendered}." if rendered else None


def _extract_biblatex_bbl_authors(block: str) -> list[str]:
    match = re.search(r"\\name\s*\{(?:author|editor)\}.*?(?=\\(?:list|strng|field|verb|endentry)\b)", block, re.IGNORECASE | re.DOTALL)
    if match is None:
        return []
    names_block = match.group(0)
    authors: list[str] = []
    cursor = 0
    while True:
        family_match = re.search(r"(?<![A-Za-z])family\s*=\s*\{", names_block[cursor:], re.IGNORECASE)
        if family_match is None:
            break
        family_start = cursor + family_match.end() - 1
        family, family_end = _read_braced_value(names_block, family_start)
        next_family = re.search(r"(?<![A-Za-z])family\s*=\s*\{", names_block[family_end:], re.IGNORECASE)
        search_end = family_end + next_family.start() if next_family else len(names_block)
        given_match = re.search(r"(?<![A-Za-z])given\s*=\s*\{", names_block[family_end:search_end], re.IGNORECASE)
        given = ""
        if given_match:
            given_start = family_end + given_match.end() - 1
            given, _ = _read_braced_value(names_block, given_start)
        name = _cleanup_inline_tex(" ".join(part for part in [given, family] if part.strip()))
        if name:
            authors.append(name)
        cursor = family_end
    return authors


def _extract_biblatex_bbl_field(block: str, field: str) -> str | None:
    match = re.search(rf"\\field\s*\{{{re.escape(field)}\}}\s*\{{", block, re.IGNORECASE)
    if match is None:
        return None
    value, _ = _read_braced_value(block, match.end() - 1)
    return value


def _extract_biblatex_bbl_verb(block: str, field: str) -> str | None:
    match = re.search(rf"\\verb\s*\{{{re.escape(field)}\}}\s*\\verb\s+(.*?)\s*\\endverb", block, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _parse_bib_file(path: Path) -> list[str]:
    text = _read_text_file(path)
    starts = list(re.finditer(r"@\w+\s*\{", text))
    entries: list[str] = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        rendered = _render_bib_entry(text[match.start():end])
        if rendered:
            entries.append(rendered)
    return entries


def _render_bib_entry(block: str) -> str | None:
    title = _cleanup_inline_tex(_extract_bib_field(block, "title") or "")
    authors_raw = _extract_bib_field(block, "author") or _extract_bib_field(block, "editor") or ""
    year = _cleanup_inline_tex(_extract_bib_field(block, "year") or "")
    venue = _cleanup_inline_tex(_extract_bib_field(block, "journal") or _extract_bib_field(block, "booktitle") or _extract_bib_field(block, "publisher") or "")
    doi = _cleanup_inline_tex(_extract_bib_field(block, "doi") or "")
    arxiv_id = _cleanup_inline_tex(_extract_bib_field(block, "eprint") or "")
    url = _cleanup_inline_tex(_extract_bib_field(block, "url") or "")
    authors = [_cleanup_inline_tex(author) for author in re.split(r"\band\b", authors_raw) if author.strip()]
    parts = [", ".join(authors), title, venue, year, f"DOI: {doi}" if doi else "", f"arXiv: {arxiv_id}" if arxiv_id else "", url]
    rendered = ". ".join(part.strip(" .") for part in parts if part and part.strip(" ."))
    return f"{rendered}." if rendered else None


def _extract_bib_field(block: str, field: str) -> str | None:
    match = re.search(rf"\b{re.escape(field)}\s*=\s*", block, re.IGNORECASE)
    if match is None:
        return None
    cursor = match.end()
    while cursor < len(block) and block[cursor].isspace():
        cursor += 1
    if cursor >= len(block):
        return None
    if block[cursor] == "{":
        value, _ = _read_braced_value(block, cursor)
        return value
    if block[cursor] == '"':
        end = cursor + 1
        while end < len(block):
            if block[end] == '"' and block[end - 1] != "\\":
                return block[cursor + 1:end]
            end += 1
        return block[cursor + 1:]
    end = block.find(",", cursor)
    return block[cursor:end if end >= 0 else len(block)].strip()


def _extract_title(text: str) -> str | None:
    legacy = _extract_legacy_title(text)
    if legacy:
        return legacy
    title = _extract_command_value(text, _TITLE_COMMAND_RE)
    if title and not _looks_like_image_only_title(title):
        return title
    running = _extract_command_value(text, _RUNNING_TITLE_RE)
    if running:
        return running
    return title if title and not _looks_like_image_only_title(title) else None


def _extract_legacy_title(text: str) -> str | None:
    for match in _LEGACY_TITLE_RE.finditer(text):
        if "\\def" in text[max(0, match.start() - 20):match.start()]:
            continue
        cursor = match.end() - 1
        args = []
        for _ in range(3):
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            if cursor >= len(text) or text[cursor] != "{":
                break
            value, cursor = _read_braced_value(text, cursor)
            args.append(value)
        if len(args) >= 2:
            return _cleanup_inline_tex(" ".join(args[:2]))
    return None


def _looks_like_image_only_title(title: str) -> bool:
    value = title.strip()
    return not value or "includegraphics" in value or re.fullmatch(r"[\s./_\-]+", value) is not None


def _extract_document_body(text: str) -> str:
    match = _DOCUMENT_ENV_RE.search(text)
    if match:
        return match.group(1)
    anchors = [
        _CENTERLINE_ABSTRACT_RE.search(text),
        re.search(r"\\(?:section|subsection|subsubsection)\*?\s*\{", text, re.IGNORECASE),
        re.search(r"\\centerline\s*\{\s*\\bf\s+[^}]+\}", text, re.IGNORECASE),
    ]
    starts = [anchor.start() for anchor in anchors if anchor]
    return text[min(starts):] if starts else text


def _remove_legacy_abstract_block(text: str) -> str:
    match = _CENTERLINE_ABSTRACT_RE.search(text)
    if match is None:
        return text
    start = match.start()
    end_start = match.end()
    end_match = re.search(r"\\(?:section|subsection|subsubsection)\*?\s*\{|\\centerline\s*\{\s*\\bf\s+[^}]+\}", text[end_start:], re.IGNORECASE)
    end = end_start + end_match.start() if end_match else min(len(text), end_start + 4000)
    return text[:start] + "\n\n" + text[end:]


def _extract_abstract(text: str) -> str | None:
    match = _ABSTRACT_ENV_RE.search(text)
    if match:
        return _cleanup_inline_tex(match.group(1))
    match = _ABSTRACT_COMMAND_RE.search(text)
    if match is not None:
        brace_index = text.find("{", match.start())
        value, _ = _read_braced_value(text, brace_index)
        cleaned = _cleanup_inline_tex(value)
        return cleaned or None
    match = _CENTERLINE_ABSTRACT_RE.search(text)
    if match is None:
        return None
    start = match.end()
    end_match = re.search(r"\\(?:section|subsection|subsubsection)\*?\s*\{|\\centerline\s*\{\s*\\bf\s+[^}]+\}", text[start:], re.IGNORECASE)
    end = start + end_match.start() if end_match else min(len(text), start + 4000)
    cleaned = _cleanup_inline_tex(text[start:end])
    return cleaned or None


def _remove_abstract_commands(text: str) -> str:
    text = _rewrite_latex_command(text, "abstract", 1, lambda _args: "\n\n")
    return _rewrite_latex_command(text, "setabstract", 1, lambda _args: "\n\n")


def _extract_command_value(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    brace_index = text.find("{", match.start())
    value, _ = _read_braced_value(text, brace_index)
    cleaned = _cleanup_inline_tex(value)
    return cleaned or None


def _replace_heading_commands(text: str) -> str:
    result = text
    for command, prefix in _HEADING_COMMANDS:
        pattern = re.compile(rf"\\{command}\*?(?:\[[^\]]*\])?\{{((?:[^{{}}]|\{{[^{{}}]*\}})*)\}}", re.IGNORECASE)
        result = pattern.sub(lambda match: f"\n\n{prefix} {_cleanup_inline_tex(match.group(1)).strip()}\n\n", result)
    return result


def _cleanup_structured_tex_body(text: str) -> str:
    protected, replacements = _protect_inline_math(text)
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", protected) if block.strip()]
    cleaned = []
    for block in blocks:
        if block.startswith("#") or block.startswith(("Figure:", "Table:", "![", "|")):
            cleaned.append(_restore_inline_math(block, replacements))
        elif re.search(r"(?m)^\s*(?:[-*]|\d+\.)\s+", block):
            lines = []
            for line in block.splitlines():
                stripped = line.strip()
                if stripped.startswith(("- ", "* ")) or re.match(r"\d+\.\s+", stripped):
                    lines.append(stripped)
                elif stripped:
                    lines.append(_cleanup_inline_tex(stripped))
            cleaned.append(_restore_inline_math("\n".join(lines), replacements))
        else:
            value = _cleanup_inline_tex(block)
            if value and not _is_layout_artifact(value):
                cleaned.append(_restore_inline_math(value, replacements))
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(cleaned)).strip()


def _cleanup_inline_tex(text: str) -> str:
    protected, replacements = _protect_inline_math(text)
    protected = protected.replace("\r", " ").replace("\n", " ").replace("~", " ")
    protected = re.sub(r"\\(?:v|h)space\*?\s*\{[^{}]*\}", " ", protected)
    protected = re.sub(r"\\(?:newblock|medskip|bigskip|smallskip|smskip|pn|noindent|nobreak|goodbreak|par)\b", " ", protected)
    protected = re.sub(r"\\(?:b(?:author|title|jtitle|volume|year|fpage|lpage|publisher|booktitle|chapter|comment|otherref|article|book|chapter)|binits|bsnm|fnms|snm|inits|orgname|cny|ead)\s*", " ", protected)
    protected = re.sub(r"\\\\\s*(?:\[[^\]]*\])?", "\n", protected)
    protected = _remove_latex_command_arguments(protected, "fontsize", 2)
    protected = _unwrap_latex_command_argument(protected, "selectfont", 0)
    protected = _unwrap_latex_command_argument(protected, "raisebox", 2)
    protected = _remove_latex_command_arguments(protected, "includegraphics", 1)
    protected = _normalize_latex_accents(protected)
    protected = protected.replace(r"\&", "&").replace(r"\%", "%").replace(r"\_", "_").replace(r"\#", "#")
    protected = re.sub(r"\\href\s*\{([^}]*)\}\s*\{([^}]*)\}", r"\2 (\1)", protected)
    protected = re.sub(r"\\url\s*\{([^}]*)\}", r"\1", protected)
    protected = re.sub(r"\\(?:cite\w*|citep|citet|parencite|autocite|ref|eqref|autoref|cref|Cref|pageref)\s*(?:\[[^\]]*\])?\{([^}]*)\}", r"[\1]", protected)
    protected = re.sub(r"\\label\s*\{[^}]*\}", " ", protected)
    protected = re.sub(r"\\footnote\s*\{([^}]*)\}", r" (\1)", protected)
    for _ in range(8):
        previous = protected
        protected = re.sub(rf"\\(?:{_INLINE_COMMANDS})\*?\s*\{{([^{{}}]*)\}}", lambda match: match.group(1), protected)
        if protected == previous:
            break
    protected = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", protected)
    protected = re.sub(r"([A-Za-zÀ-ÿ])\{([A-Za-zÀ-ÿ])\}", r"\1\2", protected)
    protected = protected.replace("{", " ").replace("}", " ").replace("$", " ")
    protected = re.sub(r"\\\\", "\n", protected)
    protected = re.sub(r"\s+", " ", protected).strip()
    protected = re.sub(r"\s+([.,;:!?])", r"\1", protected)
    return _restore_inline_math(protected, replacements)


def _normalize_latex_accents(text: str) -> str:
    replacements = {
        "\\'a": "á", "\\'e": "é", "\\'i": "í", "\\'o": "ó", "\\'u": "ú", "\\'y": "ý",
        "\\'A": "Á", "\\'E": "É", "\\'I": "Í", "\\'O": "Ó", "\\'U": "Ú", "\\'Y": "Ý",
        '\\"a': "ä", '\\"e': "ë", '\\"i': "ï", '\\"o': "ö", '\\"u': "ü",
        '\\"A': "Ä", '\\"E': "Ë", '\\"I': "Ï", '\\"O': "Ö", '\\"U': "Ü",
        "\\`a": "à", "\\`e": "è", "\\`i": "ì", "\\`o": "ò", "\\`u": "ù",
        "\\`A": "À", "\\`E": "È", "\\`I": "Ì", "\\`O": "Ò", "\\`U": "Ù",
        "\\^a": "â", "\\^e": "ê", "\\^i": "î", "\\^o": "ô", "\\^u": "û",
        "\\~n": "ñ", "\\~N": "Ñ", "\\c c": "ç", "\\c C": "Ç",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\\([`'\"^~=.])\s*\{([A-Za-z])\}", lambda match: _normalize_latex_accents("\\" + match.group(1) + match.group(2)), text)
    text = re.sub(r"\\([`'\"^~=.])\s+([A-Za-z])", lambda match: _normalize_latex_accents("\\" + match.group(1) + match.group(2)), text)
    return text


def _protect_inline_math(text: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = f"TEX2MDMATH{len(replacements)}"
        content = match.group(1) or match.group(2) or ""
        replacements[token] = f"${content.strip()}$"
        return token

    return _INLINE_MATH_RE.sub(replace, text), replacements


def _restore_inline_math(text: str, replacements: dict[str, str]) -> str:
    for token in sorted(replacements, key=len, reverse=True):
        text = text.replace(token, replacements[token])
    return text


def _render_display_math(content: str) -> str:
    return f"\n\n$$\n{content.strip()}\n$$\n\n" if content.strip() else "\n\n"


def _collect_simple_macros(text: str, state: _State) -> None:
    for match in _SIMPLE_MACRO_RE.finditer(text):
        name = match.group("def_name") or match.group("new_name")
        value = match.group("def_value") or match.group("new_value") or ""
        if name and value.strip():
            state.simple_macros[name.strip()] = value.strip()


def _expand_simple_macros(text: str, state: _State) -> str:
    expanded = text
    for _ in range(4):
        previous = expanded
        for name, value in sorted(state.simple_macros.items(), key=lambda item: len(item[0]), reverse=True):
            expanded = re.sub(rf"\\{re.escape(name)}\b", lambda _match, replacement=value: replacement, expanded)
        expanded = expanded.replace(r"\xspace", " ")
        if expanded == previous:
            break
    return expanded


def _render_list_environments(text: str) -> str:
    pattern = re.compile(r"\\begin\{(itemize|enumerate|description)\}(.*?)\\end\{\1\}", re.IGNORECASE | re.DOTALL)

    def replace(match: re.Match[str]) -> str:
        kind = match.group(1).lower()
        content = match.group(2)
        items = _split_latex_items(content)
        lines: list[str] = []
        for index, (label, item) in enumerate(items, 1):
            body = _cleanup_inline_tex(item)
            if not body:
                continue
            if kind == "enumerate":
                lines.append(f"{index}. {body}")
            elif kind == "description" and label:
                lines.append(f"- **{_cleanup_inline_tex(label)}:** {body}")
            else:
                prefix = f"**{_cleanup_inline_tex(label)}:** " if label else ""
                lines.append(f"- {prefix}{body}")
        return "\n\n" + "\n".join(lines) + "\n\n"

    previous = None
    while previous != text:
        previous = text
        text = pattern.sub(replace, text)
    text = re.sub(r"\\item\s*(?:\[([^\]]*)\])?", lambda match: f"\n- **{_cleanup_inline_tex(match.group(1))}:** " if match.group(1) else "\n- ", text)
    return text


def _split_latex_items(content: str) -> list[tuple[str | None, str]]:
    matches = list(re.finditer(r"\\item\s*(?:\[([^\]]*)\])?", content))
    items: list[tuple[str | None, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        items.append((match.group(1), content[match.end():end].strip()))
    return items


def _render_statement_environments(text: str) -> str:
    environments = "theorem|lemma|proposition|corollary|definition|assumption|remark|proof|example|claim"
    pattern = re.compile(rf"\\begin\{{({environments})\}}(?:\[([^\]]*)\])?(.*?)\\end\{{\1\}}", re.IGNORECASE | re.DOTALL)

    def replace(match: re.Match[str]) -> str:
        name = match.group(1).capitalize()
        title = _cleanup_inline_tex(match.group(2) or "")
        body = _cleanup_structured_tex_body(match.group(3))
        heading = f"**{name} ({title}).**" if title else f"**{name}.**"
        return f"\n\n{heading}\n\n{body}\n\n"

    previous = None
    while previous != text:
        previous = text
        text = pattern.sub(replace, text)
    return text


def _unwrap_passthrough_environments(text: str) -> str:
    environments = "center|tcolorbox|wrapfigure|quote|quotation|small|scriptsize|minipage|subfigure|subtable"
    text = re.sub(rf"\\begin\{{(?:{environments})\}}(?:\[[^\]]*\])?", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(rf"\\end\{{(?:{environments})\}}", "\n\n", text, flags=re.IGNORECASE)
    return text


def _drop_latex_environment_options(text: str) -> str:
    lines = text.splitlines()
    cleaned: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == "[" or (stripped.startswith("[") and any(token in stripped for token in ("colback", "colframe", "boxrule", "enhanced"))):
            skipping = True
            if stripped.endswith("]"):
                skipping = False
            continue
        if skipping:
            if stripped.endswith("]"):
                skipping = False
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _extract_command_argument(text: str, command: str) -> str | None:
    match = re.search(rf"\\{re.escape(command)}\*?(?:\[[^\]]*\])?\s*\{{", text, re.IGNORECASE)
    if match is None:
        return None
    value, _ = _read_braced_value(text, text.find("{", match.start()))
    return value.strip() or None


def _remove_latex_command_arguments(text: str, command: str, required_args: int) -> str:
    return _rewrite_latex_command(text, command, required_args, lambda _args: " ")


def _unwrap_latex_command_argument(text: str, command: str, required_args: int) -> str:
    return _rewrite_latex_command(text, command, required_args, lambda args: args[-1] if args else " ")


def _rewrite_latex_command(text: str, command: str, required_args: int, render) -> str:
    pattern = re.compile(rf"\\{re.escape(command)}\*?(?:\[[^\]]*\])?", re.IGNORECASE)
    pieces: list[str] = []
    cursor = 0
    while True:
        match = pattern.search(text, cursor)
        if match is None:
            pieces.append(text[cursor:])
            break
        args: list[str] = []
        end = match.end()
        for _ in range(required_args):
            while end < len(text) and text[end].isspace():
                end += 1
            if end >= len(text) or text[end] != "{":
                break
            value, end = _read_braced_value(text, end)
            args.append(value)
        if len(args) != required_args:
            pieces.append(text[cursor:match.end()])
            cursor = match.end()
            continue
        pieces.append(text[cursor:match.start()])
        pieces.append(str(render(args)))
        cursor = end
    return "".join(pieces)


def _read_braced_value(text: str, opening_brace: int) -> tuple[str, int]:
    depth = 0
    collected: list[str] = []
    cursor = opening_brace
    while cursor < len(text):
        char = text[cursor]
        if char == "{":
            depth += 1
            if depth > 1:
                collected.append(char)
        elif char == "}":
            depth -= 1
            if depth == 0:
                return "".join(collected), cursor + 1
            if depth > 0:
                collected.append(char)
        elif depth > 0:
            collected.append(char)
        cursor += 1
    return "".join(collected), cursor


def _read_text_file(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _strip_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        cursor = 0
        while True:
            index = line.find("%", cursor)
            if index < 0:
                lines.append(line)
                break
            backslashes = 0
            probe = index - 1
            while probe >= 0 and line[probe] == "\\":
                backslashes += 1
                probe -= 1
            if backslashes % 2 == 0:
                lines.append(line[:index])
                break
            cursor = index + 1
    return "\n".join(lines)


def _clean_markdown_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACE_RE.sub(" ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def _is_layout_artifact(text: str) -> bool:
    value = text.strip()
    return bool(re.fullmatch(r"-?\d+", value)) or value.casefold() in {"table of contents", "appendix"}


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _find_case_insensitive_path(root: Path, relative: Path, source_root: Path) -> Path | None:
    parts = relative.parts
    candidates = [root.resolve()]
    for part in parts:
        next_candidates: list[Path] = []
        for candidate in candidates:
            if not candidate.is_dir():
                continue
            try:
                children = list(candidate.iterdir())
            except OSError:
                continue
            for child in children:
                if child.name.casefold() == part.casefold():
                    next_candidates.append(child)
        candidates = next_candidates
        if not candidates:
            return None
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and _is_relative_to(resolved, source_root.resolve()):
            return resolved
    return None



def _markdown_to_plain(markdown: str) -> str:
    text = re.sub(r"^\s*#+\s*", "", markdown, flags=re.MULTILINE)
    text = re.sub(r"^\s*-\s*", "", text, flags=re.MULTILINE)
    return text.strip()
