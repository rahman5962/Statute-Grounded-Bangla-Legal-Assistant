"""Page-aware PDF text extraction and document-aware chunking."""

from __future__ import annotations

import io
import re
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class DocumentProcessingError(ValueError):
    """Raised when a PDF cannot be safely extracted for document Q&A."""


CHUNK_SIZE = 1400
MAX_DOCUMENT_CHARS = 1_000_000


def _ocr_page(content: bytes, page_number: int) -> str:
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        raise DocumentProcessingError(
            "এই PDF-এ selectable text নেই। স্ক্যান করা PDF পড়তে Tesseract OCR, "
            "বাংলা+ইংরেজি language data এবং pdf2image/Poppler ইনস্টল করুন।"
        ) from exc

    try:
        languages = set(pytesseract.get_languages(config=""))
        language = "+".join(
            item for item in ("ben", "eng") if item in languages
        )
        if not language:
            raise DocumentProcessingError(
                "স্ক্যান করা PDF পড়ার জন্য Tesseract-এর বাংলা (ben) বা ইংরেজি "
                "(eng) language data ইনস্টল নেই।"
            )
        image = convert_from_bytes(
            content,
            first_page=page_number,
            last_page=page_number,
            dpi=180,
            fmt="png",
            thread_count=1,
        )[0]
        return pytesseract.image_to_string(image, lang=language, timeout=30).strip()
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentProcessingError(
            f"পৃষ্ঠা {page_number}-এর OCR সম্পন্ন করা যায়নি: {exc}"
        ) from exc


def _page_contains_image(page: Any) -> bool:
    resources = page.get("/Resources")
    if resources is None:
        return False
    resources = resources.get_object()
    xobjects = resources.get("/XObject")
    if xobjects is None:
        return False
    xobjects = xobjects.get_object()
    for reference in xobjects.values():
        image = reference.get_object()
        if image.get("/Subtype") == "/Image":
            return True
    return False


def extract_pdf_pages(
    content: bytes,
    *,
    max_pages: int,
    max_characters: int = MAX_DOCUMENT_CHARS,
) -> tuple[int, list[tuple[int, str]]]:
    if not content or not content.lstrip().startswith(b"%PDF-"):
        raise DocumentProcessingError("ফাইলটি বৈধ PDF নয় বা খালি।")

    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentProcessingError(
                "পাসওয়ার্ড-সুরক্ষিত PDF পড়া যায়নি; আনলক করা PDF আপলোড করুন।"
            )
        page_count = len(reader.pages)
        if page_count == 0:
            raise DocumentProcessingError("PDF-এ কোনো পৃষ্ঠা নেই।")
        if page_count > max_pages:
            raise DocumentProcessingError(
                f"একটি PDF-এ সর্বোচ্চ {max_pages}টি পৃষ্ঠা গ্রহণ করা যায়।"
            )

        pages: list[tuple[int, str]] = []
        total_characters = 0
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = (page.extract_text() or "").strip()
            if len(page_text) < 20 and _page_contains_image(page):
                page_text = _ocr_page(content, page_number) or page_text
            total_characters += len(page_text)
            if total_characters > max_characters:
                raise DocumentProcessingError(
                    f"PDF থেকে নির্যাস করা লেখা {max_characters:,} অক্ষরের বেশি।"
                )
            if page_text:
                pages.append((page_number, page_text))
    except DocumentProcessingError:
        raise
    except (PdfReadError, OSError, ValueError, KeyError, TypeError) as exc:
        raise DocumentProcessingError(
            "PDF পড়া যায়নি। ফাইলটি বৈধ ও খোলার উপযোগী কি না যাচাই করুন।"
        ) from exc

    if not pages:
        raise DocumentProcessingError(
            "PDF থেকে কোনো পাঠ্য পাওয়া যায়নি। স্ক্যান করা PDF-এর OCR সুবিধা "
            "ইনস্টল আছে কি না যাচাই করুন।"
        )
    return page_count, pages


def _looks_like_heading(text: str) -> bool:
    candidate = text.strip()
    if not candidate or len(candidate) > 140:
        return False
    if re.match(
        r"^(?:chapter|section|part|অধ্যায়|অধ্যায়|ধারা|পরিচ্ছেদ|"
        r"\d+(?:\.\d+)*[.)]?)\b",
        candidate,
        flags=re.IGNORECASE,
    ):
        return True
    return not re.search(r"[.!?।॥]\s*$", candidate) and len(candidate.split()) <= 14


def _split_long_text(text: str, limit: int) -> list[str]:
    pieces: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        boundary = max(
            remaining.rfind(mark, 0, limit)
            for mark in ("।", ".", "!", "?", "\n")
        )
        if boundary < limit // 2:
            boundary = remaining.rfind(" ", 0, limit)
        if boundary < limit // 2:
            boundary = limit
        pieces.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def chunk_pdf_pages(
    document_id: str,
    filename: str,
    pages: list[tuple[int, str]],
    *,
    chunk_size: int = CHUNK_SIZE,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for page_number, page_text in pages:
        section_title = ""
        current_parts: list[str] = []
        current_length = 0
        chunk_index = 0

        def append_chunk(text: str) -> None:
            nonlocal chunk_index
            chunk_id = f"{document_id}:p{page_number}:c{chunk_index}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "filename": filename,
                    "page_number": page_number,
                    "section_title": section_title,
                    "chunk_index": chunk_index,
                    "text": text,
                }
            )
            chunk_index += 1

        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", page_text.replace("\r\n", "\n"))
            if paragraph.strip()
        ]
        for paragraph in paragraphs:
            lines = paragraph.splitlines()
            heading = lines[0].strip() if lines and _looks_like_heading(lines[0]) else ""
            if heading and len(paragraph) <= chunk_size:
                if current_parts:
                    append_chunk("\n\n".join(current_parts))
                    current_parts = []
                    current_length = 0
                section_title = heading

            if len(paragraph) > chunk_size:
                if current_parts:
                    append_chunk("\n\n".join(current_parts))
                    current_parts = []
                    current_length = 0
                for piece in _split_long_text(paragraph, chunk_size):
                    append_chunk(piece)
                continue

            if current_parts and current_length + len(paragraph) + 2 > chunk_size:
                append_chunk("\n\n".join(current_parts))
                current_parts = []
                current_length = 0
            current_parts.append(paragraph)
            current_length += len(paragraph) + 2

        if current_parts:
            append_chunk("\n\n".join(current_parts))
    return chunks
