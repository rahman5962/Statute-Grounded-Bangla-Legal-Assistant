"""
Database Initialization & Schema Management.
Statute-Grounded Bangla Legal Assistant (FR-01, FR-04).
Module: SQLite Relational Database Engine
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


if __name__ == "__main__":
    init_db()