from pathlib import Path

ROOT = Path(__file__).resolve().parent

VECTOR_STORE_CODE = r'''"""
Multi-Domain Statute-Grounded Vector Store & Hybrid Metadata Search Engine.
Domains:
  1. Bangladesh Labour Act, 2006 (375 Sections)
  2. Consumer Rights Protection Act, 2009 (82 Sections)
  3. Cyber Protection Act, 2026 (51 Sections)
"""

import json
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
PROCESSED_DIR = PROJECT_ROOT / "backend" / "data" / "processed"

LABOUR_CHUNKS_FILE = PROCESSED_DIR / "labour_act_chunks.json"
NEW_DOMAINS_FILE = PROCESSED_DIR / "new_domains_chunks.json"
CHROMA_DB_DIR = PROJECT_ROOT / "backend" / "data" / "chroma_db"

COLLECTION_NAME = "bd_legal_multi_domain_2026"
EMBEDDING_MODEL_NAME = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)


def get_vector_collection():
    """ChromaDB ক্লায়েন্ট এবং মাল্টিলিঙ্গুয়াল বাংলা এম্বেডিং ফাংশন ইনিশিয়ালাইজ করে।"""
    CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))

    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL_NAME
    )

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )
    return collection


def build_vector_store():
    """৩টি আইনি ডোমেইনের সবগুলো ধারা একত্রে ChromaDB-তে ইনডেক্স করে।"""
    all_chunks = []

    if LABOUR_CHUNKS_FILE.exists():
        with open(LABOUR_CHUNKS_FILE, "r", encoding="utf-8") as f:
            labour_chunks = json.load(f)
            for c in labour_chunks:
                c.setdefault("domain", "labour_law")
                c.setdefault("domain_bn", "শ্রম আইন, ২০০৬")
            all_chunks.extend(labour_chunks)
            print(f"[+] শ্রম আইন, ২০০৬ লোড হয়েছে: {len(labour_chunks)}টি ধারা")

    if NEW_DOMAINS_FILE.exists():
        with open(NEW_DOMAINS_FILE, "r", encoding="utf-8") as f:
            new_chunks = json.load(f)
            all_chunks.extend(new_chunks)
            print(f"[+] নতুন ডোমেইনসমূহ লোড হয়েছে: {len(new_chunks)}টি ধারা")

    if not all_chunks:
        raise FileNotFoundError("[!] কোনো চাঙ্ক ফাইল পাওয়া যায়নি।")

    print(f"[*] সর্বমোট {len(all_chunks)}টি ধারা এম্বেড ও ইনডেক্স করা হচ্ছে...")
    collection = get_vector_collection()

    ids = []
    documents = []
    metadatas = []

    for idx, chunk in enumerate(all_chunks):
        domain_key = str(chunk.get("domain", "labour_law"))
        sec_id = f"{domain_key}_{chunk.get('id', 'sec')}_{idx}"
        ids.append(sec_id)
        documents.append(chunk["content"])

        metadatas.append(
            {
                "domain": domain_key,
                "domain_bn": str(chunk.get("domain_bn", "শ্রম আইন, ২০০৬")),
                "act_name": str(chunk.get("act_name", "বাংলাদেশ শ্রম আইন, ২০০৬")),
                "chapter": str(chunk.get("chapter", "")),
                "section_number": str(chunk.get("section_number", "")),
                "section_title": str(chunk.get("section_title", "")),
                "legal_status": str(chunk.get("legal_status", "সক্রিয় (Active)")),
                "amendment_provenance": str(
                    chunk.get("amendment_provenance", "মূল আইন")
                ),
            }
        )

    BATCH_SIZE = 100
    for i in range(0, len(ids), BATCH_SIZE):
        collection.upsert(
            ids=ids[i : i + BATCH_SIZE],
            documents=documents[i : i + BATCH_SIZE],
            metadatas=metadatas[i : i + BATCH_SIZE],
        )
        print(f"  -> ইনডেক্সিং সম্পন্ন: {min(i + BATCH_SIZE, len(ids))}/{len(ids)}")

    print("\n" + "=" * 65)
    print("✅ মাল্টি-ডোমেইন ChromaDB ভেক্টর ডেটাবেজ সফলভাবে প্রস্তুত!")
    print(f"📁 ডেটাবেজ পাথ: {CHROMA_DB_DIR}")
    print(f"📊 মোট ইনডেক্সকৃত রেকর্ড: {collection.count()}")
    print("=" * 65)
    return collection


if __name__ == "__main__":
    build_vector_store()
'''

DATABASE_CODE = r'''"""
Database Initialization & Schema Management.
Statute-Grounded Multi-Domain Bangla Legal Assistant.
Module: SQLite Relational Database Engine (Users, Audit Logs & Case Bookmarks)
"""

from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "legal_assistant.db"


def get_db_connection():
    """ডেটাবেজ কানেকশন রিটার্ন করে।"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """ডেটাবেজ স্কিমা ও টেবিল তৈরি করে।"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            role TEXT DEFAULT 'citizen',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS query_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            query_text TEXT NOT NULL,
            retrieved_sections TEXT,
            generated_answer TEXT,
            evidence_status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            domain_bn TEXT,
            act_name TEXT,
            section_number TEXT,
            section_title TEXT,
            content TEXT,
            legal_status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    conn.commit()
    conn.close()


def log_audit_trail(
    user_id, query_text, retrieved_sections, evidence_status="Active", generated_answer=""
):
    """অডিট ট্রেইলে ব্যবহারকারীর সার্চ হিস্ট্রি সংরক্ষণ করে।"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO query_logs (user_id, query_text, retrieved_sections, generated_answer, evidence_status)
            VALUES (?, ?, ?, ?, ?)
        """,
            (user_id, query_text, retrieved_sections, generated_answer, evidence_status),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[!] Audit log error: {e}")


def get_audit_trail(user_id=None, role="citizen", limit=50):
    """রোল অনুযায়ী ইউজার-আইসোলেটেড অডিট ট্রেইল রিটার্ন করে।"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if role == "admin":
            cursor.execute(
                """
                SELECT q.id, COALESCE(u.full_name, 'Citizen') as user_name, 
                       q.query_text, q.retrieved_sections, q.evidence_status, q.created_at
                FROM query_logs q
                LEFT JOIN users u ON q.user_id = u.id
                ORDER BY q.id DESC
                LIMIT ?
            """,
                (limit,),
            )
        else:
            cursor.execute(
                """
                SELECT q.id, COALESCE(u.full_name, 'Citizen') as user_name, 
                       q.query_text, q.retrieved_sections, q.evidence_status, q.created_at
                FROM query_logs q
                LEFT JOIN users u ON q.user_id = u.id
                WHERE q.user_id = ?
                ORDER BY q.id DESC
                LIMIT ?
            """,
                (user_id, limit),
            )

        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[!] Get audit error: {e}")
        return []


def add_bookmark(user_id, domain_bn, act_name, section_number, section_title, content, legal_status):
    """গুরুত্বপূর্ণ ধারা ইউজারের কেস ফোল্ডারে সেভ করে।"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id FROM bookmarks WHERE user_id = ? AND act_name = ? AND section_number = ?
    """,
        (user_id, act_name, section_number),
    )
    if cursor.fetchone():
        conn.close()
        return False, "এই ধারাটি ইতিমধ্যেই আপনার কেস ফোল্ডারে সংরক্ষিত আছে।"

    cursor.execute(
        """
        INSERT INTO bookmarks (user_id, domain_bn, act_name, section_number, section_title, content, legal_status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (user_id, domain_bn, act_name, section_number, section_title, content, legal_status),
    )
    conn.commit()
    conn.close()
    return True, "ধারাটি কেস ফোল্ডারে সংরক্ষিত হয়েছে!"


def get_user_bookmarks(user_id):
    """নির্দিষ্ট ইউজারের সব বুকমার্ক করা ধারা রিটার্ন করে।"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, domain_bn, act_name, section_number, section_title, content, legal_status, created_at
        FROM bookmarks
        WHERE user_id = ?
        ORDER BY id DESC
    """,
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_bookmark(bookmark_id, user_id):
    """ইউজারের নির্দিষ্ট বুকমার্ক মুছে ফেলে।"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM bookmarks WHERE id = ? AND user_id = ?", (bookmark_id, user_id)
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
'''

MAIN_PY_CODE = r'''"""
FastAPI Backend Server for Statute-Grounded Multi-Domain Bangla Legal Assistant.
"""

import csv
from datetime import datetime
import io
from pathlib import Path
import re
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR / "backend"))

from auth import authenticate_user, register_user, validate_user_input
from database import (
    add_bookmark,
    delete_bookmark,
    get_audit_trail,
    get_user_bookmarks,
    init_db,
    log_audit_trail,
)

app = FastAPI(title="Statute-Grounded Bangla Legal Assistant API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

_vector_collection = None


def get_collection():
    global _vector_collection
    if _vector_collection is None:
        import importlib

        mod = importlib.import_module("scripts.03_vector_store")
        _vector_collection = mod.get_vector_collection()
    return _vector_collection


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str
    confirm_password: str
    role: str = "citizen"


class SearchRequest(BaseModel):
    query: str
    domain: str = "all"
    top_k: int = 3
    user_id: int | None = None


class DraftRequest(BaseModel):
    query: str
    domain_bn: str
    act_name: str
    section_number: str
    section_title: str
    statute_text: str
    applicant_name: str = "আবেদনকারীর নাম"


class BookmarkRequest(BaseModel):
    user_id: int
    domain_bn: str
    act_name: str
    section_number: str
    section_title: str
    content: str
    legal_status: str


DOMAIN_MAX_SECTIONS = {
    "labour_law": (353, "বাংলাদেশ শ্রম আইন, ২০০৬"),
    "consumer_rights": (82, "ভোক্তা-অধিকার সংরক্ষণ আইন, ২০০৯"),
    "cyber_law": (51, "সাইবার সুরক্ষা আইন, ২০২৬"),
    "all": (353, "বাংলাদেশ শ্রম আইন, ২০০৬ / সংশ্লিষ্ট আইন"),
}

BENGALI_DIGITS = {
    "০": "0", "১": "1", "২": "2", "৩": "3", "৪": "4",
    "৫": "5", "৬": "6", "৭": "7", "৮": "8", "৯": "9",
}


@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    html_path = BASE_DIR / "frontend" / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>frontend/index.html ফাইলটি পাওয়া যায়নি।</h1>", status_code=404)
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.post("/api/register")
def api_register(req: RegisterRequest):
    if req.password != req.confirm_password:
        raise HTTPException(status_code=400, detail="উভয় পাসওয়ার্ড হুবহু এক হতে হবে!")

    val_res = validate_user_input(req.full_name.strip(), req.email.strip(), req.password)
    if isinstance(val_res, tuple):
        if not val_res[0]:
            raise HTTPException(status_code=400, detail=val_res[1])
    elif isinstance(val_res, str) and val_res:
        raise HTTPException(status_code=400, detail=val_res)

    res = register_user(req.full_name.strip(), req.email.strip(), req.password, req.role)
    if isinstance(res, dict) and res.get("status") == "success":
        return {"status": "success", "message": "নিবন্ধন সফল হয়েছে! এখন লগইন করুন।"}
    if isinstance(res, tuple) and res[0] is True:
        return {"status": "success", "message": "নিবন্ধন সফল হয়েছে! এখন লগইন করুন।"}

    err = res.get("message") if isinstance(res, dict) else (res[1] if isinstance(res, tuple) else "নিবন্ধন ব্যর্থ হয়েছে।")
    raise HTTPException(status_code=400, detail=err)


@app.post("/api/login")
def api_login(req: LoginRequest):
    if not req.email.strip() or not req.password:
        raise HTTPException(status_code=400, detail="ইমেইল এবং পাসওয়ার্ড পূরণ করুন।")

    res = authenticate_user(req.email.strip(), req.password)
    if isinstance(res, dict) and res.get("status") == "success":
        return {"status": "success", "user": res.get("user")}
    if isinstance(res, tuple) and res[0] is True:
        return {"status": "success", "user": res[1]}

    err = res.get("message") if isinstance(res, dict) else (res[1] if isinstance(res, tuple) else "ইমেইল বা পাসওয়ার্ড সঠিক নয়।")
    raise HTTPException(status_code=401, detail=err)


@app.post("/api/search")
def api_search(req: SearchRequest):
    q = req.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="অনুসন্ধানের জন্য প্রশ্ন লিখুন।")

    sec_match = re.search(r"ধারা\s*([০-৯0-9]+)", q)
    if sec_match:
        raw_n = sec_match.group(1)
        norm_n = int("".join(BENGALI_DIGITS.get(ch, ch) for ch in raw_n))
        max_sec, domain_label = DOMAIN_MAX_SECTIONS.get(req.domain, (353, "সংশ্লিষ্ট আইন"))
        if norm_n > max_sec:
            if req.user_id:
                log_audit_trail(req.user_id, q, f"ধারা {raw_n} [Out of Range]", "Rejected")
            return {
                "status": "rejected",
                "message": (
                    f"আইনি সতর্কতা: নির্বাচিত আইনে ({domain_label}) 'ধারা {raw_n}' নামে কোনো ধারার "
                    f"অস্তিত্ব নেই (সর্বোচ্চ ধারা সংখ্যা {max_sec})। সিস্টেম কোনো কাল্পনিক তথ্য প্রদান করবে না।"
                ),
                "results": [],
            }

    collection = get_collection()
    query_kwargs = {
        "query_texts": [q],
        "n_results": max(1, min(req.top_k, 6)),
        "include": ["documents", "metadatas", "distances"],
    }
    if req.domain != "all":
        query_kwargs["where"] = {"domain": req.domain}

    raw_results = collection.query(**query_kwargs)

    docs = raw_results.get("documents", [[]])[0]
    metas = raw_results.get("metadatas", [[]])[0]
    distances = raw_results.get("distances", [[]])[0]

    if not docs:
        return {
            "status": "empty",
            "message": "আপনার প্রশ্নের সাথে সরাসরি মিলে এমন কোনো ধারা পাওয়া যায়নি।",
            "results": [],
        }

    best_distance = distances[0]
    confidence = round(max(0.0, 1.0 - (best_distance / 2.0)) * 100, 1)

    if confidence < 22.0:
        return {
            "status": "low_confidence",
            "confidence": confidence,
            "message": "সুনির্দিষ্ট কোনো ধারার সাথে পর্যাপ্ত মিল পাওয়া যায়নি। অনুগ্রহ করে আরও স্পষ্ট আইনি শব্দ ব্যবহার করুন।",
            "results": [],
        }

    formatted_results = []
    for i, (doc, meta, dist) in enumerate(zip(docs, metas, distances)):
        item_conf = round(max(0.0, 1.0 - (dist / 2.0)) * 100, 1)
        sec_num = meta.get("section_number", "N/A")
        sec_title = meta.get("section_title", "আইনি ধারা")
        status = meta.get("legal_status", "সক্রিয় (Active)")

        formatted_results.append(
            {
                "domain": meta.get("domain", "labour_law"),
                "domain_bn": meta.get("domain_bn", "শ্রম আইন, ২০০৬"),
                "act_name": meta.get("act_name", "বাংলাদেশ শ্রম আইন, ২০০৬"),
                "chapter": meta.get("chapter", ""),
                "section_number": sec_num,
                "section_title": sec_title,
                "legal_status": status,
                "amendment_provenance": meta.get("amendment_provenance", "মূল আইন"),
                "content": doc,
                "confidence": item_conf,
            }
        )

        if i == 0 and req.user_id:
            log_audit_trail(
                req.user_id,
                f"[{meta.get('domain_bn', '')}] {q}",
                f"ধারা {sec_num}: {sec_title}",
                status,
            )

    return {
        "status": "success",
        "confidence": confidence,
        "results