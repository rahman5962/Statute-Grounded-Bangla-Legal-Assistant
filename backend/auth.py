"""User Authentication & Security Module.

Statute-Grounded Bangla Legal Assistant (FR-01 - Compulsory Requirement).
Author: Sazim Rahman (241-35-034)
Module: Registration, Login Validation & bcrypt Password Hashing
"""

import re
import sqlite3
import bcrypt
from database import get_db_connection

EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")


def validate_user_input(
    full_name: str, email: str, password: str
) -> tuple[bool, str]:
  """ইউজার ইনপুট যাচাই করে (Input Validation)।"""
  if not full_name or len(full_name.strip()) < 3:
    return False, "নামটি অবশ্যই কমপক্ষে ৩ অক্ষরের হতে হবে।"

  if not email or not EMAIL_REGEX.match(email.strip()):
    return False, "অনুগ্রহ করে একটি সঠিক ইমেইল অ্যাড্রেস প্রদান করুন।"

  if not password or len(password) < 6:
    return False, "পাসওয়ার্ড কমপক্ষে ৬ অক্ষরের হতে হবে।"

  return True, "ভ্যালিডেশন সফল।"


def hash_password(password: str) -> str:
  """পাসওয়ার্ড bcrypt ব্যবহার করে হ্যাশ করে।"""
  salt = bcrypt.gensalt(rounds=12)
  hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
  return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
  """প্লেইন পাসওয়ার্ড এবং হ্যাশড পাসওয়ার্ডের মিল যাচাই করে।"""
  return bcrypt.checkpw(
      plain_password.encode("utf-8"), hashed_password.encode("utf-8")
  )


def register_user(
    full_name: str, email: str, password: str, role: str = "citizen"
) -> dict:
  """নতুন ইউজার রেজিস্ট্রেশন করে ডেটাবেজে সংরক্ষণ করে।"""
  is_valid, msg = validate_user_input(full_name, email, password)
  if not is_valid:
    return {"status": "error", "message": msg}

  conn = get_db_connection()
  cursor = conn.cursor()

  hashed_pwd = hash_password(password)

  try:
    cursor.execute(
        """
            INSERT INTO users (full_name, email, hashed_password, role)
            VALUES (?, ?, ?, ?)
        """,
        (full_name.strip(), email.strip().lower(), hashed_pwd, role),
    )
    conn.commit()
    user_id = cursor.lastrowid
    return {
        "status": "success",
        "message": "রেজিস্ট্রেশন সফল হয়েছে!",
        "user_id": user_id,
        "email": email.strip().lower(),
    }
  except sqlite3.IntegrityError:
    return {
        "status": "error",
        "message": "এই ইমেইলটি দিয়ে ইতিমধ্যে অ্যাকাউন্ট খোলা হয়েছে।",
    }
  finally:
    conn.close()


def authenticate_user(email: str, password: str) -> dict:
  """ইউজার লগইন যাচাই করে।"""
  if not email or not password:
    return {"status": "error", "message": "ইমেইল এবং পাসওয়ার্ড প্রদান করুন।"}

  conn = get_db_connection()
  cursor = conn.cursor()

  cursor.execute(
      "SELECT id, full_name, email, hashed_password, role FROM users WHERE"
      " email = ?",
      (email.strip().lower(),),
  )
  user = cursor.fetchone()
  conn.close()

  if not user:
    return {"status": "error", "message": "ভুল ইমেইল অথবা পাসওয়ার্ড!"}

  if not verify_password(password, user["hashed_password"]):
    return {"status": "error", "message": "ভুল ইমেইল অথবা পাসওয়ার্ড!"}

  return {
      "status": "success",
      "message": "লগইন সফল হয়েছে!",
      "user": {
          "id": user["id"],
          "full_name": user["full_name"],
          "email": user["email"],
          "role": user["role"],
      },
  }


if __name__ == "__main__":
  # ইউনিট টেস্ট ও ডায়াগনস্টিক রান
  from database import init_db

  init_db()

  print("\n--- [টেস্ট ১: ইউজার রেজিস্ট্রেশন] ---")
  reg_res = register_user("Sazim Rahman", "sazim@example.com", "securePass123")
  print(reg_res)

  print("\n--- [টেস্ট ২: সঠিক পাসওয়ার্ড দিয়ে লগইন] ---")
  login_res = authenticate_user("sazim@example.com", "securePass123")
  print(login_res)

  print("\n--- [টেস্ট ৩: ভুল পাসওয়ার্ড হ্যান্ডলিং] ---")
  fail_res = authenticate_user("sazim@example.com", "wrongPassword")
  print(fail_res)