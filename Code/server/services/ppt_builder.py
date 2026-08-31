"""Small deterministic PPTX renderer for reviewed progress reports.

The report agent owns facts and evidence. This renderer only lays out the
already-reviewed Markdown, so it cannot introduce new research claims.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt


def parse_sections(markdown: str, max_sections: int) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = "执行摘要"
    current_lines: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            continue
        if line.startswith("## ") or line.startswith("### "):
            if current_lines:
                sections.append((current_title, current_lines))
            current_title = re.sub(r"^#{2,3}\s+", "", line)
            current_lines = []
            continue
        if line.startswith("- ") or re.match(r"^\d+\.\s", line):
            current_lines.append(re.sub(r"^(?:- |\d+\.\s+)", "", line))
        elif len(current_lines) < 5:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, current_lines))
    return sections[:max_sections]


def add_text(slide, text: str, left: float, top: float, width: float, height: float, size: int, color: RGBColor, bold: bool = False) -> None:
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.LEFT
    run = paragraph.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def main() -> int:
    if len(sys.argv) != 2:
        print("output path required", file=sys.stderr)
        return 2
    payload = json.loads(sys.stdin.read().lstrip("\ufeff"))
    output = Path(sys.argv[1])
    title = str(payload.get("title") or "科研进展报告")
    slide_count = max(3, min(20, int(payload.get("slideCount") or 8)))
    sections = parse_sections(str(payload.get("markdown") or ""), slide_count - 1)
    refs = [str(item) for item in payload.get("evidenceRefs") or [] if str(item)]

    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    blank = presentation.slide_layouts[6]
    navy = RGBColor(30, 41, 59)
    muted = RGBColor(100, 116, 139)
    accent = RGBColor(79, 70, 229)
    white = RGBColor(255, 255, 255)

    cover = presentation.slides.add_slide(blank)
    cover.background.fill.solid()
    cover.background.fill.fore_color.rgb = navy
    add_text(cover, title, 0.8, 1.8, 11.7, 1.1, 34, white, True)
    add_text(cover, "基于已审核科研记录生成 · 证据引用见各页底部", 0.85, 3.2, 10.5, 0.5, 16, RGBColor(203, 213, 225))

    for section_title, lines in sections:
        slide = presentation.slides.add_slide(blank)
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = white
        add_text(slide, section_title, 0.7, 0.55, 11.8, 0.7, 26, navy, True)
        y = 1.55
        for line in lines[:8]:
            add_text(slide, f"• {line}", 0.9, y, 11.4, 0.48, 17, navy)
            y += 0.62
        add_text(slide, "科研报告 · PAPERCLAW", 0.75, 7.05, 5, 0.25, 9, muted)
        if refs:
            add_text(slide, "证据：" + "、".join(refs[:4]), 6.2, 7.05, 6.3, 0.25, 8, accent)

    presentation.save(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
