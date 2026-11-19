"""Deterministic, statute-grounded case action plans."""

from __future__ import annotations

import re
from typing import Any


CRIMINAL_MARKERS = (
    "কারাদণ্ড", "কারাদন্ড", "অর্থদণ্ড", "অর্থদন্ড", "দণ্ড", "দন্ড",
    "জরিমানা", "শাস্তি", "অপরাধ", "আমলযোগ্য", "জামিন", "ম্যাজিস্ট্রেট",
    "imprisonment", "punishable", "penalty", "fine", "offence", "offense",
)
CIVIL_MARKERS = (
    "ক্ষতিপূরণ", "বকেয়া মজুরি", "বকেয়া বেতন", "মজুরি", "বেতন", "ছুটি",
    "চাকুরী", "চাকরি", "আপীল", "আপিল", "appeal", "compensation",
    "recovery", "administrative",
)
FORUM_MARKERS = (
    "শ্রম আদালত", "সাইবার ট্রাইব্যুনাল", "ট্রাইব্যুনাল", "ম্যাজিস্ট্রেট",
    "অধিদপ্তর", "মহাপরিচালক", "পরিদর্শক", "court", "tribunal", "authority",
)
LIMIT_MARKERS = (
    "তামাদি", "সময়সীমা", "সময়সীমা", "দিনের মধ্যে", "বৎসরের মধ্যে",
    "আপীল", "আপিল", "appeal", "limitation", "within",
)

EVIDENCE_BY_DOMAIN = {
    "labour_law": (
        "নিয়োগপত্র/চাকরির চুক্তি, পরিচয়পত্র, বেতন স্লিপ, হাজিরা বা কর্মঘণ্টার নথি, "
        "চাকরিচ্যুতির নোটিশ এবং সংশ্লিষ্ট লিখিত যোগাযোগ।",
    ),
    "consumer_rights": (
        "ক্রয়ের রসিদ/লেনদেনের প্রমাণ, পণ্যের প্যাকেট ও ব্যাচ নম্বর, মেয়াদ/মূল্য "
        "দেখা যায় এমন ছবি এবং বিক্রেতার সঙ্গে যোগাযোগের নথি।",
    ),
    "cyber_law": (
        "মূল URL/অ্যাকাউন্ট আইডি, তারিখ-সময়সহ স্ক্রিনশট, লেনদেন/প্ল্যাটফর্ম "
        "রেকর্ড এবং প্রাসঙ্গিক ইমেইল বা বার্তা।",
    ),
}


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


def _exact_excerpt(
    statutes: list[dict[str, Any]], markers: tuple[str, ...], limit: int = 2
) -> list[dict[str, str]]:
    excerpts: list[dict[str, str]] = []
    for statute in statutes:
        content = str(statute.get("content") or "")
        for sentence in re.split(r"(?<=[।.!?])\s+|\n+", content):
            clean_sentence = sentence.strip()
            if clean_sentence and any(
                _has_marker(clean_sentence, marker) for marker in markers
            ):
                excerpts.append(
                    {
                        "statute_ref": _citation_ref(statute),
                        "excerpt": clean_sentence[:420],
                    }
                )
                break
        if len(excerpts) >= limit:
            break
    return excerpts


def summarize_source(
    chunks: list[dict[str, Any]], query: str, limit: int = 3
) -> list[dict[str, Any]]:
    """Select exact, page-labelled excerpts using deterministic term overlap."""
    query_tokens = {
        token
        for token in re.findall(r"[\u0980-\u09FF]+|[a-z0-9]+", _normalize(query))
        if len(token) > 2
    }
    best_by_page: dict[int, tuple[int, str]] = {}
    for chunk in chunks:
        text = str(chunk.get("text") or "").strip()
        if not text:
            continue
        page_number = int(chunk.get("page_number") or 1)
        tokens = set(
            re.findall(r"[\u0980-\u09FF]+|[a-z0-9]+", _normalize(text))
        )
        score = len(query_tokens & tokens)
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
    source_text = " ".join(
        str(item.get("excerpt") or "") for item in (source_summary or [])
    )
    evidence_text = " ".join(
        f"{statute.get('section_title', '')} {statute.get('content', '')}"
        for statute in statutes
    )
    case_text = f"{query} {source_text} {evidence_text}"
    is_criminal = any(_has_marker(case_text, marker) for marker in CRIMINAL_MARKERS)
    is_civil = any(_has_marker(case_text, marker) for marker in CIVIL_MARKERS)

    if is_criminal and is_civil:
        case_type = "মিশ্র প্রতিকার (ফৌজদারি ও ক্ষতিপূরণমূলক)"
    elif is_criminal:
        case_type = "ফৌজদারি প্রতিকারযোগ্য মামলা (Criminal Proceeding)"
    else:
        case_type = "প্রশাসনিক ও ক্ষতিপূরণমূলক প্রতিকার"

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
    statute_refs = list(dict.fromkeys(_citation_ref(statute) for statute in statutes))
    forum_excerpts = _exact_excerpt(statutes, FORUM_MARKERS)
    limit_excerpts = _exact_excerpt(statutes, LIMIT_MARKERS)
    complaint_excerpts = _exact_excerpt(
        statutes, ("অভিযোগ", "মামলা", "অধিদপ্তর", "complaint", "proceeding")
    )

    step_two = (
        "ঘটনার তারিখ, সংশ্লিষ্ট পক্ষ এবং সংরক্ষিত প্রমাণের তালিকা দিয়ে লিখিত "
        "অভিযোগ বা নোটিশের খসড়া তৈরি করুন।"
        if complaint_excerpts
        else "উদ্ধৃত ধারাগুলোতে নির্দিষ্ট অভিযোগ বা নোটিশের প্রক্রিয়া পাওয়া যায়নি। "
        "কোন কর্তৃপক্ষের কাছে কীভাবে জানাতে হবে, তা মূল আইন বা আইনজীবীর কাছে "
        "যাচাই করে তারপর লিখিত পদক্ষেপ নিন।"
    )
    if complaint_excerpts:
        step_two += (
            f" উদ্ধৃত {complaint_excerpts[0]['statute_ref']}-এ প্রাসঙ্গিক "
            f"বিধান আছে: “{complaint_excerpts[0]['excerpt']}”"
        )
    if is_criminal:
        step_two += " অভিযোগ গ্রহণ, এজাহার/জিডি বা তাৎক্ষণিক গ্রেপ্তারের যোগ্যতা উদ্ধৃত ধারায় স্পষ্ট না থাকলে তা ধরে নেবেন না; আইনজীবী বা সংশ্লিষ্ট কর্তৃপক্ষের কাছে যাচাই করুন।"
    step_three = (
        f"উদ্ধৃত ধারায় ফৌজদারি দণ্ডের ইঙ্গিত আছে। "
        if is_criminal
        else "উদ্ধৃত ধারাগুলো প্রতিকার/দায় নির্ধারণে প্রাসঙ্গিক। "
    )
    if forum_excerpts:
        step_three += (
            f"উপযুক্ত ফোরাম সম্পর্কে প্রাপ্ত নির্দিষ্ট পাঠ: "
            f"“{forum_excerpts[0]['excerpt']}” ({forum_excerpts[0]['statute_ref']}). "
            "শুধু এই উদ্ধৃত বিধানের পরিসরে প্রযোজ্য ফোরাম নিশ্চিত করুন।"
        )
    else:
        step_three += (
            "প্রাপ্ত ধারাগুলোতে নির্দিষ্ট আদালত/ট্রাইব্যুনাল বা জামিনযোগ্যতা "
            "স্পষ্টভাবে পাওয়া যায়নি; কোনো ফোরাম বা প্রক্রিয়া ধরে না নিয়ে "
            "আইনজীবী/সংশ্লিষ্ট কর্তৃপক্ষের কাছে নিশ্চিত করুন।"
        )
    step_four = (
        f"উদ্ধৃত সময়সীমা/আপিল সংক্রান্ত পাঠ: “{limit_excerpts[0]['excerpt']}” "
        f"({limit_excerpts[0]['statute_ref']})."
        if limit_excerpts
        else "এই ফলাফলে নির্দিষ্ট তামাদি, সময়সীমা বা আপিল-সময়সীমা পাওয়া যায়নি। "
        "সময়সীমা অনুমান না করে মূল আইন ও কর্তৃপক্ষের কাছ থেকে যাচাই করুন।"
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
    step_one = (
        EVIDENCE_BY_DOMAIN.get(domain, ("ঘটনা-সংশ্লিষ্ট মূল নথি সংরক্ষণ করুন.",))[0]
        + source_note
    )
    plan = [
        {
            "step_number": 1,
            "title": "প্রাথমিক তথ্য ও প্রমাণ সংরক্ষণ",
            "description": step_one,
            "statute_ref": statute_refs,
        },
        {
            "step_number": 2,
            "title": "অভিযোগ / আইনি নোটিশ প্রস্তুত",
            "description": step_two,
            "statute_ref": [
                item["statute_ref"] for item in complaint_excerpts
            ] or statute_refs,
        },
        {
            "step_number": 3,
            "title": "উপযুক্ত কর্তৃপক্ষ ও বিচারিক প্রক্রিয়া যাচাই",
            "description": step_three,
            "statute_ref": [
                item["statute_ref"] for item in forum_excerpts
            ] or statute_refs,
        },
        {
            "step_number": 4,
            "title": "সময়সীমা, প্রতিকার ও আপিল যাচাই",
            "description": step_four,
            "statute_ref": [
                item["statute_ref"] for item in limit_excerpts
            ] or statute_refs,
        },
    ]
    return {
        "case_type_bn": case_type,
        "detected_domain_bn": domain_bn,
        "act_name": act_name,
        "source_summary": source_summary or [],
        "statute_citations": citations,
        "step_by_step_plan": plan,
        "required_documents": list(EVIDENCE_BY_DOMAIN.get(domain, ())),
        "disclaimer": (
            "এই পদক্ষেপ-তালিকা কেবল প্রদর্শিত PDF উদ্ধৃতি ও সংকলিত ধারার "
            "ভিত্তিতে তৈরি। উদ্ধৃত পাঠে অনুল্লিখিত আদালত, সময়সীমা বা প্রক্রিয়া "
            "অনুমান করা হয়নি; পদক্ষেপ নেওয়ার আগে আইনজীবী/কর্তৃপক্ষের কাছে যাচাই করুন।"
        ),
    }
