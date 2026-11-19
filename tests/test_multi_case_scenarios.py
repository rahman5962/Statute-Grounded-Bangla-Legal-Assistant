"""HTTP integration checks for three-domain case analysis and PDF sources."""

from __future__ import annotations

import io
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import main  # noqa: E402


BASE_URL = os.getenv("LEGAL_ASSISTANT_BASE_URL", "http://127.0.0.1:8000")
OUT_OF_SCOPE_MESSAGE = main.OUT_OF_SCOPE_MESSAGE
OUT_OF_SCOPE_PDF_MESSAGE = main.OUT_OF_SCOPE_PDF_MESSAGE


def create_text_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): font_reference}
            )
        }
    )
    content = DecodedStreamObject()
    escaped_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content.set_data(
        f"BT /F1 12 Tf 50 750 Td ({escaped_text}) Tj ET".encode("ascii")
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def create_user(session: requests.Session, suffix: str) -> int:
    email = f"case-test-{suffix}-{uuid.uuid4().hex[:8]}@example.com"
    password = "test-password-123"
    response = session.post(
        f"{BASE_URL}/api/register",
        json={
            "full_name": f"Case Test {suffix}",
            "email": email,
            "password": password,
            "confirm_password": password,
            "role": "citizen",
        },
        timeout=120,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Test user registration failed: {response.text}")
    response = session.post(
        f"{BASE_URL}/api/login",
        json={"email": email, "password": password},
        timeout=120,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Test user login failed: {response.text}")
    return int(response.json()["user"]["id"])


def wait_for_server() -> None:
    deadline = time.monotonic() + 60
    last_error = "server did not respond"
    while time.monotonic() < deadline:
        try:
            response = requests.get(BASE_URL, timeout=3)
            if response.status_code == 200:
                return
            last_error = f"GET / returned {response.status_code}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"FastAPI server is unavailable at {BASE_URL}: {last_error}")


def expect(condition: bool, label: str, details: str = "") -> bool:
    if condition:
        print(f"PASS  {label}")
        return True
    print(f"FAIL  {label}{': ' + details if details else ''}")
    return False


def cleanup_test_users(user_ids: list[int]) -> None:
    if not user_ids:
        return
    connection = sqlite3.connect(main.BACKEND_DIR / "data" / "legal_assistant.db")
    try:
        placeholders = ",".join("?" for _ in user_ids)
        for table in ("query_logs", "bookmarks", "uploaded_sources"):
            connection.execute(
                f"DELETE FROM {table} WHERE user_id IN ({placeholders})",
                user_ids,
            )
        connection.execute(
            f"DELETE FROM users WHERE id IN ({placeholders})",
            user_ids,
        )
        connection.commit()
    finally:
        connection.close()


def main_test() -> int:
    wait_for_server()
    session = requests.Session()
    users: list[int] = []
    passed = 0
    total = 0

    def check(condition: bool, label: str, details: str = "") -> None:
        nonlocal passed, total
        total += 1
        passed += int(expect(condition, label, details))

    try:
        frontend = session.get(BASE_URL, timeout=30)
        check(
            frontend.status_code == 200
            and "NotebookLM Mode" in frontend.text
            and "Step-by-Step Legal Roadmap" in frontend.text,
            "Updated frontend is served with the PDF workspace and roadmap",
            f"HTTP {frontend.status_code}",
        )
        greeting = session.post(
            f"{BASE_URL}/api/search",
            json={"query": "হ্যালো, তুমি কে?"},
            timeout=30,
        )
        greeting_data = greeting.json()
        greeting_message = greeting_data.get("message", "")
        check(
            greeting.status_code == 200
            and greeting_data.get("status") == "chat"
            and all(
                act in greeting_message
                for act in (
                    "বাংলাদেশ শ্রম আইন ২০০৬",
                    "ভোক্তা অধিকার সংরক্ষণ আইন ২০০৯",
                    "সাইবার সুরক্ষা আইন ২০২৬",
                )
            ),
            "Generic greeting returns the Bangla assistant introduction",
            greeting.text[:500],
        )

        user_id = create_user(session, "Primary")
        users.append(user_id)
        second_user_id = create_user(session, "Secondary")
        users.append(second_user_id)

        supported_cases = [
            (
                "Cyber unauthorized access and online fraud",
                "সাইবার সুরক্ষা আইনে অননুমোদিত প্রবেশ ও অনলাইন প্রতারণার শাস্তি কী?",
                True,
            ),
            (
                "Cyber bullying and digital identity theft",
                "সাইবার বুলিং ও ডিজিটাল পরিচয় চুরির বিরুদ্ধে কী প্রতিকার আছে?",
                True,
            ),
            (
                "Expired medicine and adulterated goods",
                "ভোক্তা অধিকার আইনে মেয়াদোত্তীর্ণ ওষুধ বা ভেজাল খাদ্য বিক্রির শাস্তি কী?",
                True,
            ),
            (
                "Counterfeit goods and deceptive weight",
                "নকল পণ্য তৈরি ও ওজনে কারচুপির বিরুদ্ধে ভোক্তা আইনে কী ব্যবস্থা আছে?",
                True,
            ),
            (
                "Illegal labour lockout penal provision",
                "শ্রম আইন অনুযায়ী বেআইনি লকআউটের শাস্তি কী?",
                True,
            ),
            (
                "Termination, unpaid wages, and accident compensation",
                "শ্রমিককে বিনা নোটিশে চাকরিচ্যুত করলে বকেয়া মজুরি ও কর্মস্থলের দুর্ঘটনার ক্ষতিপূরণ কীভাবে চাইব?",
                False,
            ),
        ]
        for label, query, require_criminal in supported_cases:
            response = session.post(
                f"{BASE_URL}/api/search",
                json={
                    "query": query,
                    "domain": "all",
                    "top_k": 3,
                    "user_id": user_id,
                },
                timeout=180,
            )
            data: dict[str, Any] = response.json()
            check(
                response.status_code == 200 and data.get("status") == "success",
                f"{label}: grounded search",
                response.text[:500],
            )
            results = data.get("results") or []
            plan = data.get("step_by_step_plan") or []
            check(
                bool(results)
                and bool(data.get("statute_citations"))
                and len(plan) == 4
                and all(step.get("step_number") == index for index, step in enumerate(plan, 1)),
                f"{label}: citations and four-step plan",
                str(data)[:500],
            )
            if require_criminal:
                check(
                    "ফৌজদারি" in str(data.get("case_type_bn", "")),
                    f"{label}: criminal treatment",
                    str(data.get("case_type_bn")),
                )

        out_of_scope_cases = [
            ("General murder case", "খুনের ফৌজদারি মামলায় জামিন ও বিচার প্রক্রিয়া কী?"),
            ("Robbery case", "ডাকাতি মামলার শাস্তি ও ধাপ কী?"),
            ("Land deed and mutation", "জমির দলিল জালিয়াতি ও নামজারি বাতিলের নিয়ম কী?"),
            ("Divorce and dower", "তালাক ও দেনমোহর আদায়ের নিয়ম কী?"),
        ]
        for label, query in out_of_scope_cases:
            response = session.post(
                f"{BASE_URL}/api/search",
                json={"query": query, "user_id": user_id},
                timeout=120,
            )
            data = response.json()
            check(
                response.status_code == 200
                and data.get("status") == "out_of_scope"
                and "এই বিষয়ে কোনো তথ্য নেই" in data.get("heading", "")
                and data.get("message") == OUT_OF_SCOPE_MESSAGE
                and not data.get("results"),
                f"{label}: strict out-of-scope fallback",
                response.text[:500],
            )

        with tempfile.TemporaryDirectory(prefix="legal-assistant-pdf-tests-") as directory:
            temp_dir = Path(directory)
            valid_pdf = temp_dir / "cyber-complaint.pdf"
            invalid_pdf = temp_dir / "land-deed.pdf"
            valid_pdf.write_bytes(
                create_text_pdf(
                    "Cyber Protection Act 2026: online fraud and unauthorized "
                    "computer access. Preserve transaction records and screenshots."
                )
            )
            invalid_pdf.write_bytes(
                create_text_pdf(
                    "Land deed, land dispute, khatian mutation, and murder FIR."
                )
            )

            with valid_pdf.open("rb") as pdf_file:
                response = session.post(
                    f"{BASE_URL}/api/sources/upload",
                    data={"user_id": str(user_id)},
                    files={"file": (valid_pdf.name, pdf_file, "application/pdf")},
                    timeout=180,
                )
            valid_data = response.json()
            source = valid_data.get("source") or {}
            source_id = source.get("id")
            check(
                response.status_code == 200
                and valid_data.get("status") == "success"
                and source.get("detected_domain") == "cyber_law"
                and source.get("page_count") == 1,
                "Valid cyber PDF is accepted and domain-labelled",
                response.text[:500],
            )

            if source_id is not None:
                analysis = session.post(
                    f"{BASE_URL}/api/analyze-case",
                    json={
                        "query": "সাইবার অনলাইন প্রতারণা বিষয়ে এই নথি অনুযায়ী কী করণীয়?",
                        "domain": "cyber_law",
                        "top_k": 3,
                        "user_id": user_id,
                        "source_id": source_id,
                    },
                    timeout=180,
                )
                analysis_data = analysis.json()
                excerpts = analysis_data.get("source_summary") or []
                check(
                    analysis.status_code == 200
                    and analysis_data.get("status") == "success"
                    and len(analysis_data.get("step_by_step_plan") or []) == 4
                    and bool(analysis_data.get("statute_citations"))
                    and bool(excerpts)
                    and str(excerpts[0].get("citation", "")).startswith("পৃষ্ঠা নং"),
                    "Valid PDF analysis cites source pages and grounded statutes",
                    analysis.text[:500],
                )

                secondary_sources = session.get(
                    f"{BASE_URL}/api/sources",
                    params={"user_id": second_user_id},
                    timeout=60,
                )
                check(
                    secondary_sources.status_code == 200
                    and source_id not in {item.get("id") for item in secondary_sources.json()},
                    "Uploaded source list is isolated by user",
                    secondary_sources.text[:500],
                )
                wrong_owner_delete = session.delete(
                    f"{BASE_URL}/api/sources/{source_id}",
                    params={"user_id": second_user_id},
                    timeout=60,
                )
                check(
                    wrong_owner_delete.status_code == 404,
                    "Another user cannot delete the uploaded source",
                    wrong_owner_delete.text[:500],
                )

            before_invalid = session.get(
                f"{BASE_URL}/api/sources", params={"user_id": user_id}, timeout=60
            ).json()
            with invalid_pdf.open("rb") as pdf_file:
                rejected = session.post(
                    f"{BASE_URL}/api/sources/upload",
                    data={"user_id": str(user_id)},
                    files={"file": (invalid_pdf.name, pdf_file, "application/pdf")},
                    timeout=180,
                )
            rejected_data = rejected.json()
            after_invalid = session.get(
                f"{BASE_URL}/api/sources", params={"user_id": user_id}, timeout=60
            ).json()
            check(
                rejected.status_code == 400
                and rejected_data.get("status") == "out_of_scope"
                and rejected_data.get("message") == OUT_OF_SCOPE_PDF_MESSAGE,
                "Out-of-domain land/criminal PDF is rejected with required message",
                rejected.text[:500],
            )
            check(
                len(after_invalid) == len(before_invalid)
                and all(item.get("filename") != invalid_pdf.name for item in after_invalid),
                "Rejected PDF is not persisted",
                str(after_invalid),
            )

        audit = session.get(
            f"{BASE_URL}/api/audit-logs",
            params={"user_id": user_id, "limit": 100},
            timeout=60,
        ).json()
        no_info_logs = [
            item for item in audit.get("logs", [])
            if item.get("evidence_status") == "No Info (Out of Scope)"
        ]
        check(bool(no_info_logs), "Rejected out-of-scope queries are audited")

    finally:
        cleanup_test_users(users)

    print(f"\nResult: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main_test())
