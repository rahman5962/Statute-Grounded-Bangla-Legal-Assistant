# Statute-Grounded Bangla Legal Assistant

FastAPI service and web interface for searching Bangladesh labour, consumer-rights,
and cyber statutes.

## Run the API

Install the project dependencies and start the application from the repository root:

```bash
python -m pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) for the search page or
[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for the API reference.
The ChromaDB collection and embedding model are loaded on the first search request,
not during server startup. To restrict browser origins, set `CORS_ORIGINS` to a
comma-separated list of allowed origins before starting Uvicorn.

The API includes registration and login, domain-filtered statute search, Bengali
complaint/notice drafts, audit-log JSON/CSV export, and user-scoped bookmarks.

## PDF document Q&A

The chat's **PDF দিয়ে প্রশ্ন করুন** action accepts up to five PDFs per
conversation (20 MB and 100 pages per file). Uploads are validated and read
page by page. Page-aware chunks and embeddings are kept in a separate ChromaDB
collection; the original PDFs are stored in the ignored
`backend/data/user_documents/` directory, while SQLite stores document metadata.
Documents are scoped to the logged-in user and conversation, and can be removed
from the **আমার PDF** panel. The existing **আইনি PDF উৎস** workflow remains
available for the three supported statutes.

Document questions return matching passages with filename and page citations,
and abstain when no relevant passage is retrieved. This project has no text
generation model or external AI provider configured, so answers are deliberately
evidence excerpts rather than generated summaries; uploaded contents are not
sent to a third party. Scanned pages are OCRed when Tesseract, Poppler, and the
Python `pytesseract`/`pdf2image` packages are available. Otherwise, the upload
reports that OCR is unavailable instead of treating a scan as successfully read.
