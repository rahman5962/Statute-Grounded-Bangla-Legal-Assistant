from __future__ import annotations

from io import BytesIO
import sys
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from document_export import build_case_plan_docx


def test_case_plan_docx_contains_grounded_steps_and_source_citations() -> None:
    analysis = {
        "act_name": "ভোক্তা-অধিকার সংরক্ষণ আইন, ২০০৯",
        "case_type_bn": "ফৌজদারি প্রতিকারযোগ্য মামলা",
        "source_summary": [
            {
                "citation": "পৃষ্ঠা নং ২",
                "excerpt": "মেয়াদোত্তীর্ণ পণ্য বিক্রয় করা যাবে না।",
            }
        ],
        "step_by_step_plan": [
            {
                "step_number": 1,
                "title": "প্রমাণ সংরক্ষণ",
                "description": "ক্রয়ের রসিদ ও পণ্যের ছবি রাখুন।",
                "statute_ref": ["ধারা ৫১"],
            }
        ],
        "required_documents": ["ক্রয়ের রসিদ"],
        "statute_citations": [
            {
                "section_number": "৫১",
                "section_title": "ভোক্তা-অধিকার বিরোধী কার্য",
                "legal_status": "Active",
                "content": "আইনের মূল বিধান।",
            }
        ],
        "disclaimer": "প্রয়োজনে আইনজীবীর সঙ্গে যাচাই করুন।",
    }

    content = build_case_plan_docx("মেয়াদোত্তীর্ণ পণ্য বিক্রি করলে কী করব?", analysis)
    document = Document(BytesIO(content))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)

    assert "ধাপে ধাপে আইনি করণীয়" in text
    assert "পৃষ্ঠা নং ২" in text
    assert "ধাপ 1: প্রমাণ সংরক্ষণ" in text
    assert "ধারা ৫১" in text
    assert "আইনের মূল বিধান।" in text


def test_case_plan_docx_requires_a_nonempty_plan() -> None:
    try:
        build_case_plan_docx("একটি আইনি প্রশ্ন", {})
    except ValueError as exc:
        assert "পদক্ষেপ পরিকল্পনা" in str(exc)
    else:
        raise AssertionError("A DOCX export without a plan should be rejected.")


if __name__ == "__main__":
    test_case_plan_docx_contains_grounded_steps_and_source_citations()
    test_case_plan_docx_requires_a_nonempty_plan()
    print("DOCX export checks passed.")
