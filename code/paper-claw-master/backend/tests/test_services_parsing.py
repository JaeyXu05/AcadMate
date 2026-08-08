from __future__ import annotations

import tarfile
from pathlib import Path
from types import SimpleNamespace

from backend.db.models import Paper, ParsedDocument, ParserEvent
from backend.db.types import ArtifactKind, ArtifactStatus, ParseJobStatus, ParseStrategy, PaperArtifactRole, StorageBackend
from backend.integrations.parsers import LlamaParseConfig, LlamaParseParser, LocalOCRConfig, LocalOCRParser, TexSourceParser
from backend.schemas import ParsedDocumentPayload
from backend.services.parsing import ParseChainService
from backend.services.storage import ArtifactStorageService
from backend.integrations.storage import LocalStorage


class FakeParser:
    def __init__(self, strategy: str, parser_kind: str = "fake", fail: bool = False) -> None:
        self.strategy = strategy
        self.parser_kind = parser_kind
        self.fail = fail
        self.received_warnings: list[str] | None = None

    def parse(self, artifact_path: Path, warnings: list[str] | None = None) -> ParsedDocumentPayload:
        self.received_warnings = warnings
        if self.fail:
            raise RuntimeError(f"{self.strategy} failed")
        return ParsedDocumentPayload(
            strategy=self.strategy,
            parser_kind=self.parser_kind,
            plain_text=f"{self.strategy} text",
            markdown_content=f"# {self.strategy}",
            json_content={"artifact_path": str(artifact_path)},
            warnings=warnings or [],
        )


def make_storage(session, tmp_path):
    root = tmp_path / "data" / "files"
    return root, ArtifactStorageService(session, LocalStorage(root))


def make_paper(session, title="Paper"):
    paper = Paper(title=title)
    session.add(paper)
    session.commit()
    return paper


def test_tex_source_parser_extracts_markdown(tmp_path):
    tex = tmp_path / "main.tex"
    tex.write_text(r"""
\documentclass{article}
\begin{document}
\title{A Paper}
\section{Abstract}
This is \textbf{important} text.
\end{document}
""", encoding="utf-8")

    payload = TexSourceParser().parse(tex)

    assert payload.strategy == ParseStrategy.tex.value
    assert "## Abstract" in payload.markdown_content
    assert "important" in payload.plain_text


def test_tex_source_parser_expands_includes_and_bibliography(tmp_path):
    sections = tmp_path / "sections"
    sections.mkdir()
    (tmp_path / "main.tex").write_text(
        r"""
\documentclass{article}
\title{Included Paper}
\begin{document}
\maketitle
\begin{abstract}A structured abstract.\end{abstract}
\input{sections/intro}
\bibliography{refs}
\end{document}
""",
        encoding="utf-8",
    )
    (sections / "intro.tex").write_text(r"\section{Introduction}Included body text.", encoding="utf-8")
    (tmp_path / "refs.bib").write_text(
        r"""
@inproceedings{smith2024,
  author = {Alice Smith and Bob Jones},
  title = {A Referenced Paper},
  booktitle = {Conference on Testing},
  year = {2024},
  doi = {10.1000/test}
}
""",
        encoding="utf-8",
    )

    payload = TexSourceParser().parse(tmp_path / "main.tex")

    assert "# Included Paper" in payload.markdown_content
    assert "## Abstract" in payload.markdown_content
    assert "## Introduction" in payload.markdown_content
    assert "Included body text" in payload.markdown_content
    assert "## References" in payload.markdown_content
    assert "A Referenced Paper" in payload.markdown_content
    assert payload.json_content["used_files"] == ["main.tex", "sections/intro.tex"]
    assert payload.json_content["references_count"] == 1
    assert len(payload.json_content["references"]) == 1
    assert "A Referenced Paper" in payload.json_content["references"][0]
    assert "10.1000/test" in payload.json_content["references"][0]


def test_tex_source_parser_prefers_real_main_over_acl_lualatex_template(tmp_path):
    source = tmp_path / "source"
    sections = source / "latex" / "tex"
    sections.mkdir(parents=True)
    (source / "main_arxiv.tex").write_text(
        "\n".join(
            [
                r"\documentclass[11pt]{article}",
                "% " + "long preamble filler " * 80,
                r"\title{HyLaT: Efficient Multi-Agent Communication via \\ Hybrid Latent-Text Protocol}",
                r"\begin{document}",
                r"\maketitle",
                r"\begin{abstract}Real abstract.\end{abstract}",
                r"\input{latex/tex/1_intro}",
                r"\end{document}",
            ]
        ),
        encoding="utf-8",
    )
    (sections / "1_intro.tex").write_text(r"\section{Introduction}Real paper body.", encoding="utf-8")
    (source / "acl_lualatex.tex").write_text(
        r"""
\documentclass[11pt]{article}
\title{LuaLaTeX and XeLaTeX Template for *ACL Style Files}
\begin{document}
\maketitle
\section{Introduction}
Please see the general instructions in the ACL template.
\section{Example Appendix}
This is an appendix.
\end{document}
""",
        encoding="utf-8",
    )
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(source.rglob("*")):
            tar.add(path, arcname=path.relative_to(source))

    payload = TexSourceParser().parse(archive)

    assert payload.json_content["main_tex"] == "main_arxiv.tex"
    assert payload.json_content["used_files"] == ["main_arxiv.tex", "latex/tex/1_intro.tex"]
    assert "# HyLaT: Efficient Multi-Agent Communication via" in payload.markdown_content
    assert "Real paper body." in payload.markdown_content
    assert "LuaLaTeX and XeLaTeX Template" not in payload.markdown_content


def test_tex_source_parser_preserves_sections_after_display_math_and_layout_envs(tmp_path):
    tex = tmp_path / "main.tex"
    tex.write_text(
        r"""
\documentclass{article}
\title{Latent Test}
\newcommand{\ours}{LatentMAS\xspace}
\begin{document}
\begin{abstract}
{\fontsize{10pt}{10pt} \selectfont \raisebox{-0.1em}{\includegraphics[height=1em]{logo.png}} Code: \href{https://example.test}{https://example.test}}\\[0.6em]
Abstract body with 4$\times$ speedup.
\end{abstract}
\begin{tcolorbox}[
  enhanced,
  colback=white,
  boxrule=.7pt
]
\begin{center}
\textbf{Can multi-agent systems achieve pure latent collaboration?}
\end{center}
\end{tcolorbox}
\section{Preliminary}
Let $W_a$ align $h$ to $e$.
\begin{equation}
W_a = (W_\text{out}^\top W_\text{out} + \lambda I)^{-1} W_\text{out}^\top W_\text{in}
\end{equation}
\section{Method}
\ours keeps the method body after display math.
\section{Experiments}
Experiment body.
\section{Conclusion}
Conclusion body.
\end{document}
""",
        encoding="utf-8",
    )

    payload = TexSourceParser().parse(tex)

    assert "PAPERCLAWMATH" not in payload.markdown_content
    assert "colback" not in payload.markdown_content
    assert "10pt" not in payload.markdown_content
    assert "[0.6em]" not in payload.markdown_content
    assert "## Method" in payload.markdown_content
    assert "## Experiments" in payload.markdown_content
    assert "## Conclusion" in payload.markdown_content
    assert "$W_a$" in payload.markdown_content
    assert "LatentMAS keeps the method body after display math." in payload.markdown_content


def test_tex_source_parser_warns_on_missing_include(tmp_path):
    tex = tmp_path / "main.tex"
    tex.write_text(r"\documentclass{article}\begin{document}\input{missing}\section{Body}Text\end{document}", encoding="utf-8")

    payload = TexSourceParser().parse(tex)

    assert "Missing include file: missing" in payload.warnings
    assert payload.json_content["missing_includes"] == ["missing"]
    assert "## Body" in payload.markdown_content


def test_tex_source_parser_skips_unsafe_tar_member(tmp_path):
    archive = tmp_path / "source.tar"
    safe = tmp_path / "safe.tex"
    safe.write_text(r"\documentclass{article}\begin{document}\section{Safe}Text\end{document}", encoding="utf-8")
    unsafe = tmp_path / "unsafe.tex"
    unsafe.write_text("unsafe", encoding="utf-8")
    with tarfile.open(archive, "w") as tar:
        tar.add(safe, arcname="main.tex")
        tar.add(unsafe, arcname="../unsafe.tex")

    payload = TexSourceParser().parse(archive)

    assert "Skipped unsafe archive member: ../unsafe.tex" in payload.warnings
    assert "## Safe" in payload.markdown_content


def test_plan_parse_chain_prefers_tex_source_over_pdf(session, tmp_path):
    paper = make_paper(session)
    root, storage = make_storage(session, tmp_path)
    source = tmp_path / "source.tex"
    source.write_text("\\begin{document}TeX\\end{document}")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")
    storage.register_source_artifact(paper.id, source)
    storage.register_local_pdf(paper.id, pdf)

    plan = ParseChainService(
        session,
        {ParseStrategy.tex.value: FakeParser(ParseStrategy.tex.value), ParseStrategy.local_ocr.value: FakeParser(ParseStrategy.local_ocr.value)},
        root,
    ).plan_parse_chain(paper.id)

    assert plan.selected_strategy == ParseStrategy.tex.value


def test_run_parse_chain_persists_events_and_document(session, tmp_path):
    paper = make_paper(session)
    root, storage = make_storage(session, tmp_path)
    source = tmp_path / "source.tex"
    source.write_text("\\begin{document}TeX\\end{document}")
    storage.register_source_artifact(paper.id, source)

    job = ParseChainService(session, {ParseStrategy.tex.value: FakeParser(ParseStrategy.tex.value, "tex_fake")}, root).run_parse_chain(paper.id)

    assert job.status == ParseJobStatus.succeeded.value
    assert job.strategy == ParseStrategy.tex.value
    document = session.query(ParsedDocument).one()
    assert document.parser_kind == "tex_fake"
    assert [event.sequence for event in session.query(ParserEvent).order_by(ParserEvent.sequence)] == [1, 2, 3]


def test_local_ocr_selected_when_only_pdf_and_parser_exists(session, tmp_path):
    paper = make_paper(session)
    root, storage = make_storage(session, tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")
    storage.register_local_pdf(paper.id, pdf)

    plan = ParseChainService(session, {ParseStrategy.local_ocr.value: FakeParser(ParseStrategy.local_ocr.value)}, root).plan_parse_chain(paper.id)

    assert plan.selected_strategy == ParseStrategy.local_ocr.value


def test_llama_parse_selected_when_local_ocr_missing(session, tmp_path):
    paper = make_paper(session)
    root, storage = make_storage(session, tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")
    storage.register_local_pdf(paper.id, pdf)

    plan = ParseChainService(session, {ParseStrategy.llama_parse.value: FakeParser(ParseStrategy.llama_parse.value)}, root).plan_parse_chain(paper.id)

    assert plan.selected_strategy == ParseStrategy.llama_parse.value


def test_unavailable_when_no_parseable_artifact_or_backend(session):
    paper = make_paper(session)

    job = ParseChainService(session).run_parse_chain(paper.id)

    assert job.status == ParseJobStatus.failed.value
    assert job.strategy == ParseStrategy.unavailable.value
    assert "No parseable" in job.error_message


def test_failed_earlier_strategy_warning_reaches_later_success(session, tmp_path):
    paper = make_paper(session)
    root, storage = make_storage(session, tmp_path)
    source = tmp_path / "source.tex"
    source.write_text("\\begin{document}TeX\\end{document}")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")
    storage.register_source_artifact(paper.id, source)
    storage.register_local_pdf(paper.id, pdf)
    local_ocr = FakeParser(ParseStrategy.local_ocr.value, "ocr_fake")

    job = ParseChainService(
        session,
        {ParseStrategy.tex.value: FakeParser(ParseStrategy.tex.value, fail=True), ParseStrategy.local_ocr.value: local_ocr},
        root,
    ).run_parse_chain(paper.id)

    assert job.status == ParseJobStatus.succeeded.value
    assert local_ocr.received_warnings == ["tex: tex failed"]
    assert session.query(ParsedDocument).one().json_content["warnings"] == ["tex: tex failed"]


def test_local_ocr_parser_uses_openai_compatible_multimodal_client(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="<h1>Title</h1><p>Body</p>"))],
        usage={"total_tokens": 3},
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
    pixmap = SimpleNamespace(tobytes=lambda format: b"png")
    page = SimpleNamespace(get_pixmap=lambda dpi: pixmap)

    class FakeDocument:
        page_count = 1

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def load_page(self, index):
            return page

    fitz = SimpleNamespace(open=lambda path: FakeDocument())

    payload = LocalOCRParser(LocalOCRConfig(base_url="http://local", model="ocr"), client=client, fitz_module=fitz).parse(pdf)

    assert payload.strategy == ParseStrategy.local_ocr.value
    assert payload.json_content["page_count"] == 1
    assert "Title" in payload.markdown_content


def test_llama_parse_parser_uses_injected_parser(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")
    parser = SimpleNamespace(load_data=lambda path: [SimpleNamespace(text="# Parsed")])

    payload = LlamaParseParser(LlamaParseConfig(api_key="test"), parser=parser).parse(pdf)

    assert payload.strategy == ParseStrategy.llama_parse.value
    assert payload.markdown_content == "# Parsed"
