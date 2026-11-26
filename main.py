"""FastAPI application for the statute-grounded legal assistant."""

import csv
import hashlib
import importlib.util
import io
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Literal

from fastapi import Cookie, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR / "backend"
VECTOR_STORE_SCRIPT = BACKEND_DIR / "scripts" / "03_vector_store.py"
FRONTEND_INDEX = BASE_DIR / "frontend" / "index.html"

sys.path.insert(0, str(BACKEND_DIR))

from auth import authenticate_user, register_user, validate_user_input
from case_advisor import build_case_action_plan, summarize_source
from document_export import build_case_plan_docx
from document_processing import (
    DocumentProcessingError,
    chunk_pdf_pages,
    extract_pdf_pages,
)
from database import (
    add_bookmark,
    delete_bookmark,
    delete_uploaded_document,
    delete_uploaded_documents_for_conversation,
    delete_uploaded_source,
    delete_user_session,
    get_audit_trail,
    get_db_connection,
    get_session_user_id,
    get_uploaded_document,
    get_uploaded_document_by_hash,
    get_source_by_id,
    get_user_documents,
    get_user_sources,
    get_user_bookmarks,
    init_db,
    log_audit_trail,
    save_uploaded_document,
    save_uploaded_source,
    save_user_session,
)
from domain_guard import (
    DOMAIN_LABELS,
    DOMAIN_SEMANTIC_ANCHORS,
    MAX_COSINE_DISTANCE,
    OUT_OF_SCOPE_PDF_MESSAGE,
    inspect_domain_text,
    validate_pdf_domain,
)

logger = logging.getLogger(__name__)

Domain = Literal["labour_law", "consumer_rights", "cyber_law", "all"]

DOMAIN_MAX_SECTIONS: dict[str, tuple[int, str]] = {
    "labour_law": (353, "বাংলাদেশ শ্রম আইন, ২০০৬"),
    "consumer_rights": (82, "ভোক্তা-অধিকার সংরক্ষণ আইন, ২০০৯"),
    "cyber_law": (51, "সাইবার সুরক্ষা আইন, ২০২৬"),
    "all": (353, "সংশ্লিষ্ট আইনসমূহ"),
}
BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
OUT_OF_SCOPE_MESSAGE = (
    "দুঃখিত, আমাদের সংকলিত ৫০৮টি আইনি ধারার (বাংলাদেশ শ্রম আইন ২০০৬, "
    "ভোক্তা অধিকার সংরক্ষণ আইন ২০০৯ এবং সাইবার সুরক্ষা আইন ২০২৬) মধ্যে "
    "আপনার প্রশ্নের বিষয়ে কোনো তথ্য নেই। অনুগ্রহ করে এই তিনটি আইনের "
    "আওতাভুক্ত কোনো প্রশ্ন করুন অথবা নিচের সাধারণ প্রশ্নগুলো (FAQ) থেকে নির্বাচন করুন।"
)
CHAT_REPLY = (
    "হ্যালো! আমি আইনসাথী, বাংলাদেশের নির্বাচিত আইনি তথ্য খুঁজে পেতে আপনার "
    "সহায়ক। আমি বাংলাদেশ শ্রম আইন ২০০৬, ভোক্তা অধিকার সংরক্ষণ আইন ২০০৯ "
    "এবং সাইবার সুরক্ষা আইন ২০২৬-এর সংকলিত ধারার ভিত্তিতে উত্তর দিই। "
    "আপনি স্বাভাবিক বাংলায় লিখে বা bn-BD ভয়েস ইনপুটে প্রশ্ন করতে পারেন।"
)
CHAT_INTENTS = (
    "হ্যালো", "হাই", "সালাম", "আসসালামু আলাইকুম",
    "তুমি কে", "আপনি কে", "কিভাবে সাহায্য করতে পারো", "কীভাবে সাহায্য করতে পারো",
    "কিভাবে সাহায্য করবেন", "কীভাবে সাহায্য করবেন", "hello", "hi", "hey",
    "who are you", "what can you do", "how can you help", "help", "assalamu alaikum",
    "salam", "tumi ke", "apni ke", "kivabe help", "kibhabe help",
)
SEARCH_STOPWORDS = {
    "আমি", "আমার", "আপনি", "কি", "কী", "কেন", "কিভাবে", "কীভাবে", "কত",
    "হবে", "হয়", "হয়", "করলে", "করিবার", "করে", "করতে", "করব", "করবো",
    "করণীয়", "করণীয়", "অনুযায়ী", "অনুযায়ী", "কোন", "কোনো", "জন্য",
    "সম্পর্কে", "নিয়ম", "নিয়ম", "আইন", "ধারা", "বলুন", "পারে", "পাবো",
}
GENERIC_RELEVANCE_TERMS = {
    "শ্রম", "শ্রমিক", "কর্মচারী", "ভোক্তা", "পণ্য", "সাইবার", "অনলাইন",
    "ইন্টারনেট", "আইডি", "আইন", "আইনের", "বাংলাদেশ", "ধারা", "হিসাব",
    "করনীয়", "করণীয়", "করণীয়", "ব্যবস্থা", "কীভাবে", "কিভাবে",
    "দণ্ড", "দন্ড", "শাস্তি", "জরিমানা", "penalty", "punishment", "fine",
}
TOPIC_RELEVANCE_RULES = (
    (
        "overtime",
        ("ওভারটাইম", "অধিকাল", "overtime", "extra hours", "অতিরিক্ত কাজ"),
        ("অধিকাল", "ওভারটাইম", "overtime"),
    ),
    (
        "expired_product",
        ("মেয়াদোত্তীর্ণ", "মেয়াদোত্তীর্ণ", "মেয়াদ উত্তীর্ণ", "মেয়াদ উত্তীর্ণ", "expired"),
        ("মেয়াদোত্তীর্ণ", "মেয়াদোত্তীর্ণ", "মেয়াদ উত্তীর্ণ", "মেয়াদ উত্তীর্ণ", "expired"),
    ),
    (
        "cyber_fraud",
        ("প্রতারণা", "প্রতারিত", "fraud", "scam", "phishing"),
        ("প্রতারণা", "fraud", "scam", "phishing"),
    ),
    (
        "cyber_hacking",
        ("হ্যাক", "অননুমোদিত প্রবেশ", "অনুপ্রবেশ", "hack", "hacking", "unauthorized access"),
        ("হ্যাক", "অননুমোদিত প্রবেশ", "অনুপ্রবেশ", "hack", "unauthorized access"),
    ),
    (
        "cyber_blackmail",
        ("ব্ল্যাকমেইল", "সেক্সটর্শন", "রিভেঞ্জ পর্ন", "যৌন হয়রানি", "যৌন হয়রানি", "blackmail", "sextortion"),
        ("ব্ল্যাকমেইল", "সেক্সটর্শন", "রিভেঞ্জ পর্ন", "যৌন হয়রানি", "যৌন হয়রানি", "blackmail", "sextortion"),
    ),
    (
        "consumer_adulteration",
        ("ভেজাল", "adulterat"),
        ("ভেজাল", "adulterat"),
    ),
    (
        "counterfeit_product",
        ("নকল পণ্য", "counterfeit", "fake product"),
        ("নকল পণ্য", "counterfeit", "fake product"),
    ),
    (
        "overpricing",
        ("অধিক মূল্যে", "বেশি দাম", "অতিরিক্ত দাম", "overprice", "overcharge"),
        ("মূল্যের অধিক", "অধিক মূল্যে", "বেশি দাম", "overprice", "overcharge"),
    ),
    (
        "unpaid_wages",
        (
            "বকেয়া মজুরি",
            "বকেয়া মজুরী",
            "বকেয়া বেতন",
            "মজুরি দেয়নি",
            "মজুরী দেয়নি",
            "বেতন দেয়নি",
            "বেতন আটকে",
            "মজুরি আটকে",
            "মজুরী আটকে",
            "বেতন পরিশোধ হয়নি",
            "মজুরি পরিশোধ হয়নি",
            "মজুরী পরিশোধ হয়নি",
            "unpaid wage",
            "unpaid wages",
            "unpaid salary",
            "salary withheld",
            "wages withheld",
        ),
        (
            "মজুরী হইতে কর্তন বা মজুরী বিলম্বে পরিশোধ",
            "মজুরি হইতে কর্তন বা মজুরি বিলম্বে পরিশোধ",
            "unpaid wage",
        ),
    ),
    (
        "termination",
        ("চাকরিচ্যুত", "বরখাস্ত", "চাকুরি হইতে অপসারণ", "termination", "dismissal"),
        ("চাকরিচ্যুত", "বরখাস্ত", "চাকুরি হইতে অপসারণ", "termination", "dismissal"),
    ),
    (
        "workplace_accident",
        ("কর্মস্থলের দুর্ঘটনা", "শ্রমিকের দুর্ঘটনা", "workplace accident"),
        ("দুর্ঘটনা", "accident"),
    ),
    (
        "maternity",
        ("মাতৃত্ব", "প্রসূতি", "maternity"),
        ("মাতৃত্ব", "প্রসূতি", "maternity"),
    ),
    (
        "appeal",
        ("আপিল", "আপীল", "appeal"),
        ("আপিল", "আপীল", "appeal"),
    ),
    (
        "civil_remedy",
        ("ক্ষতিপূরণ", "দেওয়ানি", "দেওয়ানি", "civil remedy", "compensation"),
        ("প্রতিকার", "ক্ষতিপূরণ", "দেওয়ানি", "দেওয়ানি", "civil remedy", "compensation"),
    ),
)
ACTION_PROCEDURE_SECTIONS = {
    ("cyber_law", "40"): {"cyber_fraud", "cyber_hacking", "cyber_blackmail"},
    (
        "consumer_rights",
        "66",
    ): {"expired_product", "consumer_adulteration", "counterfeit_product", "overpricing"},
}
SECTION_SCOPE_REQUIREMENTS = {
    ("cyber_law", "17"): (
        "গুরুত্বপূর্ণ তথ্য পরিকাঠামো",
        "গুরুত্বপূর্ণ তথ্য অবকাঠামো",
        "critical information infrastructure",
        "critical infrastructure",
        "cii",
    ),
}
ACTION_INTENT_MARKERS = (
    "করণীয়",
    "করণীয়",
    "কি করব",
    "কী করব",
    "কি করবো",
    "কী করবো",
    "কী পদক্ষেপ",
    "কোন পদক্ষেপ",
    "অভিযোগ",
    "আইনি নোটিশ",
    "প্রতিকার",
    "what should i do",
    "what can i do",
    "how do i file",
    "how to complain",
    "what steps",
    "legal notice",
    "complaint",
    "remedy",
)

_vector_collection = None
_document_collection = None
_vector_store_module = None
_vector_collection_lock = threading.Lock()
_vector_store_module_lock = threading.Lock()
MAX_SOURCE_FILE_BYTES = 20 * 1024 * 1024
MAX_SOURCE_PAGES = 100
MAX_EXTRACTED_TEXT_CHARS = 250_000
SOURCE_CHUNK_SIZE = 1200
SOURCE_CHUNK_OVERLAP = 160
MAX_DOCUMENT_FILE_BYTES = 20 * 1024 * 1024
MAX_DOCUMENT_PAGES = 100
MAX_DOCUMENT_UPLOADS = 5
DOCUMENT_UPLOAD_DIR = BACKEND_DIR / "data" / "user_documents"
DOCUMENT_RETRIEVAL_COUNT = 5
MIN_DOCUMENT_SIMILARITY = 0.48
DOCUMENT_SESSION_COOKIE = "ainsathi_session"
DOCUMENT_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(
    title="Statute-Grounded Bangla Legal Assistant API",
    version="1.0.0",
    lifespan=lifespan,
)

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RegisterRequest(BaseModel):
    full_name: Annotated[str, Field(min_length=1, max_length=200)]
    email: Annotated[str, Field(min_length=3, max_length=320)]
    password: Annotated[str, Field(min_length=1, max_length=128)]
    confirm_password: Annotated[str, Field(min_length=1, max_length=128)]
    role: Literal["citizen", "lawyer", "student"] = "citizen"


class LoginRequest(BaseModel):
    email: Annotated[str, Field(min_length=1, max_length=320)]
    password: Annotated[str, Field(min_length=1, max_length=128)]


class SearchRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=3000)]
    domain: Domain = "all"
    top_k: int = Field(default=3, ge=1, le=6)
    user_id: int | None = Field(default=None, ge=1)


class CaseAnalysisRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=3000)]
    domain: Domain = "all"
    top_k: int = Field(default=3, ge=1, le=6)
    user_id: int = Field(ge=1)
    source_id: int | None = Field(default=None, ge=1)


class CasePlanExportRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=3000)]
    user_id: int = Field(ge=1)
    analysis: dict[str, Any]


class DocumentHistoryTurn(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=3000)]


class DocumentAskRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=3000)]
    user_id: int = Field(ge=1)
    conversation_id: Annotated[str, Field(min_length=8, max_length=128)]
    document_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list,
        max_length=MAX_DOCUMENT_UPLOADS,
    )
    history: list[DocumentHistoryTurn] = Field(default_factory=list, max_length=4)


class DraftRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=3000)]
    domain: Domain
    document_type: Literal["legal_notice", "complaint"] = "complaint"
    applicant_name: Annotated[str, Field(min_length=1, max_length=200)] = (
        "আবেদনকারীর নাম"
    )
    user_id: int | None = Field(default=None, ge=1)


class BookmarkRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    user_id: int = Field(ge=1)
    domain_bn: Annotated[str, Field(min_length=1, max_length=200)]
    act_name: Annotated[str, Field(min_length=1, max_length=300)]
    section_number: Annotated[str, Field(min_length=1, max_length=40)]
    section_title: Annotated[str, Field(min_length=1, max_length=500)]
    content: Annotated[str, Field(min_length=1, max_length=20000)]
    legal_status: Annotated[str, Field(min_length=1, max_length=100)]


def get_vector_collection():
    """Load the statute collection only when a search request needs it."""
    global _vector_collection
    if _vector_collection is None:
        with _vector_collection_lock:
            if _vector_collection is None:
                _vector_collection = _get_vector_store_module().get_vector_collection()
    return _vector_collection


def _get_vector_store_module():
    global _vector_store_module
    if _vector_store_module is None:
        with _vector_store_module_lock:
            if _vector_store_module is None:
                spec = importlib.util.spec_from_file_location(
                    "statute_vector_store", VECTOR_STORE_SCRIPT
                )
                if spec is None or spec.loader is None:
                    raise RuntimeError(
                        f"Unable to load vector-store module: {VECTOR_STORE_SCRIPT}"
                    )
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                _vector_store_module = module
    return _vector_store_module


def get_document_collection():
    """Load the isolated uploaded-document collection when required."""
    global _document_collection
    if _document_collection is None:
        with _vector_collection_lock:
            if _document_collection is None:
                _document_collection = (
                    _get_vector_store_module().get_document_collection()
                )
    return _document_collection


def _result_message(result: object, default: str) -> str:
    if isinstance(result, dict):
        message = result.get("message")
        return str(message) if message else default
    if isinstance(result, (tuple, list)) and len(result) > 1:
        return str(result[1])
    return default


def _validation_outcome(result: object) -> tuple[bool, str]:
    if isinstance(result, (tuple, list)) and len(result) >= 2:
        return bool(result[0]), str(result[1])
    if isinstance(result, dict):
        valid = result.get("valid", result.get("status") == "success")
        return bool(valid), _result_message(result, "ইনপুট যাচাই করা যায়নি।")
    if isinstance(result, bool):
        return result, "ইনপুট যাচাই করা যায়নি।"
    if isinstance(result, str):
        return not result, result or "ভ্যালিডেশন সফল।"
    return False, "ইনপুট যাচাই করা যায়নি।"


def _registration_outcome(result: object) -> tuple[bool, str]:
    if isinstance(result, dict):
        succeeded = result.get("status") == "success" or result.get("success") is True
        return succeeded, _result_message(result, "নিবন্ধন ব্যর্থ হয়েছে।")
    if isinstance(result, (tuple, list)) and result:
        return bool(result[0]), _result_message(result, "নিবন্ধন ব্যর্থ হয়েছে।")
    return False, "নিবন্ধন ব্যর্থ হয়েছে।"


def _login_user(result: object) -> dict[str, object] | None:
    user: object = None
    if isinstance(result, dict):
        if result.get("status") != "success" and result.get("success") is not True:
            return None
        user = result.get("user")
        if user is None and "id" in result:
            user = result
    elif isinstance(result, (tuple, list)) and len(result) > 1 and result[0] is True:
        user = result[1]

    if not isinstance(user, dict):
        return None
    user_id = user.get("id", user.get("user_id"))
    full_name = user.get("full_name", user.get("name"))
    email = user.get("email")
    if user_id is None or not full_name or not email:
        return None
    return {
        "id": user_id,
        "full_name": str(full_name),
        "email": str(email),
        "role": str(user.get("role") or "citizen"),
    }


def _require_user(user_id: int) -> str:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="ব্যবহারকারী পাওয়া যায়নি।")
    return str(row["role"] or "citizen")


def _require_document_session(user_id: int, token: str | None) -> None:
    if not token:
        raise HTTPException(
            status_code=401,
            detail="ব্যক্তিগত PDF ব্যবহারের জন্য আবার লগইন করুন।",
        )
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session_user_id = get_session_user_id(token_hash)
    if session_user_id != user_id:
        raise HTTPException(
            status_code=401,
            detail="লগইন সেশনটি অবৈধ বা মেয়াদোত্তীর্ণ। আবার লগইন করুন।",
        )


def _normalized_legal_status(value: object) -> str:
    source = str(value or "").lower()
    if not source.strip():
        return "Unknown"
    if any(term in source for term in ("repeal", "বিলুপ্ত", "রহিত")):
        return "Repealed"
    if any(term in source for term in ("amend", "সংশোধ")):
        return "Amended"
    return "Active"


def _confidence(distance: object) -> float:
    try:
        value = float(distance)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(100.0, (1.0 - value) * 100)), 1)


def _is_chat_intent(query: str) -> bool:
    normalized = re.sub(r"[^\w]+", " ", query.casefold()).strip()
    padded_query = f" {normalized} "
    return any(
        f" {re.sub(r'[^\w]+', ' ', intent.casefold()).strip()} " in padded_query
        for intent in CHAT_INTENTS
    )


def _search_terms(text: str) -> set[str]:
    normalized = text.casefold().replace("মেয়াদোত্তীর্ণ", "মেয়াদ উত্তীর্ণ")
    normalized = normalized.replace("মেয়াদোত্তীর্ণ", "মেয়াদ উত্তীর্ণ")
    terms: set[str] = set()
    for token in re.findall(r"[\u0980-\u09FF]+|[a-z0-9]+", normalized):
        if token in SEARCH_STOPWORDS:
            continue
        if token in {"ওভারটাইম", "overtime"}:
            token = "অধিকাল"
        elif token in {"হ্যাকিং", "হ্যাক", "হ্যাকড"}:
            token = "হ্যাক"
        elif token in {"প্রতারণার", "প্রতারণায়", "প্রতারণায়"}:
            token = "প্রতারণা"
        elif token in {"অনলাইনে", "অনলাইন"}:
            token = "অনলাইন"
        elif token.startswith("পণ্য"):
            token = "পণ্য"
        elif token.startswith("বিক্র"):
            token = "বিক্রয়"
        elif token.startswith(("দণ্ড", "দন্ড", "শাস্তি")):
            token = "দণ্ড"
        terms.add(token)
    return terms


def _title_relevance(query: str, section_title: object) -> int:
    return len(_search_terms(query) & _search_terms(str(section_title or "")))


def _requests_action_plan(query: str) -> bool:
    normalized = re.sub(r"\s+", " ", query.casefold())
    return any(marker in normalized for marker in ACTION_INTENT_MARKERS)


def _section_scope_matches(statute: dict[str, Any], query: str) -> bool:
    section_match = re.match(
        r"[০-৯0-9]+", str(statute.get("section_number") or "")
    )
    if section_match is None:
        return False
    section_number = section_match.group().translate(BENGALI_DIGITS)
    requirements = SECTION_SCOPE_REQUIREMENTS.get(
        (str(statute.get("domain") or ""), section_number)
    )
    if requirements is None:
        return True
    normalized_query = query.casefold()
    return any(marker in normalized_query for marker in requirements)


def _select_relevant_statutes(
    query: str, statutes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    normalized_query = re.sub(r"\s+", " ", query.casefold())
    matched_rules = [
        (name, statute_markers)
        for name, query_markers, statute_markers in TOPIC_RELEVANCE_RULES
        if any(marker in normalized_query for marker in query_markers)
    ]
    explicit_section = re.search(r"ধারা\s*([০-৯0-9]+)", query)
    if explicit_section:
        requested_number = int(explicit_section.group(1).translate(BENGALI_DIGITS))
        exact = [
            statute
            for statute in statutes
            if (match := re.match(r"[০-৯0-9]+", str(statute.get("section_number") or "")))
            and int(match.group().translate(BENGALI_DIGITS)) == requested_number
        ]
        if exact:
            for _, markers in matched_rules:
                if not any(
                    any(
                        marker in str(statute.get("section_title") or "").casefold()
                        for marker in markers
                    )
                    for statute in exact
                ):
                    return []
            return exact
        return []

    if matched_rules:
        topic_matches: dict[str, list[dict[str, Any]]] = {
            name: [] for name, _ in matched_rules
        }
        for statute in statutes:
            title = str(statute.get("section_title") or "").casefold()
            if not _section_scope_matches(statute, query):
                continue
            for name, statute_markers in matched_rules:
                if any(marker in title for marker in statute_markers):
                    topic_matches[name].append(statute)
        if any(not matches for matches in topic_matches.values()):
            return []
        selected: list[dict[str, Any]] = []
        for matches in topic_matches.values():
            for statute in matches:
                if statute not in selected:
                    selected.append(statute)
        if _requests_action_plan(query):
            matched_topic_names = {name for name, _ in matched_rules}
            for statute in statutes:
                section_match = re.match(
                    r"[০-৯0-9]+", str(statute.get("section_number") or "")
                )
                if section_match is None:
                    continue
                section_number = section_match.group().translate(BENGALI_DIGITS)
                required_topics = ACTION_PROCEDURE_SECTIONS.get(
                    (str(statute.get("domain") or ""), section_number), set()
                )
                if (
                    matched_topic_names.intersection(required_topics)
                    and _section_scope_matches(statute, query)
                    and statute not in selected
                ):
                    selected.append(statute)
        return selected

    query_terms = _search_terms(query) - GENERIC_RELEVANCE_TERMS
    if not query_terms:
        return []
    selected_with_scores: list[tuple[int, int, float, dict[str, Any]]] = []
    for statute in statutes:
        if not _section_scope_matches(statute, query):
            continue
        title_terms = _search_terms(str(statute.get("section_title") or ""))
        content_terms = _search_terms(str(statute.get("content") or ""))
        title_hits = len(query_terms & title_terms)
        content_hits = len(query_terms & content_terms)
        if title_hits >= 2 or (title_hits >= 1 and content_hits >= 1):
            selected_with_scores.append(
                (
                    title_hits,
                    content_hits,
                    float(statute.get("confidence") or 0.0),
                    statute,
                )
            )
    selected_with_scores.sort(
        key=lambda item: (-item[0], -item[1], -item[2])
    )
    return [item[3] for item in selected_with_scores]


def _out_of_scope(request: SearchRequest, query: str) -> dict[str, object]:
    log_audit_trail(
        request.user_id,
        query,
        "কোনো প্রাসঙ্গিক ধারা পাওয়া যায়নি",
        "No Info (Out of Scope)",
        OUT_OF_SCOPE_MESSAGE,
    )
    return {
        "status": "out_of_scope",
        "heading": "এই বিষয়ে কোনো তথ্য নেই",
        "message": OUT_OF_SCOPE_MESSAGE,
        "results": [],
    }


def _needs_verification(
    request: SearchRequest, query: str, source_only: bool = False
) -> dict[str, object]:
    message = (
        "আপলোড করা PDF-এ প্রশ্নটির সঙ্গে মেলে এমন পাঠ্যাংশ পাওয়া যায়নি। "
        "তাই PDF-ভিত্তিক বিশ্লেষণ অনুমান করে তৈরি করা হয়নি। নির্দিষ্ট পৃষ্ঠা বা "
        "বিষয় উল্লেখ করে আবার চেষ্টা করুন।"
        if source_only
        else "প্রশ্নের প্রতিটি আইনি বিষয়কে সমর্থন করে এমন পর্যাপ্ত নির্দিষ্ট ধারা "
        "পাওয়া যায়নি। অনুমানভিত্তিক উত্তর দেওয়া হয়নি। প্রশ্নটি একটি বিষয়, "
        "ঘটনার প্রয়োজনীয় তথ্য এবং প্রযোজ্য আইন উল্লেখ করে আবার লিখুন; মূল আইন "
        "বা আইনজীবীর মাধ্যমে যাচাই করুন।"
    )
    log_audit_trail(
        request.user_id,
        query,
        "যথেষ্ট প্রাসঙ্গিক আইনি প্রমাণ পাওয়া যায়নি",
        "Needs Verification",
        message,
    )
    return {
        "status": "needs_verification",
        "heading": "আরও যাচাই প্রয়োজন",
        "message": message,
        "results": [],
    }


def _section_out_of_range(query: str, domain: str) -> tuple[str, int, str] | None:
    match = re.search(r"ধারা\s*([০-৯0-9]+)", query)
    if match is None:
        return None
    raw_number = match.group(1)
    section_number = int(raw_number.translate(BENGALI_DIGITS))
    maximum, domain_name = DOMAIN_MAX_SECTIONS[domain]
    if section_number < 1 or section_number > maximum:
        return raw_number, maximum, domain_name
    return None


def _run_search(
    request: SearchRequest,
    context_text: str = "",
    log_success: bool = True,
    conversational_intents: bool = True,
) -> dict[str, object]:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="অনুসন্ধানের জন্য প্রশ্ন লিখুন।")
    if request.user_id is not None:
        _require_user(request.user_id)

    if conversational_intents and _is_chat_intent(query):
        return {"status": "chat", "message": CHAT_REPLY, "results": []}

    rejected = _section_out_of_range(query, request.domain)
    if rejected is not None:
        return _out_of_scope(request, query)

    has_section_reference = re.search(r"ধারা\s*[০-৯0-9]+", query) is not None
    preferred_domain = request.domain if request.domain != "all" else None
    query_decision = inspect_domain_text(
        query,
        preferred_domain=preferred_domain,
        allow_section_reference=has_section_reference,
    )
    if query_decision.reason not in {"supported_domain", "explicit_section_reference"}:
        if not (
            context_text
            and query_decision.reason == "no_supported_domain_signal"
            and not query_decision.blocked_topics
        ):
            return _out_of_scope(request, query)

    scope_text = " ".join(part for part in (query, context_text) if part).strip()
    scope_decision = query_decision
    if query_decision.reason == "no_supported_domain_signal" and context_text:
        scope_decision = inspect_domain_text(
            scope_text,
            preferred_domain=preferred_domain,
            allow_section_reference=has_section_reference,
        )
    if not scope_decision.allowed:
        return _out_of_scope(request, query)
    search_domains = (
        {request.domain}
        if request.domain != "all"
        else set(scope_decision.domains)
    )
    if not search_domains:
        return _out_of_scope(request, query)

    retrieval_query = query
    if (
        context_text
        and query_decision.reason == "no_supported_domain_signal"
        and not has_section_reference
    ):
        selected_domain = request.domain
        retrieval_query = (
            DOMAIN_SEMANTIC_ANCHORS[selected_domain][0]
            if selected_domain in DOMAIN_SEMANTIC_ANCHORS
            else context_text[:3000]
        )

    query_kwargs: dict[str, object] = {
        "query_texts": [retrieval_query[:3000]],
        "include": ["documents", "metadatas", "distances"],
    }
    if len(search_domains) == 1:
        query_kwargs["where"] = {"domain": next(iter(search_domains))}
    elif search_domains:
        query_kwargs["where"] = {"domain": {"$in": sorted(search_domains)}}

    try:
        collection = get_vector_collection()
        query_kwargs["n_results"] = collection.count()
        raw_results = collection.query(**query_kwargs)
    except Exception as exc:
        logger.exception("Vector search failed")
        raise HTTPException(
            status_code=503,
            detail="আইনি অনুসন্ধান সেবা বর্তমানে পাওয়া যাচ্ছে না। পরে আবার চেষ্টা করুন।",
        ) from exc

    documents_by_query = raw_results.get("documents") or []
    metadatas_by_query = raw_results.get("metadatas") or []
    distances_by_query = raw_results.get("distances") or []
    documents = documents_by_query[0] if documents_by_query else []
    metadatas = metadatas_by_query[0] if metadatas_by_query else []
    distances = distances_by_query[0] if distances_by_query else []
    if not documents:
        return _out_of_scope(request, query)

    ranked_results: list[tuple[int, float, dict[str, object]]] = []
    for index, document in enumerate(documents):
        metadata = metadatas[index] if index < len(metadatas) else {}
        distance = distances[index] if index < len(distances) else 2.0
        metadata = metadata or {}
        domain = str(metadata.get("domain") or "")
        section_number = str(metadata.get("section_number") or "")
        section_match = re.match(r"[০-৯0-9]+", section_number)
        if section_match is None:
            continue
        numeric_section = int(section_match.group().translate(BENGALI_DIGITS))
        maximum = DOMAIN_MAX_SECTIONS.get(domain, (0, ""))[0]
        if (
            float(distance) > MAX_COSINE_DISTANCE
            or domain not in DOMAIN_LABELS
            or domain not in search_domains
            or numeric_section < 1
            or numeric_section > maximum
            or not document
        ):
            continue
        status = _normalized_legal_status(metadata.get("legal_status"))
        result = {
            "domain": domain,
            "domain_bn": metadata.get("domain_bn", ""),
            "act_name": metadata.get("act_name", ""),
            "chapter": metadata.get("chapter", ""),
            "section_number": section_number,
            "section_title": metadata.get("section_title", ""),
            "legal_status": status,
            "source_legal_status": metadata.get("legal_status", ""),
            "amendment_provenance": metadata.get("amendment_provenance", ""),
            "content": document,
            "confidence": _confidence(distance),
        }
        ranked_results.append(
            (
                _title_relevance(retrieval_query, metadata.get("section_title")),
                float(distance),
                result,
            )
        )

    if not ranked_results:
        return _out_of_scope(request, query)

    ranked_results.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    candidates = [candidate[2] for candidate in ranked_results]
    relevant_results = _select_relevant_statutes(query, candidates)
    if not relevant_results:
        return _needs_verification(request, query)
    if (
        request.domain == "all"
        and re.search(r"ধারা\s*[০-৯0-9]+", query)
        and len({str(item.get("domain") or "") for item in relevant_results}) > 1
    ):
        return _needs_verification(request, query)
    results = relevant_results[: request.top_k]
    confidence = float(results[0]["confidence"])
    if request.user_id is not None and log_success:
        top = results[0]
        log_audit_trail(
            request.user_id,
            query,
            f"ধারা {top['section_number']}: {top['section_title']}",
            str(top["legal_status"]),
            str(top["content"]),
        )

    return {
        "status": "success",
        "confidence": confidence,
        "results": results,
    }


def _chunk_pdf_pages(page_texts: list[tuple[int, str]]) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    for page_number, page_text in page_texts:
        start = 0
        while start < len(page_text):
            end = min(start + SOURCE_CHUNK_SIZE, len(page_text))
            if end < len(page_text):
                boundary = page_text.rfind(" ", start, end)
                if boundary > start + SOURCE_CHUNK_SIZE // 2:
                    end = boundary
            text = page_text[start:end].strip()
            if text:
                chunks.append({"page_number": page_number, "text": text})
            if end >= len(page_text):
                break
            start = max(start + 1, end - SOURCE_CHUNK_OVERLAP)
    return chunks


def _source_metadata(source: dict[str, object]) -> dict[str, object]:
    return {
        key: source[key]
        for key in (
            "id",
            "filename",
            "detected_domain",
            "detected_domain_bn",
            "page_count",
            "created_at",
        )
    }


def _audit_case_analysis(
    user_id: int, query: str, analysis: dict[str, object]
) -> None:
    citations = analysis.get("statute_citations") or []
    citation_refs = [
        f"ধারা {citation.get('section_number')}: {citation.get('section_title')}"
        for citation in citations
        if isinstance(citation, dict)
    ]
    log_audit_trail(
        user_id,
        query,
        " | ".join(citation_refs) or "আইনি সূত্র সংরক্ষিত হয়নি",
        f"Case Analysis: {analysis.get('case_type_bn', 'Unknown')}",
        json.dumps(analysis, ensure_ascii=False),
    )


@app.get("/")
def serve_frontend() -> FileResponse:
    if not FRONTEND_INDEX.is_file():
        raise HTTPException(status_code=404, detail="Frontend page was not found.")
    return FileResponse(FRONTEND_INDEX, media_type="text/html")


@app.post("/api/register")
def api_register(request: RegisterRequest) -> dict[str, str]:
    if request.password != request.confirm_password:
        raise HTTPException(
            status_code=400, detail="পাসওয়ার্ড এবং নিশ্চিতকরণ পাসওয়ার্ড মিলছে না।"
        )
    valid, validation_message = _validation_outcome(
        validate_user_input(
            request.full_name.strip(), request.email.strip(), request.password
        )
    )
    if not valid:
        raise HTTPException(status_code=400, detail=validation_message)

    succeeded, message = _registration_outcome(
        register_user(
            request.full_name.strip(),
            request.email.strip(),
            request.password,
            request.role,
        )
    )
    if not succeeded:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.post("/api/login")
def api_login(request: LoginRequest, response: Response) -> dict[str, object]:
    result = authenticate_user(request.email.strip(), request.password)
    user = _login_user(result)
    if user is None:
        message = _result_message(result, "ইমেইল অথবা পাসওয়ার্ড সঠিক নয়।")
        raise HTTPException(status_code=401, detail=message)
    session_token = secrets.token_urlsafe(32)
    save_user_session(
        hashlib.sha256(session_token.encode("utf-8")).hexdigest(),
        int(user["id"]),
        time.time() + DOCUMENT_SESSION_TTL_SECONDS,
    )
    response.set_cookie(
        DOCUMENT_SESSION_COOKIE,
        session_token,
        max_age=DOCUMENT_SESSION_TTL_SECONDS,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="strict",
        path="/api",
    )
    return {"status": "success", "user": user}


@app.post("/api/logout")
def api_logout(
    response: Response,
    session_token: Annotated[
        str | None, Cookie(alias=DOCUMENT_SESSION_COOKIE)
    ] = None,
) -> dict[str, str]:
    if session_token:
        delete_user_session(hashlib.sha256(session_token.encode("utf-8")).hexdigest())
    response.delete_cookie(
        DOCUMENT_SESSION_COOKIE,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="strict",
        path="/api",
    )
    return {"status": "success", "message": "লগআউট সম্পন্ন হয়েছে।"}


@app.post("/api/search")
def api_search(request: SearchRequest) -> dict[str, object]:
    result = _run_search(request, log_success=False)
    if result.get("status") != "success":
        return result
    results = result.get("results") or []
    if request.user_id is not None:
        if _requests_action_plan(request.query):
            analysis = build_case_action_plan(request.query, results)
            result.update(analysis)
            _audit_case_analysis(request.user_id, request.query, analysis)
        else:
            top = results[0]
            log_audit_trail(
                request.user_id,
                request.query,
                " | ".join(
                    f"ধারা {item.get('section_number')}: {item.get('section_title')}"
                    for item in results
                ),
                str(top.get("legal_status") or "Unknown"),
                str(top.get("content") or ""),
            )
    elif _requests_action_plan(request.query):
        result.update(build_case_action_plan(request.query, results))
    return result


def _document_metadata(document: dict[str, Any]) -> dict[str, object]:
    return {
        key: document[key]
        for key in (
            "document_id",
            "filename",
            "size_bytes",
            "page_count",
            "created_at",
        )
    }


def _document_path(user_id: int, document_id: str) -> Path:
    return DOCUMENT_UPLOAD_DIR / str(user_id) / f"{document_id}.pdf"


def _validate_conversation_id(conversation_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", conversation_id):
        raise HTTPException(status_code=422, detail="কথোপকথনের ID সঠিক নয়।")


@app.post("/api/documents/upload")
async def api_upload_document(
    file: Annotated[UploadFile, File()],
    user_id: Annotated[int, Form(gt=0)],
    conversation_id: Annotated[str, Form(min_length=8, max_length=128)],
    session_token: Annotated[
        str | None, Cookie(alias=DOCUMENT_SESSION_COOKIE)
    ] = None,
) -> dict[str, object]:
    _require_document_session(user_id, session_token)
    _require_user(user_id)
    _validate_conversation_id(conversation_id)
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="শুধুমাত্র PDF ফাইল আপলোড করুন।")
    if (file.content_type or "").lower() not in {
        "application/pdf",
        "application/x-pdf",
        "application/octet-stream",
    }:
        raise HTTPException(
            status_code=400,
            detail="ফাইলের MIME type PDF নয়। বৈধ PDF ফাইল নির্বাচন করুন।",
        )
    documents = get_user_documents(user_id, conversation_id)
    if len(documents) >= MAX_DOCUMENT_UPLOADS:
        raise HTTPException(
            status_code=413,
            detail=f"একটি কথোপকথনে সর্বোচ্চ {MAX_DOCUMENT_UPLOADS}টি PDF যোগ করা যায়।",
        )

    try:
        content = await file.read(MAX_DOCUMENT_FILE_BYTES + 1)
    finally:
        await file.close()
    if len(content) > MAX_DOCUMENT_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="PDF ফাইলটি ২০ MB-এর বেশি; ছোট ফাইল আপলোড করুন।",
        )

    try:
        page_count, page_texts = extract_pdf_pages(
            content,
            max_pages=MAX_DOCUMENT_PAGES,
        )
    except DocumentProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content_sha256 = hashlib.sha256(content).hexdigest()
    duplicate = get_uploaded_document_by_hash(
        user_id,
        conversation_id,
        content_sha256,
    )
    if duplicate is not None:
        return {
            "status": "success",
            "message": "এই PDF আগে থেকেই এই কথোপকথনে যুক্ত আছে।",
            "duplicate": True,
            "document": _document_metadata(duplicate),
        }

    document_id = str(uuid.uuid4())
    chunks = chunk_pdf_pages(document_id, filename, page_texts)
    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="PDF থেকে কোনো অনুসন্ধানযোগ্য লেখা তৈরি করা যায়নি।",
        )

    document_path = _document_path(user_id, document_id)
    chunk_ids = [str(chunk["chunk_id"]) for chunk in chunks]
    collection = None
    try:
        document_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(document_path.parent, 0o700)
        descriptor = os.open(
            document_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stored_pdf:
            stored_pdf.write(content)
        collection = get_document_collection()
        collection.upsert(
            ids=chunk_ids,
            documents=[str(chunk["text"]) for chunk in chunks],
            metadatas=[
                {
                    "document_id": document_id,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "filename": filename,
                    "page_number": int(chunk["page_number"]),
                    "section_title": str(chunk["section_title"]),
                    "chunk_index": int(chunk["chunk_index"]),
                }
                for chunk in chunks
            ],
        )
        document = save_uploaded_document(
            document_id=document_id,
            user_id=user_id,
            conversation_id=conversation_id,
            filename=filename,
            content_sha256=content_sha256,
            size_bytes=len(content),
            page_count=page_count,
        )
    except Exception as exc:
        logger.exception("PDF document indexing failed for user %s", user_id)
        try:
            if collection is not None:
                collection.delete(ids=chunk_ids)
        except Exception:
            logger.exception("Failed to clean up partial PDF index for user %s", user_id)
        try:
            document_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Failed to remove partial PDF file for user %s", user_id)
        try:
            delete_uploaded_document(document_id, user_id, conversation_id)
        except Exception:
            logger.exception("Failed to remove partial PDF metadata for user %s", user_id)
        raise HTTPException(
            status_code=503,
            detail="PDF-এর লেখা সংরক্ষণ ও অনুসন্ধান-সূচিতে যোগ করা যায়নি। পরে আবার চেষ্টা করুন।",
        ) from exc

    return {
        "status": "success",
        "message": "PDF পড়া হয়েছে এবং এই কথোপকথনের জন্য প্রশ্ন করার উপযোগী।",
        "duplicate": False,
        "document": _document_metadata(document),
    }


@app.get("/api/documents")
def api_get_documents(
    user_id: Annotated[int, Query(ge=1)],
    conversation_id: Annotated[str, Query(min_length=8, max_length=128)],
    session_token: Annotated[
        str | None, Cookie(alias=DOCUMENT_SESSION_COOKIE)
    ] = None,
) -> list[dict[str, object]]:
    _require_document_session(user_id, session_token)
    _require_user(user_id)
    _validate_conversation_id(conversation_id)
    return [
        _document_metadata(document)
        for document in get_user_documents(user_id, conversation_id)
    ]


@app.delete("/api/documents/{document_id}")
def api_delete_document(
    document_id: Annotated[
        str, Field(min_length=36, max_length=36, pattern=r"^[a-f0-9-]{36}$")
    ],
    user_id: Annotated[int, Query(ge=1)],
    conversation_id: Annotated[str, Query(min_length=8, max_length=128)],
    session_token: Annotated[
        str | None, Cookie(alias=DOCUMENT_SESSION_COOKIE)
    ] = None,
) -> dict[str, str]:
    _require_document_session(user_id, session_token)
    _require_user(user_id)
    _validate_conversation_id(conversation_id)
    document = get_uploaded_document(document_id, user_id, conversation_id)
    if document is None:
        raise HTTPException(status_code=404, detail="এই কথোপকথনের PDF পাওয়া যায়নি।")
    try:
        get_document_collection().delete(
            where={
                "$and": [
                    {"document_id": document_id},
                    {"user_id": user_id},
                    {"conversation_id": conversation_id},
                ]
            }
        )
        _document_path(user_id, document_id).unlink(missing_ok=True)
    except Exception as exc:
        logger.exception("PDF document deletion failed for user %s", user_id)
        raise HTTPException(
            status_code=503,
            detail="PDF এবং এর অনুসন্ধান-তথ্য সম্পূর্ণভাবে মুছে ফেলা যায়নি।",
        ) from exc
    if not delete_uploaded_document(document_id, user_id, conversation_id):
        raise HTTPException(
            status_code=503,
            detail="PDF-এর তথ্য ডেটাবেজ থেকে মুছে ফেলা যায়নি।",
        )
    return {"status": "success", "message": "PDF ও এর অনুসন্ধান-তথ্য মুছে ফেলা হয়েছে।"}


@app.delete("/api/documents/conversations/{conversation_id}")
def api_delete_conversation_documents(
    conversation_id: Annotated[str, Field(min_length=8, max_length=128)],
    user_id: Annotated[int, Query(ge=1)],
    session_token: Annotated[
        str | None, Cookie(alias=DOCUMENT_SESSION_COOKIE)
    ] = None,
) -> dict[str, object]:
    _require_document_session(user_id, session_token)
    _require_user(user_id)
    _validate_conversation_id(conversation_id)
    documents = get_user_documents(user_id, conversation_id)
    if not documents:
        return {
            "status": "success",
            "deleted_count": 0,
            "message": "এই কথোপকথনে কোনো PDF ছিল না।",
        }
    try:
        get_document_collection().delete(
            where={
                "$and": [
                    {"user_id": user_id},
                    {"conversation_id": conversation_id},
                ]
            }
        )
        for document in documents:
            _document_path(user_id, str(document["document_id"])).unlink(
                missing_ok=True
            )
    except Exception as exc:
        logger.exception(
            "PDF cleanup for conversation failed for user %s", user_id
        )
        raise HTTPException(
            status_code=503,
            detail="কথোপকথনের PDF ও অনুসন্ধান-তথ্য সম্পূর্ণভাবে মুছে ফেলা যায়নি।",
        ) from exc
    deleted = delete_uploaded_documents_for_conversation(
        user_id,
        conversation_id,
    )
    return {
        "status": "success",
        "deleted_count": len(deleted),
        "message": "কথোপকথনের PDF ও অনুসন্ধান-তথ্য মুছে ফেলা হয়েছে।",
    }


def _document_query_terms(text: str) -> set[str]:
    stopwords = {
        "the", "and", "for", "with", "what", "which", "where", "when",
        "this", "that", "from", "about", "does", "into", "have", "এর",
        "এবং", "করে", "কী", "কি", "কেন", "কিভাবে", "কীভাবে", "বলুন",
        "ব্যাখ্যা", "করুন", "হলো", "হয়", "হয়", "আছে", "থেকে",
    }
    return {
        token
        for token in re.findall(r"[\u0980-\u09FF]+|[a-z0-9]+", text.casefold())
        if len(token) > 2 and token not in stopwords
    }


def _document_search_query(
    query: str,
    history: list[DocumentHistoryTurn],
) -> str:
    follow_up_markers = (
        "আগের", "উপরের", "ওটা", "এটা", "সেটা", "আরও বিস্তারিত",
        "আরো বিস্তারিত", "previous", "above", "that", "it", "more detail",
        "explain further",
    )
    if history and any(marker in query.casefold() for marker in follow_up_markers):
        return f"{history[-1].query}\n{query}"
    return query


@app.post("/api/documents/ask")
def api_ask_document(
    request: DocumentAskRequest,
    session_token: Annotated[
        str | None, Cookie(alias=DOCUMENT_SESSION_COOKIE)
    ] = None,
) -> dict[str, object]:
    _require_document_session(request.user_id, session_token)
    _require_user(request.user_id)
    _validate_conversation_id(request.conversation_id)
    documents = get_user_documents(request.user_id, request.conversation_id)
    if request.document_ids:
        allowed_ids = {str(document["document_id"]) for document in documents}
        if not set(request.document_ids).issubset(allowed_ids):
            raise HTTPException(
                status_code=404,
                detail="নির্বাচিত PDF এই ব্যবহারকারী বা কথোপকথনের নয়।",
            )
        documents = [
            document
            for document in documents
            if document["document_id"] in set(request.document_ids)
        ]
    if not documents:
        raise HTTPException(
            status_code=404,
            detail="এই কথোপকথনে কোনো PDF যুক্ত নেই। আগে একটি PDF আপলোড করুন।",
        )

    where: dict[str, object] = {
        "$and": [
            {"user_id": request.user_id},
            {"conversation_id": request.conversation_id},
            {
                "document_id": {
                    "$in": [str(document["document_id"]) for document in documents]
                }
            },
        ]
    }
    try:
        collection = get_document_collection()
        matching_chunks = collection.count(where=where)
        if matching_chunks == 0:
            retrieved: dict[str, Any] = {}
        else:
            retrieved = collection.query(
                query_texts=[
                    _document_search_query(request.query, request.history)[:3000]
                ],
                n_results=min(DOCUMENT_RETRIEVAL_COUNT, matching_chunks),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
    except Exception as exc:
        logger.exception("Document retrieval failed for user %s", request.user_id)
        raise HTTPException(
            status_code=503,
            detail="আপলোডকৃত PDF থেকে তথ্য খোঁজা যাচ্ছে না। পরে আবার চেষ্টা করুন।",
        ) from exc

    found_documents = retrieved.get("documents") or [[]]
    found_metadatas = retrieved.get("metadatas") or [[]]
    found_distances = retrieved.get("distances") or [[]]
    query_terms = _document_query_terms(request.query)
    citations: list[dict[str, object]] = []
    seen_chunks: set[str] = set()
    for text, metadata, distance in zip(
        found_documents[0],
        found_metadatas[0],
        found_distances[0],
    ):
        metadata = metadata or {}
        similarity = 1.0 - float(distance)
        overlap_terms = query_terms & _document_query_terms(str(text or ""))
        if (
            similarity < MIN_DOCUMENT_SIMILARITY
            and (not query_terms or len(overlap_terms) / len(query_terms) < 0.25)
        ):
            continue
        unique_chunk = (
            str(metadata.get("document_id")),
            str(metadata.get("page_number")),
            str(metadata.get("chunk_index")),
        )
        unique_key = "|".join(unique_chunk)
        if unique_key in seen_chunks:
            continue
        seen_chunks.add(unique_key)
        citations.append(
            {
                "document_id": str(metadata.get("document_id") or ""),
                "filename": str(metadata.get("filename") or "আপলোডকৃত PDF"),
                "page_number": int(metadata.get("page_number") or 1),
                "section_title": str(metadata.get("section_title") or ""),
                "excerpt": str(text or "")[:1200],
                "similarity": round(max(0.0, min(1.0, similarity)), 3),
            }
        )

    if not citations:
        return {
            "status": "needs_verification",
            "message": (
                "আপলোডকৃত PDF-এ এই প্রশ্নের উত্তর খুঁজে পাওয়া যায়নি। PDF-এর "
                "প্রাসঙ্গিক অংশ দিন বা নথিতে থাকা তথ্য সম্পর্কে প্রশ্ন করুন।"
            ),
            "document_citations": [],
        }

    return {
        "status": "success",
        "message": (
            "আপলোডকৃত PDF-এ প্রশ্নটির সঙ্গে সম্পর্কিত অংশ পাওয়া গেছে। নিচের "
            "উদ্ধৃতিগুলোই নথিভিত্তিক উত্তর; নথিতে নেই এমন তথ্য যোগ করা হয়নি।"
        ),
        "document_citations": citations,
    }


@app.post("/api/sources/upload", response_model=None)
async def api_upload_source(
    file: Annotated[UploadFile, File()],
    user_id: Annotated[int, Form(gt=0)],
) -> dict[str, object] | JSONResponse:
    _require_user(user_id)
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="শুধুমাত্র PDF ফাইল আপলোড করুন।")

    content = await file.read(MAX_SOURCE_FILE_BYTES + 1)
    if len(content) > MAX_SOURCE_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="PDF ফাইলটি ২০ MB-এর বেশি; ছোট ফাইল আপলোড করুন।",
        )
    if not content.lstrip().startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="আপলোড করা ফাইলটি বৈধ PDF নয়।")

    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise HTTPException(
                status_code=400,
                detail="পাসওয়ার্ড-সুরক্ষিত PDF পড়া যায়নি; আনলক করা PDF আপলোড করুন।",
            )
        page_count = len(reader.pages)
        if not page_count:
            raise HTTPException(status_code=400, detail="PDF-এ কোনো পৃষ্ঠা নেই।")
        if page_count > MAX_SOURCE_PAGES:
            raise HTTPException(
                status_code=413,
                detail=f"একটি PDF-এ সর্বোচ্চ {MAX_SOURCE_PAGES}টি পৃষ্ঠা গ্রহণ করা যায়।",
            )

        page_texts: list[tuple[int, str]] = []
        total_characters = 0
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = (page.extract_text() or "").strip()
            total_characters += len(page_text)
            if total_characters > MAX_EXTRACTED_TEXT_CHARS:
                raise HTTPException(
                    status_code=413,
                    detail="PDF থেকে নির্যাস করা লেখা ২৫০,০০০ অক্ষরের বেশি।",
                )
            if page_text:
                page_texts.append((page_number, page_text))
    except HTTPException:
        raise
    except (PdfReadError, OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("PDF extraction failed for %s: %s", filename, exc)
        raise HTTPException(
            status_code=400,
            detail="PDF পড়া যায়নি। ফাইলটি বৈধ ও খোলার উপযোগী কি না যাচাই করুন।",
        ) from exc

    if not page_texts:
        raise HTTPException(
            status_code=400,
            detail=(
                "PDF-এ নির্বাচনযোগ্য পাঠ্য পাওয়া যায়নি। স্ক্যান করা ছবির PDF হলে "
                "OCR করে পাঠ্য-সহ PDF আপলোড করুন।"
            ),
        )

    chunks = _chunk_pdf_pages(page_texts)
    extracted_text = "\n".join(
        f"পৃষ্ঠা নং {page_number}\n{text}" for page_number, text in page_texts
    )
    try:
        decision = validate_pdf_domain(
            extracted_text, chunks, get_vector_collection()
        )
    except Exception as exc:
        logger.exception("PDF domain validation failed")
        raise HTTPException(
            status_code=503,
            detail="আইনি ডোমেইন যাচাই সেবা বর্তমানে পাওয়া যাচ্ছে না। পরে আবার চেষ্টা করুন।",
        ) from exc

    if not decision.allowed or decision.domain is None or decision.domain_bn is None:
        log_audit_trail(
            user_id,
            f"PDF upload rejected: {filename}",
            "কোনো উৎস সংরক্ষণ করা হয়নি",
            "No Info (Out of Scope)",
            OUT_OF_SCOPE_PDF_MESSAGE,
        )
        return JSONResponse(
            status_code=400,
            content={
                "status": "out_of_scope",
                "message": OUT_OF_SCOPE_PDF_MESSAGE,
            },
        )

    source = save_uploaded_source(
        user_id,
        filename,
        decision.domain,
        decision.domain_bn,
        page_count,
        extracted_text,
        chunks,
    )
    return {
        "status": "success",
        "message": "PDF যাচাই করে আপনার ব্যক্তিগত উৎস নথিতে সংরক্ষণ করা হয়েছে।",
        "source": _source_metadata(source),
    }


@app.get("/api/sources")
def api_get_sources(
    user_id: Annotated[int, Query(ge=1)],
) -> list[dict[str, object]]:
    _require_user(user_id)
    return get_user_sources(user_id)


@app.delete("/api/sources/{source_id}")
def api_delete_source(
    source_id: int,
    user_id: Annotated[int, Query(ge=1)],
) -> dict[str, str]:
    _require_user(user_id)
    if not delete_uploaded_source(source_id, user_id):
        raise HTTPException(status_code=404, detail="উৎস নথিটি পাওয়া যায়নি।")
    return {"status": "success", "message": "উৎস PDF মুছে ফেলা হয়েছে।"}


@app.post("/api/analyze-case")
def api_analyze_case(request: CaseAnalysisRequest) -> dict[str, object]:
    _require_user(request.user_id)
    domain = request.domain
    source_summary: list[dict[str, Any]] = []
    source_context = ""
    source: dict[str, Any] | None = None

    if request.source_id is not None:
        source = get_source_by_id(request.source_id, request.user_id)
        if source is None:
            raise HTTPException(status_code=404, detail="উৎস নথিটি পাওয়া যায়নি।")
        source_domain = str(source["detected_domain"])
        if domain != "all" and domain != source_domain:
            return _out_of_scope(
                SearchRequest(
                    query=request.query,
                    domain=request.domain,
                    top_k=request.top_k,
                    user_id=request.user_id,
                ),
                request.query,
            )
        domain = source_domain
        source_check = inspect_domain_text(
            str(source["extracted_text"]),
            preferred_domain=source_domain,
        )
        if not source_check.allowed:
            return _out_of_scope(
                SearchRequest(
                    query=request.query,
                    domain=domain,
                    top_k=request.top_k,
                    user_id=request.user_id,
                ),
                request.query,
            )
        chunks = json.loads(str(source["chunks_json"]))
        source_summary = summarize_source(chunks, request.query)
        if not source_summary:
            return _needs_verification(
                SearchRequest(
                    query=request.query,
                    domain=request.domain,
                    top_k=request.top_k,
                    user_id=request.user_id,
                ),
                request.query,
                source_only=True,
            )
        source_context = "\n".join(
            f"{item['citation']}: {item['excerpt']}" for item in source_summary
        )

    search_request = SearchRequest(
        query=request.query,
        domain=domain,
        top_k=request.top_k,
        user_id=request.user_id,
    )
    result = _run_search(
        search_request,
        context_text=source_context,
        log_success=False,
        conversational_intents=False,
    )
    if result.get("status") != "success":
        return result
    analysis = build_case_action_plan(
        request.query,
        result.get("results") or [],
        source_summary=source_summary,
    )
    result.update(analysis)
    if request.source_id is not None and source is not None:
        result["source"] = _source_metadata(source)
    _audit_case_analysis(request.user_id, request.query, analysis)
    return result


@app.post("/api/export-case-plan")
def api_export_case_plan(request: CasePlanExportRequest) -> StreamingResponse:
    _require_user(request.user_id)
    try:
        content = build_case_plan_docx(request.query, request.analysis)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StreamingResponse(
        io.BytesIO(content),
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": 'attachment; filename="ainsathi-case-plan.docx"'
        },
    )


@app.post("/api/generate-draft")
def api_generate_draft(request: DraftRequest) -> dict[str, object]:
    search_request = SearchRequest(
        query=request.query,
        domain=request.domain,
        top_k=3,
        user_id=request.user_id,
    )
    search_result = _run_search(search_request)
    results = search_result.get("results", [])
    if search_result.get("status") != "success" or not results:
        raise HTTPException(
            status_code=422,
            detail=search_result.get(
                "message", "খসড়া তৈরির জন্য প্রাসঙ্গিক আইনি ধারা পাওয়া যায়নি।"
            ),
        )

    statute = results[0]
    domain = str(statute["domain"])
    recipient = {
        "labour_law": "শ্রম অধিদপ্তর / সংশ্লিষ্ট শ্রম কর্তৃপক্ষ",
        "consumer_rights": "জাতীয় ভোক্তা-অধিকার সংরক্ষণ অধিদপ্তর",
        "cyber_law": "সাইবার ক্রাইম ইউনিট / নিকটস্থ থানা",
        "all": "সংশ্লিষ্ট কর্তৃপক্ষ",
    }[domain]
    subject_kind = (
        "আইনগত নোটিশ"
        if request.document_type == "legal_notice"
        else "লিখিত অভিযোগ"
    )
    title = (
        f"{subject_kind}: {statute['act_name']} এর ধারা "
        f"{statute['section_number']} অনুসারে"
    )
    draft = "\n".join(
        [
            "তারিখ: [তারিখ লিখুন]",
            "",
            "বরাবর",
            recipient,
            "[জেলা/কার্যালয়ের ঠিকানা]",
            "",
            f"বিষয়: {title}",
            "",
            "জনাব/জনাবা,",
            "",
            f"আমি {request.applicant_name.strip()}, নিম্নলিখিত ঘটনার বিষয়ে "
            "আপনার দপ্তরের প্রয়োজনীয় ব্যবস্থা প্রার্থনা করছি।",
            "",
            "ঘটনার বিবরণ:",
            request.query.strip(),
            "",
            "প্রাসঙ্গিক আইনি বিধান:",
            f"আইন: {statute['act_name'] or statute['domain_bn']}",
            f"ধারা {statute['section_number']}: {statute['section_title']}",
            f"আইনি অবস্থা: {statute['legal_status']}",
            "",
            "উদ্ধৃত আইনগত পাঠ:",
            str(statute["content"]),
            "",
            "অতএব, সংযুক্ত প্রমাণাদি বিবেচনা করে প্রযোজ্য আইন অনুযায়ী "
            "বিষয়টি তদন্ত ও প্রয়োজনীয় ব্যবস্থা গ্রহণের জন্য বিনীত অনুরোধ করছি।",
            "",
            "সংযুক্তি: [প্রাসঙ্গিক কাগজপত্র/স্ক্রিনশট/রসিদের তালিকা]",
            "",
            "বিনীত,",
            request.applicant_name.strip(),
            "[যোগাযোগের ঠিকানা ও ফোন নম্বর]",
            "[স্বাক্ষর]",
        ]
    )
    return {
        "status": "success",
        "draft": draft,
        "document_type": request.document_type,
        "recipient": recipient,
        "statute": statute,
        "disclaimer": (
            "এটি প্রাপ্ত আইনগত পাঠের ভিত্তিতে তৈরি একটি খসড়া; জমা দেওয়ার আগে "
            "তথ্য ও প্রযোজ্য আইন সংশ্লিষ্ট আইনজীবী বা কর্তৃপক্ষের মাধ্যমে যাচাই করুন।"
        ),
    }


@app.get("/api/audit-logs")
def api_audit_logs(
    user_id: Annotated[int, Query(ge=1)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
) -> dict[str, object]:
    role = _require_user(user_id)
    return {
        "logs": get_audit_trail(user_id=user_id, role=role, limit=limit),
        "role": role,
    }


def _csv_safe_value(value: object) -> str:
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@app.get("/api/audit-logs/csv")
def api_audit_logs_csv(
    user_id: Annotated[int, Query(ge=1)],
) -> StreamingResponse:
    role = _require_user(user_id)
    rows = get_audit_trail(user_id=user_id, role=role, limit=100000)
    columns = [
        "id",
        "user_name",
        "query_text",
        "retrieved_sections",
        "evidence_status",
        "created_at",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_safe_value(row.get(key)) for key in columns})
    content = output.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-logs.csv"'},
    )


@app.post("/api/bookmarks")
def api_add_bookmark(request: BookmarkRequest) -> dict[str, str]:
    _require_user(request.user_id)
    succeeded, message = add_bookmark(
        request.user_id,
        request.domain_bn,
        request.act_name,
        request.section_number,
        request.section_title,
        request.content,
        request.legal_status,
    )
    if not succeeded:
        raise HTTPException(status_code=409, detail=message)
    return {"status": "success", "message": message}


@app.get("/api/bookmarks")
def api_get_bookmarks(
    user_id: Annotated[int, Query(ge=1)],
) -> list[dict[str, object]]:
    _require_user(user_id)
    return get_user_bookmarks(user_id)


@app.delete("/api/bookmarks/{bookmark_id}")
def api_delete_bookmark(
    bookmark_id: int,
    user_id: Annotated[int, Query(ge=1)],
) -> dict[str, str]:
    _require_user(user_id)
    if not any(
        int(bookmark["id"]) == bookmark_id
        for bookmark in get_user_bookmarks(user_id)
    ):
        raise HTTPException(status_code=404, detail="বুকমার্কটি পাওয়া যায়নি।")
    delete_bookmark(bookmark_id, user_id)
    return {"status": "success", "message": "বুকমার্ক মুছে ফেলা হয়েছে।"}
