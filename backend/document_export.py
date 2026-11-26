"""Export grounded case action plans as Word documents."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


FONT_NAME = "Noto Sans Bengali"
MAX_EXPORT_CHARACTERS = 200_000


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _set_run_font(run: Any) -> None:
    run.font.name = FONT_NAME
    run_properties = run._element.get_or_add_rPr()
    fonts = run_properties.rFonts
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        run_properties.insert(0, fonts)
    for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{attribute}"), FONT_NAME)


def _add_paragraph(document: Document, text: str, style: str | None = None) -> None:
    paragraph = document.add_paragraph(style=style)
    run = paragraph.add_run(text)
    _set_run_font(run)


def _add_heading(document: Document, text: str, level: int = 1) -> None:
    paragraph = document.add_heading(level=level)
    run = paragraph.add_run(text)
    _set_run_font(run)


def build_case_plan_docx(query: str, analysis: dict[str, Any]) -> bytes:
    steps = analysis.get("step_by_step_plan")
    if not isinstance(steps, list) or not steps:
        raise ValueError("এই উত্তরে ডাউনলোড করার মতো পদক্ষেপ পরিকল্পনা নেই।")

    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)
    document.core_properties.title = "আইনসাথী — ধাপে ধাপে আইনি করণীয়"
    document.core_properties.subject = _text(analysis.get("act_name"))

    normal_style = document.styles["Normal"]
    normal_style.font.name = FONT_NAME
    normal_style.font.size = Pt(11)
    normal_properties = normal_style._element.get_or_add_rPr()
    normal_fonts = normal_properties.rFonts
    if normal_fonts is None:
        normal_fonts = OxmlElement("w:rFonts")
        normal_properties.insert(0, normal_fonts)
    for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
        normal_fonts.set(qn(f"w:{attribute}"), FONT_NAME)

    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = heading.add_run("আইনসাথী\nধাপে ধাপে আইনি করণীয়")
    _set_run_font(title_run)
    title_run.bold = True
    title_run.font.size = Pt(20)
    title_run.font.color.rgb = RGBColor(20, 75, 67)

    _add_paragraph(document, f"প্রশ্ন: {query}")
    _add_paragraph(
        document,
        f"প্রযোজ্য আইন: {_text(analysis.get('act_name')) or _text(analysis.get('detected_domain_bn')) or 'সংকলিত আইন'}",
    )
    _add_paragraph(
        document,
        f"মামলার ধরন: {_text(analysis.get('case_type_bn')) or 'প্রতিকার যাচাই'}",
    )

    source_summary = analysis.get("source_summary")
    if isinstance(source_summary, list) and source_summary:
        _add_heading(document, "আপলোডকৃত PDF থেকে প্রাসঙ্গিক অংশ")
        for excerpt in source_summary:
            if not isinstance(excerpt, dict):
                continue
            citation = _text(excerpt.get("citation")) or (
                f"পৃষ্ঠা নং {excerpt.get('page_number') or '—'}"
            )
            _add_paragraph(document, citation, "Heading 3")
            _add_paragraph(document, _text(excerpt.get("excerpt")))

    _add_heading(document, "ধাপে ধাপে করণীয়")
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        step_number = step.get("step_number") or index
        title = _text(step.get("title")) or "পরবর্তী পদক্ষেপ"
        _add_heading(document, f"ধাপ {step_number}: {title}", level=2)
        _add_paragraph(document, _text(step.get("description")))
        references = step.get("statute_ref")
        if isinstance(references, str):
            references = [references]
        if isinstance(references, list):
            refs = [reference for reference in references if isinstance(reference, str) and reference.strip()]
            if refs:
                _add_paragraph(document, f"প্রাসঙ্গিক ধারা: {', '.join(refs)}")

    required_documents = analysis.get("required_documents")
    if isinstance(required_documents, list) and required_documents:
        _add_heading(document, "প্রয়োজনীয় কাগজপত্র")
        for item in required_documents:
            if isinstance(item, str) and item.strip():
                _add_paragraph(document, f"• {item.strip()}")

    citations = analysis.get("statute_citations")
    if isinstance(citations, list) and citations:
        _add_heading(document, "যাচাইকৃত আইনি ধারা")
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            section_number = _text(citation.get("section_number")) or "—"
            section_title = _text(citation.get("section_title")) or "আইনি বিধান"
            _add_heading(document, f"ধারা {section_number}: {section_title}", level=2)
            status = _text(citation.get("legal_status"))
            if status:
                _add_paragraph(document, f"আইনি অবস্থা: {status}")
            content = _text(citation.get("content"))
            if content:
                _add_paragraph(document, content)

    disclaimer = _text(analysis.get("disclaimer"))
    if disclaimer:
        _add_heading(document, "গুরুত্বপূর্ণ নোট")
        _add_paragraph(document, disclaimer)

    characters = sum(len(paragraph.text) for paragraph in document.paragraphs)
    if characters > MAX_EXPORT_CHARACTERS:
        raise ValueError("ডকুমেন্টটি রপ্তানির জন্য অতিরিক্ত বড়।")

    output = BytesIO()
    document.save(output)
    return output.getvalue()
