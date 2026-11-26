"""Deterministic, statute-grounded case action plans."""

from __future__ import annotations

import re
from typing import Any


PROCEDURE_TITLE_MARKERS = (
    "মামলা দায়ের",
    "মামলা দায়ের",
    "অভিযোগ দায়ের",
    "অভিযোগ দায়ের",
    "শ্রম আদালতে দরখাস্ত",
    "দেওয়ানী প্রতিকার",
    "দেওয়ানী প্রতিকার",
)
TERMINATION_MARKERS = ("চাকরিচ্যুত", "বরখাস্ত", "termination", "dismissal")
FINANCIAL_LOSS_MARKERS = (
    "প্রতারণা", "লেনদেন", "অর্থ", "fraud", "scam", "transaction",
)
ACCOUNT_ACCESS_MARKERS = (
    "হ্যাক", "অননুমোদিত প্রবেশ", "আইডি", "account hacked", "unauthorized access",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _has_marker(text: str, marker: str) -> bool:
    normalized_text = _normalize(text)
    normalized_marker = _normalize(marker)
    if marker.isascii() and " " not in marker:
        return re.search(
            rf"(?<![a-z0-9]){re.escape(marker)}[a-z0-9]*(?![a-z0-9])",
            normalized_text,
        ) is not None
    return normalized_marker in normalized_text


def _citation_ref(statute: dict[str, Any]) -> str:
    return f"ধারা {statute.get('section_number', '—')}"


def summarize_source(
    chunks: list[dict[str, Any]], query: str, limit: int = 3
) -> list[dict[str, Any]]:
    """Select exact, page-labelled excerpts using deterministic term overlap."""
    ignored_tokens = {
        "এই", "সেই", "নথি", "নথিতে", "অনুযায়ী", "অনুযায়ী", "কী", "কি",
        "করণীয়", "করণীয়", "কীভাবে", "কিভাবে", "বলুন", "জানতে", "পারি",
    }
    query_tokens = {
        token
        for token in re.findall(r"[\u0980-\u09FF]+|[a-z0-9]+", _normalize(query))
        if len(token) > 2 and token not in ignored_tokens
    }
    token_aliases = {
        "প্রতারণা": "fraud",
        "প্রতারণার": "fraud",
        "সাইবার": "cyber",
        "অনলাইন": "online",
        "অনলাইনে": "online",
        "ওভারটাইম": "overtime",
        "অধিকাল": "overtime",
        "হ্যাক": "hack",
        "হ্যাকিং": "hack",
    }
    query_tokens = {token_aliases.get(token, token) for token in query_tokens}
    best_by_page: dict[int, tuple[int, str]] = {}
    for chunk in chunks:
        text = str(chunk.get("text") or "").strip()
        if not text:
            continue
        page_number = int(chunk.get("page_number") or 1)
        tokens = set(
            re.findall(r"[\u0980-\u09FF]+|[a-z0-9]+", _normalize(text))
        )
        tokens = {token_aliases.get(token, token) for token in tokens}
        score = len(query_tokens & tokens)
        if score == 0:
            continue
        current = best_by_page.get(page_number)
        if current is None or score > current[0]:
            best_by_page[page_number] = (score, text)

    ranked = sorted(
        best_by_page.items(),
        key=lambda item: (-item[1][0], item[0]),
    )[:limit]
    return [
        {
            "page_number": page_number,
            "citation": f"পৃষ্ঠা নং {page_number}",
            "excerpt": text[:600],
        }
        for page_number, (_, text) in ranked
    ]


def _required_documents(domain: str, query: str) -> list[str]:
    normalized_query = _normalize(query)
    if domain == "labour_law":
        documents = [
            "নিয়োগপত্র/চাকরির চুক্তি এবং পরিচয়পত্র, যদি থাকে।",
            "বেতন স্লিপ/বেতন রেজিস্টার এবং হাজিরা বা কর্মঘণ্টার নথি।",
        ]
        if any(
            _has_marker(normalized_query, marker)
            for marker in TERMINATION_MARKERS
        ):
            documents.append(
                "চাকরিচ্যুতি বা বরখাস্তের নোটিশ ও সংশ্লিষ্ট যোগাযোগ, যদি থাকে।"
            )
        if any(
            _has_marker(normalized_query, marker)
            for marker in ("ওভারটাইম", "অধিকাল")
        ):
            documents.append(
                "ওভারটাইমের দিন/ঘণ্টা ও অতিরিক্ত ভাতার হিসাবের রেকর্ড, যদি থাকে।"
            )
        return documents
    if domain == "consumer_rights":
        return [
            "ক্রয়ের রসিদ/লেনদেনের প্রমাণ, যদি থাকে।",
            "পণ্যের প্যাকেট, ব্যাচ নম্বর, মেয়াদ ও মূল্য দেখা যায় এমন ছবি।",
            "বিক্রেতা বা সেবাদাতার সঙ্গে যোগাযোগের নথি।",
        ]
    if domain == "cyber_law":
        documents = [
            "মূল URL/অ্যাকাউন্ট আইডি, তারিখ-সময়সহ স্ক্রিনশট এবং প্রাসঙ্গিক ইমেইল/বার্তা।",
        ]
        if any(_has_marker(normalized_query, marker) for marker in FINANCIAL_LOSS_MARKERS):
            documents.append(
                "লেনদেন/ব্যাংক/পেমেন্ট প্ল্যাটফর্মের রেকর্ড, আর্থিক ক্ষতি হয়ে থাকলে।"
            )
        if any(_has_marker(normalized_query, marker) for marker in ACCOUNT_ACCESS_MARKERS):
            documents.append(
                "লগইন সতর্কতা, পাসওয়ার্ড/অ্যাকাউন্ট পরিবর্তনের নোটিশ এবং "
                "প্ল্যাটফর্মে করা রিপোর্ট, যদি থাকে।"
            )
        return documents
    return ["ঘটনা-সংশ্লিষ্ট মূল নথি ও প্রমাণ সংরক্ষণ করুন।"]


def build_case_action_plan(
    query: str,
    statutes: list[dict[str, Any]],
    source_summary: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a four-step plan whose legal claims only cite retrieved provisions."""
    if not statutes:
        raise ValueError("A case action plan requires grounded statute citations.")

    domain = str(statutes[0].get("domain") or "")
    domain_bn = str(statutes[0].get("domain_bn") or "")
    act_name = str(statutes[0].get("act_name") or domain_bn)
    case_type = "এই অনুসন্ধান থেকে মামলার ধরন নিশ্চিত করা হয়নি"
    procedure_sections = [
        statute
        for statute in statutes
        if any(
            _has_marker(str(statute.get("section_title") or ""), marker)
            for marker in PROCEDURE_TITLE_MARKERS
        )
    ]

    citations = [
        {
            "domain_bn": str(statute.get("domain_bn") or ""),
            "act_name": str(statute.get("act_name") or ""),
            "section_number": str(statute.get("section_number") or ""),
            "section_title": str(statute.get("section_title") or ""),
            "legal_status": str(statute.get("legal_status") or ""),
            "content": str(statute.get("content") or ""),
            "confidence": float(statute.get("confidence") or 0.0),
        }
        for statute in statutes
    ]
    procedure_refs = list(
        dict.fromkeys(_citation_ref(statute) for statute in procedure_sections)
    )
    step_two = (
        "নির্বাচিত ধারার শিরোনামে অভিযোগ/আবেদনের বিধান আছে: "
        + "; ".join(
            f"{_citation_ref(statute)} ({statute.get('section_title') or 'প্রক্রিয়া'})"
            for statute in procedure_sections
        )
        + "। ঘটনার সঙ্গে কোন শর্তটি মেলে তা মূল ধারার পূর্ণ পাঠ যাচাই করে নিশ্চিত করুন; "
        "শুধু শিরোনাম দেখে অভিযোগ গ্রহণ বা ফল নিশ্চিত ধরে নেবেন না।"
        if procedure_sections
        else "নির্বাচিত ধারাগুলো থেকে অভিযোগ বা নোটিশের সুনির্দিষ্ট পদ্ধতি নিশ্চিত করা যায়নি। "
        "কোনো নির্দিষ্ট কর্তৃপক্ষ বা প্রক্রিয়া অনুমান না করে মূল আইন/আইনজীবীর সঙ্গে যাচাই করুন।"
    )
    step_three = (
        "এই অনুসন্ধানের নির্বাচিত ধারাগুলো থেকে আপনার ঘটনার জন্য নির্দিষ্ট কর্তৃপক্ষ, "
        "আদালত বা ট্রাইব্যুনাল নিশ্চিত করা হয়নি। পদক্ষেপের আগে মূল আইন ও সংশ্লিষ্ট "
        "কর্তৃপক্ষ/আইনজীবীর কাছে যাচাই করুন।"
    )
    step_four = (
        "নির্বাচিত ধারাগুলো থেকে নির্দিষ্ট তামাদি, আপিল বা অন্য কোনো সময়সীমা নিশ্চিত "
        "করা হয়নি। সময়সীমা অনুমান না করে মূল আইন বা আইনজীবীর কাছে দ্রুত যাচাই করুন।"
    )

    source_note = ""
    if source_summary:
        pages = ", ".join(
            str(item.get("citation") or f"পৃষ্ঠা নং {item.get('page_number')}")
            for item in source_summary
        )
        source_note = (
            f" নির্বাচিত PDF-এর {pages} থেকে প্রাপ্ত উদ্ধৃতিগুলোও বিবেচনায় নিন।"
        )
    step_one = " ".join(_required_documents(domain, query)) + source_note
    plan = [
        {
            "step_number": 1,
            "title": "প্রাথমিক তথ্য ও প্রমাণ সংরক্ষণ",
            "description": step_one,
            "statute_ref": [],
        },
        {
            "step_number": 2,
            "title": "অভিযোগ / আইনি নোটিশ প্রস্তুত",
            "description": step_two,
            "statute_ref": procedure_refs,
        },
        {
            "step_number": 3,
            "title": "উপযুক্ত কর্তৃপক্ষ ও বিচারিক প্রক্রিয়া যাচাই",
            "description": step_three,
            "statute_ref": [],
        },
        {
            "step_number": 4,
            "title": "সময়সীমা, প্রতিকার ও আপিল যাচাই",
            "description": step_four,
            "statute_ref": [],
        },
    ]
    return {
        "case_type_bn": case_type,
        "detected_domain_bn": domain_bn,
        "act_name": act_name,
        "source_summary": source_summary or [],
        "statute_citations": citations,
        "step_by_step_plan": plan,
        "required_documents": _required_documents(domain, query),
        "disclaimer": (
            "এই পরিকল্পনা একটি সহায়ক তালিকা, আইনি মতামত নয়। প্রদর্শিত ধারার বাইরে "
            "কোনো কর্তৃপক্ষ, মামলার ধরন বা সময়সীমা অনুমান করা হয়নি। মূল আইন ও "
            "ঘটনার তথ্য আইনজীবী/সংশ্লিষ্ট কর্তৃপক্ষের মাধ্যমে যাচাই করুন।"
        ),
    }
