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
