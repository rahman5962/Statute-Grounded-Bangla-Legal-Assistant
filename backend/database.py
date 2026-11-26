"""
Database Initialization & Schema Management.
Statute-Grounded Bangla Legal Assistant (FR-01, FR-04).
Module: SQLite Relational Database Engine
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

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

    # ১. ইউজার টেবিল (অথেনটিকেশন ও ক্রেডেনশিয়াল স্টোরেজ)
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

    # ২. কোয়েরি ও কনসালটেশন লগ টেবিল (অডিট হিস্ট্রি)
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

    # ৩. ব্যবহারকারীর বুকমার্ক করা ধারা
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            domain_bn TEXT,
            act_name TEXT NOT NULL,
            section_number TEXT NOT NULL,
            section_title TEXT,
            content TEXT,
            legal_status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE (user_id, act_name, section_number)
        )
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bookmarks_user_act_section
        ON bookmarks (user_id, act_name, section_number)
    """)

    # ৪. ফিডব্যাক টেবিল
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_id INTEGER,
            rating INTEGER,
            comments TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (log_id) REFERENCES query_logs (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            detected_domain TEXT NOT NULL CHECK (
                detected_domain IN ('labour_law', 'consumer_rights', 'cyber_law')
            ),
            detected_domain_bn TEXT NOT NULL,
            page_count INTEGER NOT NULL CHECK (page_count > 0),
            extracted_text TEXT NOT NULL,
            chunks_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_uploaded_sources_user_created
        ON uploaded_sources (user_id, created_at DESC, id DESC)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_documents (
            document_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            conversation_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
            page_count INTEGER NOT NULL CHECK (page_count > 0),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            UNIQUE (user_id, conversation_id, content_sha256)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_uploaded_documents_conversation
        ON uploaded_documents (user_id, conversation_id, created_at DESC)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_sessions_user
        ON user_sessions (user_id, expires_at)
    """)

    conn.commit()
    conn.close()
    print(f"[*] SQLite ডেটাবেজ সফলভাবে প্রস্তুত: {DB_PATH}")


def log_audit_trail(user_id, query_text, retrieved_sections, evidence_status="Active", generated_answer=""):
    """অডিট ট্রেইলে ব্যবহারকারীর সার্চ হিস্ট্রি সংরক্ষণ করে।"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO query_logs (user_id, query_text, retrieved_sections, generated_answer, evidence_status)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, query_text, retrieved_sections, generated_answer, evidence_status))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[!] Audit log error: {e}")


def get_audit_trail(user_id=None, role="citizen", limit=50):
    """
    ব্যবহারকারীর রোল অনুযায়ী অডিট ট্রেইল রেকর্ড রিটার্ন করে।
    সাধারণ ব্যবহারকারী শুধু নিজের রেকর্ড দেখবে, অ্যাডমিন সবার রেকর্ড দেখতে পারবে।
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if role == "admin":
            cursor.execute("""
                SELECT q.id, COALESCE(u.full_name, 'Citizen') as user_name, 
                       q.query_text, q.retrieved_sections, q.evidence_status, q.created_at
                FROM query_logs q
                LEFT JOIN users u ON q.user_id = u.id
                ORDER BY q.id DESC
                LIMIT ?
            """, (limit,))
        else:
            cursor.execute("""
                SELECT q.id, COALESCE(u.full_name, 'Citizen') as user_name, 
                       q.query_text, q.retrieved_sections, q.evidence_status, q.created_at
                FROM query_logs q
                LEFT JOIN users u ON q.user_id = u.id
                WHERE q.user_id = ?
                ORDER BY q.id DESC
                LIMIT ?
            """, (user_id, limit))
            
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[!] Get audit error: {e}")
        return []


def add_bookmark(user_id, domain_bn, act_name, section_number, section_title, content, legal_status):
    """গুরুত্বপূর্ণ ধারা ইউজারের কেস ফোল্ডারে সেভ করে।"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO bookmarks (
                user_id, domain_bn, act_name, section_number,
                section_title, content, legal_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, domain_bn, act_name, section_number,
            section_title, content, legal_status,
        ))
        conn.commit()
        return True, "ধারাটি কেস ফোল্ডারে সংরক্ষিত হয়েছে!"
    except sqlite3.IntegrityError:
        cursor.execute("""
            SELECT 1 FROM bookmarks
            WHERE user_id = ? AND act_name = ? AND section_number = ?
        """, (user_id, act_name, section_number))
        if cursor.fetchone():
            return False, "এই ধারাটি ইতিমধ্যেই আপনার কেস ফোল্ডারে সংরক্ষিত আছে।"
        raise
    finally:
        conn.close()


def get_user_bookmarks(user_id):
    """নির্দিষ্ট ইউজারের সব বুকমার্ক করা ধারা নতুন থেকে পুরোনো ক্রমে রিটার্ন করে।"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, domain_bn, act_name, section_number, section_title,
                   content, legal_status, created_at
            FROM bookmarks
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
        """, (user_id,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def delete_bookmark(bookmark_id, user_id):
    """ইউজারের নির্দিষ্ট বুকমার্ক মুছে ফেলে।"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM bookmarks WHERE id = ? AND user_id = ?",
            (bookmark_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def save_uploaded_source(
    user_id: int,
    filename: str,
    detected_domain: str,
    detected_domain_bn: str,
    page_count: int,
    extracted_text: str,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist extracted PDF text and page-aware chunks for one user."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO uploaded_sources (
                user_id, filename, detected_domain, detected_domain_bn,
                page_count, extracted_text, chunks_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                filename,
                detected_domain,
                detected_domain_bn,
                page_count,
                extracted_text,
                json.dumps(chunks, ensure_ascii=False),
            ),
        )
        conn.commit()
        source_id = cursor.lastrowid
    finally:
        conn.close()
    if source_id is None:
        raise RuntimeError("Uploaded source ID was not generated.")
    source = get_source_by_id(source_id, user_id)
    if source is None:
        raise RuntimeError("Uploaded source was not persisted.")
    return source


def get_user_sources(user_id: int) -> list[dict[str, Any]]:
    """Return source metadata belonging only to the requested user."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, user_id, filename, detected_domain, detected_domain_bn,
                   page_count, created_at
            FROM uploaded_sources
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_source_by_id(source_id: int, user_id: int) -> dict[str, Any] | None:
    """Fetch a source only when both its id and owner match."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT id, user_id, filename, detected_domain, detected_domain_bn,
                   page_count, extracted_text, chunks_json, created_at
            FROM uploaded_sources
            WHERE id = ? AND user_id = ?
            """,
            (source_id, user_id),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def delete_uploaded_source(source_id: int, user_id: int) -> bool:
    """Delete a source only when it belongs to the requesting user."""
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM uploaded_sources WHERE id = ? AND user_id = ?",
            (source_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def save_uploaded_document(
    document_id: str,
    user_id: int,
    conversation_id: str,
    filename: str,
    content_sha256: str,
    size_bytes: int,
    page_count: int,
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO uploaded_documents (
                document_id, user_id, conversation_id, filename,
                content_sha256, size_bytes, page_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                user_id,
                conversation_id,
                filename,
                content_sha256,
                size_bytes,
                page_count,
            ),
        )
        conn.commit()
        document = get_uploaded_document(document_id, user_id, conversation_id)
        if document is None:
            raise RuntimeError("Uploaded document was not persisted.")
        return document
    finally:
        conn.close()


def get_uploaded_document(
    document_id: str,
    user_id: int,
    conversation_id: str,
) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT document_id, user_id, conversation_id, filename,
                   content_sha256, size_bytes, page_count, created_at
            FROM uploaded_documents
            WHERE document_id = ? AND user_id = ? AND conversation_id = ?
            """,
            (document_id, user_id, conversation_id),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def get_uploaded_document_by_hash(
    user_id: int,
    conversation_id: str,
    content_sha256: str,
) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT document_id, user_id, conversation_id, filename,
                   content_sha256, size_bytes, page_count, created_at
            FROM uploaded_documents
            WHERE user_id = ? AND conversation_id = ? AND content_sha256 = ?
            """,
            (user_id, conversation_id, content_sha256),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def get_user_documents(
    user_id: int,
    conversation_id: str,
) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT document_id, user_id, conversation_id, filename,
                   size_bytes, page_count, created_at
            FROM uploaded_documents
            WHERE user_id = ? AND conversation_id = ?
            ORDER BY created_at ASC, document_id ASC
            """,
            (user_id, conversation_id),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_uploaded_document(
    document_id: str,
    user_id: int,
    conversation_id: str,
) -> bool:
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """
            DELETE FROM uploaded_documents
            WHERE document_id = ? AND user_id = ? AND conversation_id = ?
            """,
            (document_id, user_id, conversation_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_uploaded_documents_for_conversation(
    user_id: int,
    conversation_id: str,
) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT document_id, filename, size_bytes, page_count
            FROM uploaded_documents
            WHERE user_id = ? AND conversation_id = ?
            """,
            (user_id, conversation_id),
        ).fetchall()
        conn.execute(
            """
            DELETE FROM uploaded_documents
            WHERE user_id = ? AND conversation_id = ?
            """,
            (user_id, conversation_id),
        )
        conn.commit()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def save_user_session(token_hash: str, user_id: int, expires_at: float) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "DELETE FROM user_sessions WHERE user_id = ? AND expires_at <= ?",
            (user_id, time.time()),
        )
        conn.execute(
            """
            INSERT INTO user_sessions (token_hash, user_id, expires_at)
            VALUES (?, ?, ?)
            """,
            (token_hash, user_id, expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def get_session_user_id(token_hash: str) -> int | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT user_id FROM user_sessions
            WHERE token_hash = ? AND expires_at > ?
            """,
            (token_hash, time.time()),
        ).fetchone()
        return int(row["user_id"]) if row is not None else None
    finally:
        conn.close()


def delete_user_session(token_hash: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "DELETE FROM user_sessions WHERE token_hash = ?",
            (token_hash,),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()