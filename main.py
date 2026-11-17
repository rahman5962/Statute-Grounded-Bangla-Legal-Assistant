"""FastAPI application for the statute-grounded legal assistant."""

import csv
import importlib.util
import io
import logging
import os
import re
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, AsyncIterator, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR / "backend"
VECTOR_STORE_SCRIPT = BACKEND_DIR / "scripts" / "03_vector_store.py"
FRONTEND_INDEX = BASE_DIR / "frontend" / "index.html"

sys.path.insert(0, str(BACKEND_DIR))

from auth import authenticate_user, register_user, validate_user_input
from database import (
    add_bookmark,
    delete_bookmark,
    get_audit_trail,
    get_db_connection,
    get_user_bookmarks,
    init_db,
    log_audit_trail,
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

_vector_collection = None
_vector_collection_lock = threading.Lock()


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
    return round(max(0.0, min(1.0, 1.0 - value / 2.0)) * 100, 1)


def _section_out_of_range(query: str, domain: str) -> tuple[str, int, str] | None:
    match = re.search(r"ধারা\s*([০-৯0-9]+)", query)
    if match is None:
        return None
    raw_number = match.group(1)
    section_number = int(raw_number.translate(BENGALI_DIGITS))
    maximum, domain_name = DOMAIN_MAX_SECTIONS[domain]
    if section_number > maximum:
        return raw_number, maximum, domain_name
    return None


def _run_search(request: SearchRequest) -> dict[str, object]:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="অনুসন্ধানের জন্য প্রশ্ন লিখুন।")
    if request.user_id is not None:
        _require_user(request.user_id)

    rejected = _section_out_of_range(query, request.domain)
    if rejected is not None:
        raw_number, maximum, domain_name = rejected
        if request.user_id is not None:
            log_audit_trail(
                request.user_id,
                query,
                f"ধারা {raw_number} [Out of Range: >{maximum}]",
                "Rejected",
            )
        return {
            "status": "rejected",
            "message": (
                f"আইনি সতর্কতা: {domain_name}-এ ধারা {raw_number} নেই। "
                f"এই আইনে সর্বোচ্চ ধারা {maximum}; তাই কোনো অনুমানভিত্তিক "
                "তথ্য দেওয়া হচ্ছে না।"
            ),
            "results": [],
        }

    query_kwargs: dict[str, object] = {
        "query_texts": [query],
        "n_results": request.top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if request.domain != "all":
        query_kwargs["where"] = {"domain": request.domain}

    try:
        raw_results = get_vector_collection().query(**query_kwargs)
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
        return {
            "status": "empty",
            "message": "আপনার প্রশ্নের সাথে মেলে এমন কোনো ধারা পাওয়া যায়নি।",
            "results": [],
        }

    results: list[dict[str, object]] = []
    for index, document in enumerate(documents):
        metadata = metadatas[index] if index < len(metadatas) else {}
        distance = distances[index] if index < len(distances) else 2.0
        metadata = metadata or {}
        status = _normalized_legal_status(metadata.get("legal_status"))
        results.append(
            {
                "domain": metadata.get("domain", request.domain),
                "domain_bn": metadata.get("domain_bn", ""),
                "act_name": metadata.get("act_name", ""),
                "chapter": metadata.get("chapter", ""),
                "section_number": metadata.get("section_number", ""),
                "section_title": metadata.get("section_title", ""),
                "legal_status": status,
                "source_legal_status": metadata.get("legal_status", ""),
                "amendment_provenance": metadata.get("amendment_provenance", ""),
                "content": document,
                "confidence": _confidence(distance),
            }
        )

    confidence = float(results[0]["confidence"])
    if request.user_id is not None:
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
    return _run_search(request)


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
