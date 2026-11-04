"""Database Initialization & Schema Management.

Statute-Grounded Bangla Legal Assistant (FR-01, FR-04).
Author: Sazim Rahman (241-35-034)
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

  # ৩. ফিডব্যাক টেবিল
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


if __name__ == "__main__":
  init_db()