"""Strict, shared domain validation for queries and uploaded PDF sources."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


MIN_DOMAIN_SIMILARITY = 0.48
MAX_COSINE_DISTANCE = 1.0 - MIN_DOMAIN_SIMILARITY

DOMAIN_SEMANTIC_ANCHORS = {
    "labour_law": (
        "বাংলাদেশ শ্রম আইন ২০০৬ শ্রমিকের মজুরি ওভারটাইম মাতৃত্বকালীন ছুটি "
        "কর্মঘণ্টা লকআউট",
    ),
    "consumer_rights": (
        "ভোক্তা অধিকার সংরক্ষণ আইন ২০০৯ মেয়াদোত্তীর্ণ পণ্য বিক্রি ভেজাল খাদ্য "
        "নকল পণ্য",
    ),
    "cyber_law": (
        "সাইবার সুরক্ষা আইন ২০২৬ অননুমোদিত প্রবেশ হ্যাকিং অনলাইন প্রতারণা "
        "তথ্য উপাত্ত",
    ),
}

DOMAIN_LABELS = {
    "labour_law": {
        "name": "বাংলাদেশ শ্রম আইন, ২০০৬",
        "act_terms": (
            "বাংলাদেশ শ্রম আইন",
            "bangladesh labour act",
            "bangladesh labour law",
            "bangladesh labor act",
            "bangladesh labor law",
        ),
        "terms": (
            "শ্রম", "শ্রমিক", "কর্মচার", "চাকরি", "চাকুরী", "নিয়োগ", "নিয়োগ",
            "মজুরি", "বেতন", "ওভারটাইম", "অতিরিক্ত কাজ", "মাতৃত্ব", "প্রসূতি",
            "ছুটি", "কারখানা", "কর্মঘণ্টা", "কর্মঘন্টা", "লকআউট", "লে-অফ",
            "labour", "labor", "worker", "employee", "employment", "overtime",
            "maternity leave", "wage", "salary", "termination", "lockout",
            "workplace accident",
        ),
    },
    "consumer_rights": {
        "name": "ভোক্তা-অধিকার সংরক্ষণ আইন, ২০০৯",
        "act_terms": (
            "ভোক্তা অধিকার সংরক্ষণ আইন",
            "ভোক্তা-অধিকার সংরক্ষণ আইন",
            "consumer rights protection act",
            "consumer protection act",
            "consumer rights act",
        ),
        "terms": (
            "ভোক্তা", "পণ্য", "দ্রব্য", "মেয়াদোত্তীর্ণ", "মেয়াদোত্তীর্ণ",
            "মেয়াদ উত্তীর্ণ", "মেয়াদ উত্তীর্ণ", "ভেজাল", "নকল", "ক্রেতা",
            "বিক্রেতা", "বিক্রি", "বিক্রয়", "বিক্রয়", "মূল্য", "দাম",
            "ওজনে", "বাটখারা", "ঔষধ", "ওষুধ", "খাদ্য",
            "consumer", "product", "expired", "counterfeit", "adulterated",
            "seller", "buyer", "price", "medicine", "food", "fake goods",
            "deceptive weight",
        ),
    },
    "cyber_law": {
        "name": "সাইবার সুরক্ষা আইন, ২০২৬",
        "act_terms": (
            "সাইবার সুরক্ষা আইন",
            "cyber protection act",
            "cyber security act",
            "cyber safety act",
        ),
        "terms": (
            "সাইবার", "অনলাইন", "ইন্টারনেট", "হ্যাক", "বুলিং", "সামাজিক মাধ্যম",
            "তথ্যপ্রযুক্তি", "তথ্য-উপাত্ত", "তথ্য উপাত্ত", "ডিজিটাল", "কম্পিউটার",
            "আইডি হ্যাক", "পরিচয় চুরি", "পরিচয় চুরি", "অনলাইন প্রতারণা",
            "cyber", "online", "internet", "hack", "bullying", "social media",
            "phishing", "computer", "data breach", "digital identity",
            "identity theft", "account theft", "online fraud", "defamation",
        ),
    },
}

OUT_OF_DOMAIN_TOPICS = {
    "general_criminal": (
        "খুন", "হত্যা", "মার্ডার", "murder", "homicide", "ডাকাতি", "ডাকাত",
        "robbery", "dacoity",
    ),
    "land": (
        "জমি", "জমির", "ভূমি", "খতিয়ান", "খতিয়ান", "নামজারি", "দলিল",
        "land dispute", "land deed", "mutation", "khatian",
    ),
    "family": (
        "তালাক", "বিবাহবিচ্ছেদ", "দেনমোহর", "উত্তরাধিকার", "ভরণপোষণ",
        "divorce", "dower", "inheritance",
    ),
    "traffic": (
        "ট্রাফিক", "সড়ক পরিবহন", "সড়ক পরিবহন", "ট্রাফিক আইন", "traffic law",
        "traffic violation",
    ),
    "tax": (
        "আয়কর", "আয়কর", "কর রিটার্ন", "ভ্যাট", "income tax", "tax return",
        "tax law",
    ),
    "general_nonlegal": (
        "ক্রিকেট", "ফুটবল", "খেলার নিয়ম", "খেলার নিয়ম", "রেসিপি", "রান্না",
        "গল্প লিখ", "কবিতা লিখ", "জীবনবৃত্তান্ত", "জীবন বৃত্তান্ত", "পাঠ্যবই",
        "পাঠ্যপুস্তক", "sports rules", "recipe", "cooking", "write a story",
        "resume", "curriculum vitae", "textbook", "text book",
    ),
}

OUT_OF_SCOPE_PDF_MESSAGE = (
    "দুঃখিত! আপলোডকৃত নথিটি আমাদের নির্ধারিত ৩টি আইনি ডোমেইনের "
    "(বাংলাদেশ শ্রম আইন ২০০৬, ভোক্তা অধিকার সংরক্ষণ আইন ২০০৯ এবং সাইবার "
    "সুরক্ষা আইন ২০২৬) অন্তর্ভুক্ত নয়। এই ৩টি ডোমেইনের বাইরের কোনো নথি "
    "বা উৎস থেকে সিস্টেম কোনো তথ্য গ্রহণ বা বিশ্লেষণ করতে পারবে না।"
)


@dataclass(frozen=True)
class DomainDecision:
    allowed: bool
    domains: tuple[str, ...] = ()
    domain: str | None = None
    domain_bn: str | None = None
    similarity: float | None = None
    reason: str = ""
    blocked_topics: tuple[str, ...] = ()


def _normalize(text: str) -> str:
    normalized = text.casefold().replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", normalized).strip()


def _contains_term(text: str, term: str) -> bool:
    if term.isascii() and term.replace(" ", "").isalnum():
        escaped = re.escape(term)
        if " " not in term:
            return re.search(rf"(?<![a-z0-9]){escaped}[a-z0-9]*(?![a-z0-9])", text) is not None
        return term in text
    return term in text


def _domain_scores(text: str) -> tuple[dict[str, int], dict[str, tuple[str, ...]]]:
    normalized = _normalize(text)
    scores: dict[str, int] = {}
    hits: dict[str, tuple[str, ...]] = {}
    for domain, definition in DOMAIN_LABELS.items():
        act_hits = tuple(
            term for term in definition["act_terms"]
            if _contains_term(normalized, term)
        )
        topic_hits = tuple(
            term for term in definition["terms"]
            if _contains_term(normalized, term)
        )
        scores[domain] = len(topic_hits) + 3 * len(act_hits)
        hits[domain] = act_hits + topic_hits
    return scores, hits


def _blocked_topics(text: str) -> tuple[str, ...]:
    normalized = _normalize(text)
    return tuple(
        topic
        for category, terms in OUT_OF_DOMAIN_TOPICS.items()
        if any(_contains_term(normalized, term) for term in terms)
        for topic in (category,)
    )


def domains_in_text(text: str) -> set[str]:
    """Return supported domains with at least one explicit topical signal."""
    scores, _ = _domain_scores(text)
    return {domain for domain, score in scores.items() if score > 0}


def inspect_domain_text(
    text: str,
    preferred_domain: str | None = None,
    allow_section_reference: bool = False,
) -> DomainDecision:
    """Apply lexical/blocklist checks before any semantic statute retrieval."""
    scores, hits = _domain_scores(text)
    domains = tuple(sorted(domain for domain, score in scores.items() if score > 0))
    blocked = _blocked_topics(text)
    has_act_name = any(
        term in hits[domain]
        for domain in DOMAIN_LABELS
        for term in DOMAIN_LABELS[domain]["act_terms"]
    )
    strong_domain_context = has_act_name or any(
        scores[domain] >= 2 for domain in domains
    )
    if "general_nonlegal" in blocked and not has_act_name:
        return DomainDecision(
            allowed=False,
            reason="blocked_nonlegal_topic",
            blocked_topics=blocked,
        )
    if blocked and not strong_domain_context:
        return DomainDecision(
            allowed=False,
            reason="blocked_topic",
            blocked_topics=blocked,
        )
    if preferred_domain and preferred_domain != "all":
        if preferred_domain not in DOMAIN_LABELS:
            return DomainDecision(allowed=False, reason="invalid_domain")
        if domains and preferred_domain not in domains:
            return DomainDecision(
                allowed=False,
                reason="selected_domain_mismatch",
                blocked_topics=blocked,
            )
        if not domains and not allow_section_reference:
            return DomainDecision(
                allowed=False,
                reason="no_supported_domain_signal",
                blocked_topics=blocked,
            )
        selected = preferred_domain
        return DomainDecision(
            allowed=True,
            domains=(selected,),
            domain=selected,
            domain_bn=DOMAIN_LABELS[selected]["name"],
            reason="supported_domain",
            blocked_topics=blocked,
        )
    if not domains and allow_section_reference:
        return DomainDecision(
            allowed=True,
            domains=tuple(DOMAIN_LABELS),
            reason="explicit_section_reference",
            blocked_topics=blocked,
        )
    if not domains:
        return DomainDecision(
            allowed=False,
            reason="no_supported_domain_signal",
            blocked_topics=blocked,
        )
    best_score = max(scores[domain] for domain in domains)
    best_domains = tuple(
        domain for domain in domains if scores[domain] == best_score
    )
    selected = best_domains[0] if len(best_domains) == 1 else None
    return DomainDecision(
        allowed=True,
        domains=domains,
        domain=selected,
        domain_bn=DOMAIN_LABELS[selected]["name"] if selected else None,
        reason="supported_domain",
        blocked_topics=blocked,
    )


def validate_pdf_domain(
    text: str,
    chunks: list[dict[str, Any]],
    collection: Any,
) -> DomainDecision:
    """Require both a supported topical signal and a matching Chroma result."""
    lexical_decision = inspect_domain_text(text)
    if not lexical_decision.allowed or lexical_decision.domain is None:
        return lexical_decision

    domain = lexical_decision.domain
    _, text_hits = _domain_scores(text)
    topic_hits = [
        term for term in text_hits[domain] if term in DOMAIN_LABELS[domain]["terms"]
    ]
    act_hits = [
        term for term in text_hits[domain] if term in DOMAIN_LABELS[domain]["act_terms"]
    ]
    if not topic_hits or (not act_hits and len(topic_hits) < 2):
        return DomainDecision(
            allowed=False,
            domain=domain,
            domain_bn=DOMAIN_LABELS[domain]["name"],
            reason="insufficient_domain_evidence",
            blocked_topics=lexical_decision.blocked_topics,
        )

    ranked_chunks = sorted(
        chunks,
        key=lambda chunk: (
            -_domain_scores(str(chunk.get("text") or ""))[0].get(domain, 0),
            int(chunk.get("page_number") or 0),
        ),
    )
    candidates = [
        str(chunk.get("text") or "").strip()[:1500]
        for chunk in ranked_chunks
        if _domain_scores(str(chunk.get("text") or ""))[0].get(domain, 0) > 0
    ][:8]
    if not candidates:
        candidates = [text.strip()[:1500]]

    best_similarity = -1.0
    best_domain = None
    for candidate in candidates:
        result = collection.query(
            query_texts=[candidate],
            n_results=1,
            where={"domain": domain},
            include=["distances", "metadatas"],
        )
        distances = result.get("distances") or []
        metadatas = result.get("metadatas") or []
        if not distances or not distances[0]:
            continue
        similarity = 1.0 - float(distances[0][0])
        metadata = metadatas[0][0] if metadatas and metadatas[0] else {}
        if similarity > best_similarity:
            best_similarity = similarity
            best_domain = (metadata or {}).get("domain")

    if best_domain != domain or best_similarity < MIN_DOMAIN_SIMILARITY:
        source_has_bengali = any(
            re.search(r"[\u0980-\u09FF]", str(chunk.get("text") or ""))
            for chunk in chunks
        )
        if not source_has_bengali:
            anchor_result = collection.query(
                query_texts=[DOMAIN_SEMANTIC_ANCHORS[domain][0]],
                n_results=1,
                where={"domain": domain},
                include=["distances", "metadatas"],
            )
            anchor_distances = anchor_result.get("distances") or []
            anchor_metadatas = anchor_result.get("metadatas") or []
            if anchor_distances and anchor_distances[0]:
                anchor_similarity = 1.0 - float(anchor_distances[0][0])
                anchor_metadata = (
                    anchor_metadatas[0][0]
                    if anchor_metadatas and anchor_metadatas[0]
                    else {}
                )
                if (
                    (anchor_metadata or {}).get("domain") == domain
                    and anchor_similarity >= MIN_DOMAIN_SIMILARITY
                ):
                    return DomainDecision(
                        allowed=True,
                        domains=(domain,),
                        domain=domain,
                        domain_bn=DOMAIN_LABELS[domain]["name"],
                        similarity=anchor_similarity,
                        reason="supported_domain_semantic_anchor",
                    )
        return DomainDecision(
            allowed=False,
            domain=domain,
            domain_bn=DOMAIN_LABELS[domain]["name"],
            similarity=max(0.0, best_similarity),
            reason="semantic_mismatch",
            blocked_topics=lexical_decision.blocked_topics,
        )
    return DomainDecision(
        allowed=True,
        domains=(domain,),
        domain=domain,
        domain_bn=DOMAIN_LABELS[domain]["name"],
        similarity=best_similarity,
        reason="supported_domain",
    )
