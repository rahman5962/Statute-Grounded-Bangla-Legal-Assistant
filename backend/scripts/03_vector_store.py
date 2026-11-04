"""Statute-Grounded Vector Store & Hybrid Metadata Search Engine.

Bangladesh Labour Act, 2006 (375 Sections: Active, Amended, Repealed).
Author: Prarthona Biswas Puja (241-35-187)
Module: ChromaDB Vector Indexing & Semantic Retrieval (FR-02 & FR-03)
"""

import json
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions

# প্রজেক্টের ফাইল পাথ কনফিগারেশন
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
CHUNKS_FILE = (
    PROJECT_ROOT / "backend" / "data" / "processed" / "labour_act_chunks.json"
)
CHROMA_DB_DIR = PROJECT_ROOT / "backend" / "data" / "chroma_db"

COLLECTION_NAME = "bd_labour_act_2006"
EMBEDDING_MODEL_NAME = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)


def get_vector_collection():
  """ChromaDB ক্লায়েন্ট এবং মাল্টিলিঙ্গুয়াল বাংলা এম্বেডিং ফাংশন ইনিশিয়ালাইজ করে।"""
  CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
  client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))

  embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
      model_name=EMBEDDING_MODEL_NAME
  )

  collection = client.get_or_create_collection(
      name=COLLECTION_NAME,
      embedding_function=embedding_fn,
      metadata={"hnsw:space": "cosine"},
  )
  return collection


def build_vector_store():
  """৩৭৫টি আইনি ধারা মেটাডাটাসহ ChromaDB-তে ইনডেক্স করে।"""
  if not CHUNKS_FILE.exists():
    raise FileNotFoundError(f"[!] চাংক ফাইল পাওয়া যায়নি: {CHUNKS_FILE}")

  with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
    chunks = json.load(f)

  print(f"[*] মোট {len(chunks)} টি ধারা লোড হয়েছে।")
  print(f"[*] এম্বেডিং মডেল লোড হচ্ছে: {EMBEDDING_MODEL_NAME} ...")

  collection = get_vector_collection()

  ids = []
  documents = []
  metadatas = []

  for idx, chunk in enumerate(chunks):
    # ডুপ্লিকেট আইডি এড়াতে সেকশন নম্বর ও ইনডেক্সের সমন্বয়
    sec_id = f"{chunk['id']}_{idx}"
    ids.append(sec_id)
    documents.append(chunk["content"])

    metadatas.append({
        "act_name": str(chunk.get("act_name", "")),
        "chapter": str(chunk.get("chapter", "")),
        "section_number": str(chunk.get("section_number", "")),
        "section_title": str(chunk.get("section_title", "")),
        "legal_status": str(chunk.get("legal_status", "")),
        "amendment_provenance": str(chunk.get("amendment_provenance", "")),
    })

  # ব্যাচ আকারে ডেটাবেজে ইনসার্ট/আপসার্ট করা
  BATCH_SIZE = 100
  for i in range(0, len(ids), BATCH_SIZE):
    collection.upsert(
        ids=ids[i : i + BATCH_SIZE],
        documents=documents[i : i + BATCH_SIZE],
        metadatas=metadatas[i : i + BATCH_SIZE],
    )
    print(
        f"  -> ইনডেক্সিং সম্পন্ন: {min(i + BATCH_SIZE, len(ids))}/{len(ids)}"
    )

  print("\n" + "=" * 65)
  print("✅ ChromaDB ভেক্টর ডেটাবেজ সফলভাবে তৈরি ও সংরক্ষিত হয়েছে!")
  print(f"📁 ডেটাবেজ পাথ: {CHROMA_DB_DIR}")
  print(f"📊 মোট ইনডেক্সকৃত রেকর্ড: {collection.count()}")
  print("=" * 65)
  return collection


def test_retrieval(collection):
  """সিম্যান্টিক সার্চ এবং মেটাডাটা ফিল্টারিং যাচাই করার ডায়াগনস্টিক টেস্ট।"""
  print("\n🔍 [টেস্ট ১] সাধারণ বাংলা প্রশ্নের মাধ্যমে সিম্যান্টিক সার্চ:")
  query_text = "শ্রমিকের ওভারটাইম বা অতিরিক্ত কাজের মজুরি কীভাবে হিসাব করা হবে?"
  print(f"   প্রশ্ন: '{query_text}'")

  results = collection.query(query_texts=[query_text], n_results=2)

  for i in range(len(results["ids"][0])):
    meta = results["metadatas"][0][i]
    dist = results["distances"][0][i]
    similarity = round(1 - dist, 4)
    print(
        f"   [{i+1}] ধারা: {meta['section_number']} | শিরোনাম:"
        f" {meta['section_title']}"
    )
    print(
        f"       অবস্থা: {meta['legal_status']} | সিমিলারিটি স্কোর:"
        f" {similarity}"
    )

  print("\n🔍 [টেস্ট ২] সুনির্দিষ্ট বিলুপ্ত ধারা (ধারা ১৮৪) মেটাডাটা ফিল্টার সার্চ:")
  exact_res = collection.get(where={"section_number": "১৮৪"})
  if exact_res["ids"]:
    meta = exact_res["metadatas"][0]
    print(f"   পাওয়া গেছে -> ধারা: {meta['section_number']}")
    print(f"   বর্তমান অবস্থা: {meta['legal_status']}")
    print(f"   রেফারেন্স: {meta['amendment_provenance']}")
  print("=" * 65)


if __name__ == "__main__":
  col = build_vector_store()
  test_retrieval(col)