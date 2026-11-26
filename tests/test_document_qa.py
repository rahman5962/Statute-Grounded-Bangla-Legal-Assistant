from __future__ import annotations

import io
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import database  # noqa: E402
import main  # noqa: E402


class MemoryDocumentCollection:
    def __init__(self) -> None:
        self.records: dict[str, tuple[str, dict[str, Any]]] = {}

    @staticmethod
    def _matches(metadata: dict[str, Any], where: dict[str, Any]) -> bool:
        if "$and" in where:
            return all(
                MemoryDocumentCollection._matches(metadata, item)
                for item in where["$and"]
            )
        return all(
            value.get("$in", []) and metadata.get(key) in value["$in"]
            if isinstance(value, dict)
            else metadata.get(key) == value
            for key, value in where.items()
        )

    def upsert(
        self,
        *,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        for item_id, text, metadata in zip(ids, documents, metadatas):
            self.records[item_id] = (text, metadata)

    def count(self, *, where: dict[str, Any]) -> int:
        return sum(
            self._matches(metadata, where)
            for _, metadata in self.records.values()
        )

    def query(
        self,
        *,
        query_texts: list[str],
        n_results: int,
        where: dict[str, Any],
        include: list[str],
    ) -> dict[str, list[list[Any]]]:
        ignored = {"the", "and", "for", "with", "what", "is", "of", "a", "to"}
        terms = set(re.findall(r"[a-z0-9]+", query_texts[0].casefold())) - ignored
        ranked = []
        for item_id, (text, metadata) in self.records.items():
            if not self._matches(metadata, where):
                continue
            text_terms = set(re.findall(r"[a-z0-9]+", text.casefold())) - ignored
            overlap = len(terms & text_terms)
            ranked.append((overlap, item_id, text, metadata))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        selected = ranked[:n_results]
        distances = [0.15 if item[0] else 0.95 for item in selected]
        return {
            "ids": [[item[1] for item in selected]],
            "documents": [[item[2] for item in selected]],
            "metadatas": [[item[3] for item in selected]],
            "distances": [distances],
        }

    def delete(
        self,
        *,
        where: dict[str, Any] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        for item_id, (_, metadata) in list(self.records.items()):
            if (ids and item_id in ids) or (
                where and self._matches(metadata, where)
            ):
                del self.records[item_id]


def create_text_pdf(pages: list[str]) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_reference}
                )
            }
        )
        escaped_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content = DecodedStreamObject()
        content.set_data(
            f"BT /F1 12 Tf 50 750 Td ({escaped_text}) Tj ET".encode("ascii")
        )
        page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def document_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(main, "DOCUMENT_UPLOAD_DIR", tmp_path / "documents")
    collection = MemoryDocumentCollection()
    monkeypatch.setattr(main, "get_document_collection", lambda: collection)
    with TestClient(main.app) as client:
        yield client, collection, tmp_path


def register_and_login(client: TestClient, suffix: str) -> int:
    email = f"{suffix}@example.test"
    password = "test-password-123"
    response = client.post(
        "/api/register",
        json={
            "full_name": f"Test {suffix}",
            "email": email,
            "password": password,
            "confirm_password": password,
        },
    )
    assert response.status_code == 200
    response = client.post(
        "/api/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    assert "ainsathi_session" in response.cookies
    return int(response.json()["user"]["id"])


def test_upload_retrieval_citations_and_scoped_deletion(document_client) -> None:
    client, collection, tmp_path = document_client
    conversation_id = "chat-test-12345"
    pdf = create_text_pdf(
        [
            "Project Overview. This report introduces a local research project.",
            "Project Objective. The project objective is to help students understand climate risks.",
        ]
    )

    assert client.get(
        "/api/documents",
        params={"user_id": 1, "conversation_id": conversation_id},
    ).status_code == 401
    user_id = register_and_login(client, "primary")

    uploaded = client.post(
        "/api/documents/upload",
        data={"user_id": user_id, "conversation_id": conversation_id},
        files={"file": ("research.pdf", pdf, "application/pdf")},
    )
    assert uploaded.status_code == 200, uploaded.text
    document = uploaded.json()["document"]
    assert document["filename"] == "research.pdf"
    assert document["page_count"] == 2
    assert document["size_bytes"] == len(pdf)
    assert (tmp_path / "documents" / str(user_id) / f"{document['document_id']}.pdf").exists()

    duplicate = client.post(
        "/api/documents/upload",
        data={"user_id": user_id, "conversation_id": conversation_id},
        files={"file": ("research-copy.pdf", pdf, "application/pdf")},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["document"]["document_id"] == document["document_id"]

    second_pdf = create_text_pdf(
        ["Research Method. The project uses a survey to collect student feedback."]
    )
    second_upload = client.post(
        "/api/documents/upload",
        data={"user_id": user_id, "conversation_id": conversation_id},
        files={"file": ("methods.pdf", second_pdf, "application/pdf")},
    )
    assert second_upload.status_code == 200, second_upload.text
    second_document = second_upload.json()["document"]

    listed = client.get(
        "/api/documents",
        params={"user_id": user_id, "conversation_id": conversation_id},
    )
    assert {
        item["document_id"] for item in listed.json()
    } == {document["document_id"], second_document["document_id"]}
    other_conversation = client.get(
        "/api/documents",
        params={"user_id": user_id, "conversation_id": "chat-other-12345"},
    )
    assert other_conversation.json() == []

    answer = client.post(
        "/api/documents/ask",
        json={
            "query": "What is the project objective?",
            "user_id": user_id,
            "conversation_id": conversation_id,
            "document_ids": [document["document_id"]],
        },
    )
    assert answer.status_code == 200, answer.text
    citation = answer.json()["document_citations"][0]
    assert citation["filename"] == "research.pdf"
    assert citation["page_number"] == 2
    assert "help students understand climate risks" in citation["excerpt"]

    follow_up = client.post(
        "/api/documents/ask",
        json={
            "query": "Explain the previous point in more detail.",
            "user_id": user_id,
            "conversation_id": conversation_id,
            "document_ids": [document["document_id"]],
            "history": [{"query": "What is the project objective?"}],
        },
    )
    assert follow_up.status_code == 200
    assert follow_up.json()["document_citations"][0]["page_number"] == 2

    unsupported = client.post(
        "/api/documents/ask",
        json={
            "query": "Explain the history of volcanoes.",
            "user_id": user_id,
            "conversation_id": conversation_id,
            "document_ids": [document["document_id"]],
        },
    )
    assert unsupported.status_code == 200
    assert unsupported.json()["status"] == "needs_verification"
    assert unsupported.json()["document_citations"] == []

    cross_conversation = client.post(
        "/api/documents/ask",
        json={
            "query": "What is the project objective?",
            "user_id": user_id,
            "conversation_id": "chat-other-12345",
            "document_ids": [document["document_id"]],
        },
    )
    assert cross_conversation.status_code == 404

    second_user_id = register_and_login(client, "secondary")
    cross_user = client.post(
        "/api/documents/ask",
        json={
            "query": "What is the project objective?",
            "user_id": second_user_id,
            "conversation_id": conversation_id,
            "document_ids": [document["document_id"]],
        },
    )
    assert cross_user.status_code == 404

    client.post(
        "/api/login",
        json={"email": "primary@example.test", "password": "test-password-123"},
    )
    deleted = client.delete(
        f"/api/documents/{document['document_id']}",
        params={"user_id": user_id, "conversation_id": conversation_id},
    )
    assert deleted.status_code == 200, deleted.text
    assert collection.records
    assert not (tmp_path / "documents" / str(user_id) / f"{document['document_id']}.pdf").exists()
    assert (tmp_path / "documents" / str(user_id) / f"{second_document['document_id']}.pdf").exists()
    deleted_conversation = client.delete(
        f"/api/documents/conversations/{conversation_id}",
        params={"user_id": user_id},
    )
    assert deleted_conversation.status_code == 200
    assert deleted_conversation.json()["deleted_count"] == 1
    assert not collection.records
    assert not (tmp_path / "documents" / str(user_id) / f"{second_document['document_id']}.pdf").exists()
    assert client.post("/api/logout").status_code == 200
    assert client.get(
        "/api/documents",
        params={"user_id": user_id, "conversation_id": conversation_id},
    ).status_code == 401


def test_upload_rejects_non_pdf_and_scanned_pdf_without_ocr(document_client) -> None:
    client, _, _ = document_client
    user_id = register_and_login(client, "validation")
    conversation_id = "chat-validation-123"

    invalid_mime = client.post(
        "/api/documents/upload",
        data={"user_id": user_id, "conversation_id": conversation_id},
        files={"file": ("fake.pdf", b"%PDF-1.4 invalid", "text/plain")},
    )
    assert invalid_mime.status_code == 400
    assert "MIME" in invalid_mime.json()["detail"]

    corrupted = client.post(
        "/api/documents/upload",
        data={"user_id": user_id, "conversation_id": conversation_id},
        files={"file": ("broken.pdf", b"not a pdf", "application/pdf")},
    )
    assert corrupted.status_code == 400

    scanned = client.post(
        "/api/documents/upload",
        data={"user_id": user_id, "conversation_id": conversation_id},
        files={"file": ("scan.pdf", create_text_pdf([""]), "application/pdf")},
    )
    assert scanned.status_code == 400
    assert "OCR" in scanned.json()["detail"] or "পাঠ্য" in scanned.json()["detail"]
