from __future__ import annotations

import runpy
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import main  # noqa: E402
from case_advisor import build_case_action_plan, summarize_source  # noqa: E402


def statute(section_number: str, title: str, content: str) -> dict[str, Any]:
    return {
        "section_number": section_number,
        "section_title": title,
        "content": content,
        "domain": "labour_law",
    }


def test_overtime_search_excludes_accident_and_audit_sections() -> None:
    results = [
        statute("১৬৯", "মারাত্মক দুর্ঘটনার ক্ষেত্রে শ্রম আদালতের ক্ষমতা", "দুর্ঘটনার ক্ষতিপূরণ"),
        statute("১০৮", "অধিকাল কর্মের জন্য অতিরিক্ত ভাতা", "অধিকাল কাজের জন্য দ্বিগুণ হারে ভাতা"),
        statute("৩২১", "হিসাব ও নিরীক্ষা", "বোর্ডের হিসাব নিরীক্ষা"),
    ]

    selected = main._select_relevant_statutes(
        "শ্রম আইন অনুযায়ী অতিরিক্ত কাজের ওভারটাইম ভাতা কীভাবে হিসাব হবে?",
        results,
    )

    assert [item["section_number"] for item in selected] == ["১০৮"]


def test_wage_withholding_selects_wage_claim_not_injury_compensation() -> None:
    results = [
        statute("১৫৫", "ক্ষতিপূরণ বন্টন", "মৃত শ্রমিকের জখমজনিত ক্ষতিপূরণ"),
        statute(
            "১৩২",
            "মজুরী হইতে কর্তন বা মজুরী বিলম্বে পরিশোধের কারণে উত্থিত দাবী",
            "অনাদায়ী বা বিলম্বিত মজুরি আদায়ের জন্য শ্রম আদালতে দরখাস্ত",
        ),
        statute("১৪৭", "শ্রম আদালতে দরখাস্ত", "দুর্ঘটনাজনিত ক্ষতিপূরণের দরখাস্ত"),
        statute("২১৩", "শ্রম আদালতে দরখাস্ত", "শ্রমিক সংগঠন সংক্রান্ত দরখাস্ত"),
    ]

    selected = main._select_relevant_statutes(
        "শ্রমিকের বেতন আটকে রাখলে কীভাবে আইনি প্রতিকার পাওয়া যাবে?",
        results,
    )

    assert [item["section_number"] for item in selected] == ["১৩২"]


def test_consumer_remedy_query_adds_only_its_related_procedure_section() -> None:
    results = [
        {
            **statute(
                "৫১",
                "মেয়াদ উত্তীর্ণ কোন পণ্য বা ঔষধ বিক্রয় করিবার দণ্ড",
                "মেয়াদোত্তীর্ণ পণ্য বিক্রয়",
            ),
            "domain": "consumer_rights",
        },
        {
            **statute("৬৬", "দেওয়ানী প্রতিকার", "দেওয়ানী প্রতিকারের বিধান"),
            "domain": "consumer_rights",
        },
        {
            **statute("৪০", "অধিক মূল্যে বিক্রয় করিবার দণ্ড", "পণ্যের মূল্য"),
            "domain": "consumer_rights",
        },
    ]

    selected = main._select_relevant_statutes(
        "মেয়াদোত্তীর্ণ পণ্য বিক্রি করলে কী প্রতিকার পাওয়া যায়?",
        results,
    )

    assert [item["section_number"] for item in selected] == ["৫১", "৬৬"]


def test_cyber_query_selects_fraud_and_hacking_not_blackmail() -> None:
    results = [
        {
            **statute("৩৪", "পরোয়ানার মাধ্যমে তল্লাশি ও জব্দ", "কম্পিউটারে বেআইনি প্রবেশ ও হ্যাকিং"),
            "domain": "cyber_law",
        },
        {
            **statute(
                "৩৫",
                "বেআইনি প্রবেশ বা অনুপ্রবেশ বা হ্যাকিং এর ক্ষেত্রে পরোয়ানা ব্যতিরেকে তল্লাশি, জব্দ ও গ্রেফতার",
                "বেআইনি প্রবেশ বা হ্যাকিংয়ের ক্ষেত্রে তল্লাশি ও জব্দ",
            ),
            "domain": "cyber_law",
        },
        {
            **statute(
                "১৭",
                "গুরুত্বপূর্ণ তথ্য পরিকাঠামোতে বে-আইনি প্রবেশ বা হ্যাকিং, ইত্যাদির দণ্ড",
                "গুরুত্বপূর্ণ তথ্য পরিকাঠামোতে অননুমোদিত প্রবেশ",
            ),
            "domain": "cyber_law",
        },
        {
            **statute("২৫", "ব্ল্যাকমেইলিং ও যৌন হয়রানি", "ব্ল্যাকমেইলিং বা যৌন হয়রানি"),
            "domain": "cyber_law",
        },
        {
            **statute("৪০", "মামলা দায়ের ও অপরাধ বিচারার্থ গ্রহণ", "অভিযোগ গ্রহণ ও তদন্তের পদ্ধতি"),
            "domain": "cyber_law",
        },
        {
            **statute("২২", "সাইবার স্পেসে প্রতারণার অপরাধ ও দণ্ড", "সাইবার স্পেসে প্রতারণার অপরাধ"),
            "domain": "cyber_law",
        },
    ]

    selected = main._select_relevant_statutes(
        "অনলাইনে প্রতারণা ও আইডি হ্যাক হলে কী করণীয়?",
        results,
    )

    assert {item["section_number"] for item in selected} == {"২২", "৩৫", "৪০"}
    assert main._select_relevant_statutes(
        "গুরুত্বপূর্ণ তথ্য পরিকাঠামোতে হ্যাকিং",
        [results[2]],
    ) == [results[2]]


def test_search_abstains_when_one_requested_cyber_issue_has_no_matching_section() -> None:
    results = [
        {
            **statute("৩৪", "তল্লাশি ও জব্দ", "কম্পিউটারে বেআইনি প্রবেশ ও হ্যাকিং"),
            "domain": "cyber_law",
        }
    ]

    assert not main._select_relevant_statutes(
        "অনলাইন প্রতারণা ও আইডি হ্যাক হলে কী করণীয়?",
        results,
    )


def test_cyber_topic_matching_ignores_unrelated_body_mentions() -> None:
    results = [
        {
            **statute("২৩", "সাইবার সন্ত্রাসী কার্য সংঘটনের অপরাধ ও দণ্ড", "সন্ত্রাসী উদ্দেশ্যের শর্তে পরিচয় গোপন করে প্রতারণা"),
            "domain": "cyber_law",
        }
    ]

    assert not main._select_relevant_statutes("সাইবার স্পেসে প্রতারণা", results)


def test_chunk_parser_does_not_attach_next_heading_to_previous_section() -> None:
    parse_lines_to_chunks = runpy.run_path(
        str(ROOT / "backend/scripts/01_scrape_new_domains.py")
    )["parse_lines_to_chunks"]
    long_heading = (
        "বেআইনি প্রবেশ বা অনুপ্রবেশ বা হ্যাকিং এর ক্ষেত্রে "
        "পরোয়ানা ব্যতিরেকে তল্লাশি, জব্দ ও গ্রেফতার"
    )
    assert len(long_heading) > 90
    chunks = parse_lines_to_chunks(
        [
            "প্রথম ধারার শিরোনাম",
            "১। প্রথম ধারার মূল বিধান",
            long_heading,
            long_heading,
            "২। দ্বিতীয় ধারার মূল বিধান",
        ],
        "cyber_law",
        "সাইবার আইন",
        "পরীক্ষামূলক আইন",
    )

    assert chunks[0]["section_title"] == "প্রথম ধারার শিরোনাম"
    assert long_heading not in chunks[0]["content"]
    assert chunks[1]["section_title"] == long_heading


def test_simple_calculation_question_does_not_get_a_generic_case_plan() -> None:
    assert not main._requests_action_plan(
        "শ্রম আইন অনুযায়ী ওভারটাইম ভাতা কীভাবে হিসাব হবে?"
    )
    assert main._requests_action_plan(
        "অনলাইনে প্রতারণা ও আইডি হ্যাক হলে কী করণীয়?"
    )


def test_case_plan_does_not_infer_forum_deadline_or_irrelevant_documents() -> None:
    analysis = build_case_action_plan(
        "ওভারটাইম ভাতা কীভাবে হিসাব হবে?",
        [
            {
                **statute(
                    "১০৮",
                    "অধিকাল কর্মের জন্য অতিরিক্ত ভাতা",
                    "অধিকাল কাজের জন্য দ্বিগুণ হারে ভাতা।",
                ),
                "domain": "labour_law",
                "domain_bn": "বাংলাদেশ শ্রম আইন, ২০০৬",
                "act_name": "বাংলাদেশ শ্রম আইন, ২০০৬",
            }
        ],
    )

    assert "নিশ্চিত করা হয়নি" in analysis["case_type_bn"]
    assert "চাকরিচ্যুতির নোটিশ" not in " ".join(analysis["required_documents"])
    assert not analysis["step_by_step_plan"][2]["statute_ref"]
    assert not analysis["step_by_step_plan"][3]["statute_ref"]
    assert "নিশ্চিত" in analysis["step_by_step_plan"][3]["description"]


def test_wage_claim_plan_identifies_labour_law_subject_and_statutory_process() -> None:
    analysis = build_case_action_plan(
        "শ্রমিকের বেতন আটকে রাখলে কীভাবে আইনি প্রতিকার পাওয়া যাবে?",
        [
            {
                **statute(
                    "১৩২",
                    "মজুরী হইতে কর্তন বা মজুরী বিলম্বে পরিশোধের কারণে উত্থিত দাবী",
                    "মজুরি না দেওয়া বা বিলম্বের জন্য শ্রম আদালতে দরখাস্ত করা যায়। "
                    "দরখাস্ত বারো মাসের মধ্যে করতে হয়; যথেষ্ট কারণ থাকলে পরে গ্রহণ হতে পারে। "
                    "আদালত শুনানি শেষে পাওনা দিতে এবং কিছু ক্ষেত্রে ২৫ শতাংশ ক্ষতিপূরণ দিতে পারে।",
                ),
                "domain": "labour_law",
                "domain_bn": "বাংলাদেশ শ্রম আইন",
                "act_name": "বাংলাদেশ শ্রম আইন, ২০০৬",
            }
        ],
    )

    assert "বকেয়া/বিলম্বিত মজুরি" in analysis["legal_search_subject_bn"]
    assert "নিশ্চিত করা হয়নি" in analysis["case_type_bn"]
    assert "শ্রম আদালত" in analysis["step_by_step_plan"][1]["description"]
    assert "১২ মাস" in analysis["step_by_step_plan"][2]["description"]
    assert "২৫%" in analysis["step_by_step_plan"][3]["description"]


def test_pdf_summary_omits_pages_without_query_evidence() -> None:
    assert summarize_source(
        [{"page_number": 1, "text": "অন্য একটি বিষয়ে সাধারণ আলোচনা"}],
        "ওভারটাইম ভাতা",
    ) == []
