"""Multi-Domain Statute-Grounded Vector Store & Hybrid Metadata Search Engine.

Domains:
  1. Bangladesh Labour Act, 2006 (375 Sections)
  2. Consumer Rights Protection Act, 2009 (82 Sections)
  3. Cyber Protection Act, 2026 (51 Sections)

Unified Collection: bd_legal_multi_domain_2026 (Total: 508 Sections)
Author: Prarthona Biswas Puja (241-35-187) / Sazim Rahman
Module: ChromaDB Vector Indexing & Semantic Retrieval (FR-02 & FR-03)
"""

import json
import threading
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions

# প্রজেক্ট ফাইল পাথ কনফিগারেশন
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
PROCESSED_DIR = PROJECT_ROOT / "backend" / "data" / "processed"

LABOUR_CHUNKS_FILE = PROCESSED_DIR / "labour_act_chunks.json"
NEW_DOMAINS_FILE = PROCESSED_DIR / "new_domains_chunks.json"
CHROMA_DB_DIR = PROJECT_ROOT / "backend" / "data" / "chroma_db"

COLLECTION_NAME = "bd_legal_multi_domain_2026"
DOCUMENT_COLLECTION_NAME = "uploaded_pdf_documents"
EMBEDDING_MODEL_NAME = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
_client = None
_embedding_function = None
_initialization_lock = threading.Lock()


def _get_client():
    global _client
    if _client is None:
        with _initialization_lock:
            if _client is None:
                CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
                _client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    return _client


def _get_embedding_function():
    global _embedding_function
    if _embedding_function is None:
        with _initialization_lock:
            if _embedding_function is None:
                _embedding_function = (
                    embedding_functions.SentenceTransformerEmbeddingFunction(
                        model_name=EMBEDDING_MODEL_NAME
                    )
                )
    return _embedding_function

def get_vector_collection():
    """ChromaDB ক্লায়েন্ট এবং মাল্টিলিঙ্গুয়াল বাংলা এম্বেডিং ফাংশন ইনিশিয়ালাইজ করে।"""
    return _get_client().get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def get_document_collection():
    """Return a separate, privacy-filtered collection for uploaded PDF chunks."""
    return _get_client().get_or_create_collection(
        name=DOCUMENT_COLLECTION_NAME,
        embedding_function=_get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def load_all_chunks():
    """৩টি আইনি ডোমেইনের চাঙ্ক ফাইলগুলো লোড করে মেটাডাটা স্ট্যান্ডার্ডাইজ করে।"""
    all_chunks = []

    # ১. বাংলাদেশ শ্রম আইন, ২০০৬ (৩৭৫টি ধারা)
    if not LABOUR_CHUNKS_FILE.exists():
        raise FileNotFoundError(f"[!] শ্রম আইনের চাঙ্ক ফাইল পাওয়া যায়নি: {LABOUR_CHUNKS_FILE}")

    with open(LABOUR_CHUNKS_FILE, "r", encoding="utf-8") as f:
        labour_chunks = json.load(f)
        for c in labour_chunks:
            if not c.get("domain"):
                c["domain"] = "labour_law"
            if not c.get("domain_bn"):
                c["domain_bn"] = "শ্রম আইন, ২০০৬"
        all_chunks.extend(labour_chunks)
        print(f"[+] শ্রম আইন, ২০০৬ লোড হয়েছে: {len(labour_chunks)}টি ধারা")

    # ২. নতুন ডোমেইনসমূহ: ভোক্তা অধিকার সংরক্ষণ আইন (৮২টি ধারা) + সাইবার সুরক্ষা আইন (৫১টি ধারা)
    if not NEW_DOMAINS_FILE.exists():
        raise FileNotFoundError(f"[!] নতুন ডোমেইনের চাঙ্ক ফাইল পাওয়া যায়নি: {NEW_DOMAINS_FILE}")

    with open(NEW_DOMAINS_FILE, "r", encoding="utf-8") as f:
        new_chunks = json.load(f)
        for c in new_chunks:
            if not c.get("domain"):
                c["domain"] = "general"
            if not c.get("domain_bn"):
                c["domain_bn"] = "সাধারণ আইন"
        all_chunks.extend(new_chunks)
        print(f"[+] নতুন ডোমেইনসমূহ লোড হয়েছে: {len(new_chunks)}টি ধারা")

    print(f"[*] সর্বমোট লোডকৃত ধারা: {len(all_chunks)}টি")
    return all_chunks


def build_vector_store():
    """৩টি আইনি ডোমেইনের সর্বমোট ৫০৮টি ধারা মেটাডাটাসহ ChromaDB-তে ইনডেক্স করে।"""
    all_chunks = load_all_chunks()

    collection = get_vector_collection()
    print(f"[*] এম্বেডিং মডেল লোড হচ্ছে: {EMBEDDING_MODEL_NAME} ...")

    ids = []
    documents = []
    metadatas = []

    for idx, chunk in enumerate(all_chunks):
        domain = str(chunk.get("domain") or "labour_law")
        chunk_id = str(chunk.get("id") or f"sec_{idx}")
        # f"{domain}_{chunk_id}_{idx}" ফরম্যাটে স্বতন্ত্র আইডি
        unique_id = f"{domain}_{chunk_id}_{idx}"

        content = str(chunk.get("content") or "").strip()
        if not content:
            continue

        ids.append(unique_id)
        documents.append(content)

        metadata = {
            "domain": domain,
            "domain_bn": str(chunk.get("domain_bn") or ""),
            "act_name": str(chunk.get("act_name") or ""),
            "chapter": str(chunk.get("chapter") or ""),
            "section_number": str(chunk.get("section_number") or ""),
            "section_title": str(chunk.get("section_title") or ""),
            "legal_status": str(chunk.get("legal_status") or "সক্রিয় (Active)"),
            "amendment_provenance": str(chunk.get("amendment_provenance") or "মূল আইন"),
        }
        metadatas.append(metadata)

    # ব্যাচ আকারে (১০০টি করে) আপসার্ট করা
    BATCH_SIZE = 100
    for i in range(0, len(ids), BATCH_SIZE):
        batch_ids = ids[i : i + BATCH_SIZE]
        batch_docs = documents[i : i + BATCH_SIZE]
        batch_metas = metadatas[i : i + BATCH_SIZE]

        collection.upsert(
            ids=batch_ids,
            documents=batch_docs,
            metadatas=batch_metas,
        )
        print(f"  -> ইনডেক্সিং সম্পন্ন: {min(i + BATCH_SIZE, len(ids))}/{len(ids)}")

    print("\n" + "=" * 65)
    print("✅ মাল্টি-ডোমেইন ChromaDB ভেক্টর ডেটাবেজ সফলভাবে তৈরি ও সংরক্ষিত হয়েছে!")
    print(f"📁 ডেটাবেজ পাথ: {CHROMA_DB_DIR}")
    print(f"🏷️  কালেকশন নাম: {COLLECTION_NAME}")
    print(f"📊 মোট ইনডেক্সকৃত রেকর্ড: {collection.count()}")
    print("=" * 65)
    return collection


def test_retrieval(collection):
    """৩টি ডোমেইনেই সিম্যান্টিক সার্চ এবং মেটাডাটা ফিল্টারিং যাচাই করার টেস্ট।"""
    print("\n🔍 [ডায়াগনস্টিক টেস্ট ১: শ্রম আইন]")
    q_labour = "শ্রমিকের অতিরিক্ত কাজের মজুরি বা ওভারটাইম ভাতা কীভাবে প্রদান করতে হবে?"
    res_labour = collection.query(query_texts=[q_labour], n_results=1, where={"domain": "labour_law"})
    if res_labour["ids"] and res_labour["ids"][0]:
        m = res_labour["metadatas"][0][0]
        dist = res_labour["distances"][0][0]
        print(f"   আইন: {m['domain_bn']} | ধারা: {m['section_number']} - {m['section_title']}")
        print(f"   সিমিলারিটি স্কোর: {round(1 - dist, 4)} | স্ট্যাটাস: {m['legal_status']}")

    print("\n🔍 [ডায়াগনস্টিক টেস্ট ২: ভোক্তা অধিকার আইন]")
    q_consumer = "ভেজাল পণ্য বা ওষুধ বিক্রির অভিযোগ ও দণ্ড সম্পর্কিত বিধান"
    res_consumer = collection.query(query_texts=[q_consumer], n_results=1, where={"domain": "consumer_rights"})
    if res_consumer["ids"] and res_consumer["ids"][0]:
        m = res_consumer["metadatas"][0][0]
        dist = res_consumer["distances"][0][0]
        print(f"   আইন: {m['domain_bn']} | ধারা: {m['section_number']} - {m['section_title']}")
        print(f"   সিমিলারিটি স্কোর: {round(1 - dist, 4)} | স্ট্যাটাস: {m['legal_status']}")

    print("\n🔍 [ডায়াগনস্টিক টেস্ট ৩: সাইবার সুরক্ষা / নিরাপত্তা আইন]")
    q_cyber = "অননুমোদিত প্রবেশ বা কম্পিউটার সিস্টেমে হ্যাকিং করার শাস্তি"
    res_cyber = collection.query(query_texts=[q_cyber], n_results=1, where={"domain": "cyber_law"})
    if res_cyber["ids"] and res_cyber["ids"][0]:
        m = res_cyber["metadatas"][0][0]
        dist = res_cyber["distances"][0][0]
        print(f"   আইন: {m['domain_bn']} | ধারা: {m['section_number']} - {m['section_title']}")
        print(f"   সিমিলারিটি স্কোর: {round(1 - dist, 4)} | স্ট্যাটাস: {m['legal_status']}")

    print("\n" + "=" * 65)


if __name__ == "__main__":
    col = build_vector_store()
    test_retrieval(col)
