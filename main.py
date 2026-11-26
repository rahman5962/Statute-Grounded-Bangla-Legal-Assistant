"""FastAPI application for the statute-grounded legal assistant."""

import csv
import importlib.util
import io
import json
import logging
import os
import re
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
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
from database import (
    add_bookmark,
    delete_bookmark,
    delete_uploaded_source,
    get_audit_trail,
    get_db_connection,
    get_source_by_id,
    get_user_sources,
    get_user_bookmarks,
    init_db,
    log_audit_trail,
    save_uploaded_source,
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
    "হবে", "হয়", "হয়", "করলে", "করিবার", "করে", "করতে", "কোন", "কোনো",
    "জন্য", "সম্পর্কে", "নিয়ম", "নিয়ম", "আইন", "ধারা",
}

_vector_collection = None
_vector_collection_lock = threading.Lock()
MAX_SOURCE_FILE_BYTES = 20 * 1024 * 1024
MAX_SOURCE_PAGES = 100
MAX_EXTRACTED_TEXT_CHARS = 250_000
SOURCE_CHUNK_SIZE = 1200
SOURCE_CHUNK_OVERLAP = 160


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
    """Load the Chroma collection only when the first search needs it."""
    global _vector_collection
    if _vector_collection is None:
        with _vector_collection_lock:
            if _vector_collection is None:
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
                _vector_collection = module.get_vector_collection()
    return _vector_collection


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


def _normalized_legal_status(value: object) -> str:
    source = str(value or "").lower()
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
        if token.startswith("পণ্য"):
            token = "পণ্য"
        elif token.startswith("বিক্র"):
            token = "বিক্রয়"
        elif token.startswith(("দণ্ড", "দন্ড", "শাস্তি")):
            token = "দণ্ড"
        terms.add(token)
    return terms


def _title_relevance(query: str, section_title: object) -> int:
    return len(_search_terms(query) & _search_terms(str(section_title or "")))


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
    results = [candidate[2] for candidate in ranked_results[: request.top_k]]
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
def api_login(request: LoginRequest) -> dict[str, object]:
    result = authenticate_user(request.email.strip(), request.password)
    user = _login_user(result)
    if user is None:
        message = _result_message(result, "ইমেইল অথবা পাসওয়ার্ড সঠিক নয়।")
        raise HTTPException(status_code=401, detail=message)
    return {"status": "success", "user": user}


@app.post("/api/search")
def api_search(request: SearchRequest) -> dict[str, object]:
    result = _run_search(request, log_success=False)
    if result.get("status") != "success":
        return result
    results = result.get("results") or []
    analysis = build_case_action_plan(request.query, results)
    result.update(analysis)
    if request.user_id is not None:
        _audit_case_analysis(request.user_id, request.query, analysis)
    return result


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
