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
    "মজুরী বিলম্বে পরিশোধের কারণে উত্থিত দাবী",
    "দেওয়ানী প্রতিকার",
    "দেওয়ানী প্রতিকার",
)
UNPAID_WAGE_QUERY_MARKERS = (
    "বকেয়া মজুরি",
    "বকেয়া মজুরী",
    "বকেয়া বেতন",
    "মজুরি আটকে",
    "মজুরী আটকে",
    "বেতন আটকে",
    "মজুরি দেয়নি",
    "মজুরী দেয়নি",
    "বেতন দেয়নি",
    "বেতন পরিশোধ হয়নি",
    "মজুরি পরিশোধ হয়নি",
    "মজুরী পরিশোধ হয়নি",
    "unpaid wage",
    "unpaid wages",
    "unpaid salary",
    "salary withheld",
    "wages withheld",
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


def _is_unpaid_wage_claim(
    query: str, domain: str, statutes: list[dict[str, Any]]
) -> bool:
    if domain != "labour_law" or not any(
        _has_marker(query, marker) for marker in UNPAID_WAGE_QUERY_MARKERS
    ):
        return False
    return any(
        str(statute.get("section_number") or "") in {"১৩২", "132"}
        and _has_marker(
            str(statute.get("section_title") or ""),
            "মজুরী বিলম্বে পরিশোধের কারণে উত্থিত দাবী",
        )
        for statute in statutes
    )


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
    wage_claim = _is_unpaid_wage_claim(query, domain, statutes)
    if wage_claim:
        legal_search_subject = "বকেয়া/বিলম্বিত মজুরি আদায়ের দাবি (ধারা ১৩২)"
    else:
        primary_statute = statutes[0]
        primary_title = str(primary_statute.get("section_title") or "").strip()
        legal_search_subject = (
            f"{_citation_ref(primary_statute)}: {primary_title}"
            if primary_title
            else "প্রাসঙ্গিক আইনভিত্তিক বিষয় আরও যাচাই প্রয়োজন"
        )
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
        else "নির্বাচিত ধারাগুলো থেকে অভিযোগ বা আবেদনের সুনির্দিষ্ট পদ্ধতি নিশ্চিত করা যায়নি। "
        "কোনো নির্দিষ্ট কর্তৃপক্ষ বা প্রক্রিয়া অনুমান না করে মূল আইন/আইনজীবীর সঙ্গে যাচাই করুন।"
    )
    step_two_title = "অভিযোগ বা প্রক্রিয়াগত পদক্ষেপ যাচাই"
    step_three = (
        "এই অনুসন্ধানের নির্বাচিত ধারাগুলো থেকে আপনার ঘটনার জন্য নির্দিষ্ট কর্তৃপক্ষ, "
        "আদালত বা ট্রাইব্যুনাল নিশ্চিত করা হয়নি। পদক্ষেপের আগে মূল আইন ও সংশ্লিষ্ট "
        "কর্তৃপক্ষ/আইনজীবীর কাছে যাচাই করুন।"
    )
    step_three_title = "উপযুক্ত কর্তৃপক্ষ ও বিচারিক প্রক্রিয়া যাচাই"
    step_four = (
        "নির্বাচিত ধারাগুলো থেকে নির্দিষ্ট তামাদি, আপিল বা অন্য কোনো সময়সীমা নিশ্চিত "
        "করা হয়নি। সময়সীমা অনুমান না করে মূল আইন বা আইনজীবীর কাছে দ্রুত যাচাই করুন।"
    )
    step_four_title = "সময়সীমা, প্রতিকার ও আপিল যাচাই"
    step_two_refs = procedure_refs
    step_three_refs: list[str] = []
    step_four_refs: list[str] = []
    if wage_claim:
        wage_refs = [_citation_ref(statute) for statute in procedure_sections]
        step_two_title = "বকেয়া বা বিলম্বিত মজুরির দাবি"
        step_two = (
            "ধারা ১৩২(১) অনুযায়ী, মজুরি কর্তন, অনাদায়ী থাকা বা বিলম্বে পরিশোধের ক্ষেত্রে "
            "শ্রমিক বা আইনসঙ্গত প্রতিনিধি পাওনা আদায়ের জন্য শ্রম আদালতে দরখাস্ত করতে পারেন। "
            "মজুরি পাওনা কি না এবং পরিশোধের জন্য দায়ী ব্যক্তি কে—নিয়োগ ও বেতন-সংক্রান্ত "
            "নথি দিয়ে যাচাই করুন।"
        )
        step_three_title = "শ্রম আদালতের এখতিয়ার ও আবেদনের সময়"
        step_three = (
            "ধারা ১৩২(২) অনুযায়ী, দরখাস্তটি কাজের স্থান বা মজুরি পরিশোধের স্থানের "
            "এখতিয়ারাধীন শ্রম আদালতে করতে হয়। মজুরি কর্তনের তারিখ বা মজুরি প্রদেয় "
            "হওয়ার তারিখ থেকে ১২ মাসের মধ্যে আবেদন করতে হয়; যথেষ্ট কারণ থাকলে আদালত "
            "বিলম্বিত আবেদনও গ্রহণ করতে পারে।"
        )
        step_four_title = "সম্ভাব্য আদেশ ও ক্ষতিপূরণের শর্ত"
        step_four = (
            "ধারা ১৩২(৩), (৫) ও (৬) অনুযায়ী শুনানি ও প্রমাণের পর শ্রম আদালত বকেয়া "
            "মজুরি দিতে নির্দেশ দিতে পারে এবং আইনের শর্তে সর্বোচ্চ ২৫% ক্ষতিপূরণও "
            "নির্দেশ করতে পারে। এই ক্ষতিপূরণ স্বয়ংক্রিয় নয়; প্রকৃত ভুল/বিরোধ, জরুরি "
            "বা বিশেষ পরিস্থিতি, অথবা শ্রমিকের মজুরি গ্রহণ/দাবি না করার মতো কারণ থাকলে "
            "বিলম্বের ক্ষেত্রে তা নাও দেওয়া হতে পারে।"
        )
        step_three_refs = wage_refs
        step_four_refs = wage_refs

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
            "title": step_two_title,
            "description": step_two,
            "statute_ref": step_two_refs,
        },
        {
            "step_number": 3,
            "title": step_three_title,
            "description": step_three,
            "statute_ref": step_three_refs,
        },
        {
            "step_number": 4,
            "title": step_four_title,
            "description": step_four,
            "statute_ref": step_four_refs,
        },
    ]
    return {
        "case_type_bn": case_type,
        "legal_search_subject_bn": legal_search_subject,
        "detected_domain_bn": domain_bn,
        "act_name": act_name,
        "source_summary": source_summary or [],
        "statute_citations": citations,
        "step_by_step_plan": plan,
        "required_documents": _required_documents(domain, query),
        "disclaimer": (
            "এই পরিকল্পনা একটি সহায়ক তালিকা, আইনি মতামত নয়। প্রদর্শিত ধারার বাইরে "
            "কোনো কর্তৃপক্ষ বা মামলার ধরন অনুমান করা হয়নি। আইনভিত্তিক অনুসন্ধানের "
            "বিষয়টি প্রাথমিক শ্রেণিবিন্যাস; মূল আইন ও ঘটনার তথ্য আইনজীবী/সংশ্লিষ্ট "
            "কর্তৃপক্ষের মাধ্যমে যাচাই করুন।"
        ),
    }
