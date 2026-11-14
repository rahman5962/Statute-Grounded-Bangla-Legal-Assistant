"""
Multi-Domain Legal Statute Scraper & Chunker (Laws of Bangladesh)
Domains:
  1. Consumer Rights Law (ভোক্তা-অধিকার সংরক্ষণ আইন, ২০০৯)
  2. Cyber Law (সাইবার নিরাপত্তা আইন, ২০২৩ / সাইবার সুরক্ষা অধ্যাদেশ)
Compatible with backend/scripts/03_vector_store.py schema.
"""

import json
from pathlib import Path
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RAW_DIR = PROJECT_ROOT / "backend" / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "backend" / "data" / "processed"
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://bdlaws.minlaw.gov.bd/"
INDEX_URL = "https://bdlaws.minlaw.gov.bd/laws-of-bangladesh-chronological-index.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "bn,en;q=0.9",
}

DOMAINS_CONFIG = [
    {
        "domain": "consumer_rights",
        "domain_bn": "ভোক্তা অধিকার আইন",
        "keywords": ["ভোক্তা-অধিকার সংরক্ষণ আইন", "ভোক্তা অধিকার সংরক্ষণ আইন"],
        "id_scan_range": range(1005, 1025),  # ২০০৯ সালের আইনসমূহের রেঞ্জ
    },
    {
        "domain": "cyber_law",
        "domain_bn": "সাইবার আইন",
        "keywords": ["সাইবার সুরক্ষা", "সাইবার নিরাপত্তা আইন"],
        "id_scan_range": range(1435, 1465),  # ২০২৩ সালের আইনসমূহের রেঞ্জ
    },
]

SECTION_RE = re.compile(r"^([১২৩৪৫৬৭৮৯০]+[ক-হ]?)\s*[\।৷:\.]\s*(.*)$")


def decode_html_bytes(raw_bytes: bytes) -> str:
    """সার্ভার বাইটের আসল এনকোডিং (UTF-16 / UTF-8) শনাক্ত করে ডিকোড করে।"""
    for enc in ["utf-8", "utf-16", "utf-16-le", "windows-1252"]:
        try:
            decoded = raw_bytes.decode(enc)
            if "<html" in decoded.lower() or "ধারা" in decoded or "আইন" in decoded:
                return decoded
        except (UnicodeDecodeError, LookupError):
            continue
    return raw_bytes.decode("utf-8", errors="ignore")


def fetch_page(session: requests.Session, url: str) -> str:
    try:
        resp = session.get(url, timeout=30, verify=False)
        if resp.status_code == 200:
            return decode_html_bytes(resp.content)
    except Exception:
        pass
    return ""


def find_exact_act_url(session: requests.Session, config: dict) -> tuple[str, str]:
    """ইনডেক্স পেজ এবং প্রয়োজনে আইডি রেঞ্জ স্ক্যান করে আইনের সঠিক URL বের করে।"""
    keywords = config["keywords"]
    print(f"[*] '{config['domain_bn']}' এর সঠিক লিংক খোঁজা হচ্ছে...")

    # ধাপ ১: ক্রনোলজিক্যাল ইনডেক্সে খোঁজা
    index_html = fetch_page(session, INDEX_URL)
    if index_html:
        soup = BeautifulSoup(index_html, "html.parser")
        matches = []
        for a in soup.find_all("a", href=True):
            title = re.sub(r"\s+", " ", a.get_text(strip=True))
            href = a["href"]
            if any(kw in title for kw in keywords) and "act-" in href:
                details_href = re.sub(r"act-(\d+)\.html", r"act-details-\1.html", href)
                matches.append((urljoin(BASE_URL, details_href), title))
        main_matches = [m for m in matches if "সংশোধন" not in m[1]] or matches
        if main_matches:
            url, title = main_matches[-1]
            print(f"[+] ইনডেক্স থেকে পাওয়া গেছে: {title} -> {url}")
            return url, title

    # ধাপ ২: নির্দিষ্ট বছরের আইডি রেঞ্জে স্ক্যান করা
    print(f"[*] আইডি রেঞ্জ স্ক্যান করা হচ্ছে ({config['id_scan_range'].start}-{config['id_scan_range'].stop - 1})...")
    for act_id in config["id_scan_range"]:
        test_url = f"{BASE_URL}act-details-{act_id}.html"
        html = fetch_page(session, test_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        page_title = soup.title.get_text(strip=True) if soup.title else ""
        if any(kw in page_title for kw in keywords):
            clean_title = re.sub(r"\s+", " ", page_title)
            print(f"[+] স্ক্যান করে পাওয়া গেছে: {clean_title} -> {test_url}")
            return test_url, clean_title

    return "", ""


def extract_clean_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside"]):
        tag.decompose()

    lines = []
    for line in soup.get_text(separator="\n").splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip().replace("\x00", "")
        if cleaned:
            lines.append(cleaned)
    return lines


def detect_status(text: str) -> tuple[str, str]:
    if (len(text) < 45 and "বিলুপ্ত" in text) or text.strip() in ["[বিলুপ্ত]", "বিলুপ্ত", "[***]"]:
        return "বিলুপ্ত (Repealed)", "সংশোধনীর মাধ্যমে ধারাটি বিলুপ্ত করা হয়েছে"
    if any(k in text for k in ["প্রতিস্থাপিত", "সন্নিবেশিত", "সংশোধিত", "সংযোজিত", "["]):
        return "সংশোধিত (Amended)", "সংশোধনীর মাধ্যমে কতিপয় বিধান পরিমার্জিত"
    return "সক্রিয় (Active)", "মূল বিধিমালার অধীনে অপরিবর্তিত"


def parse_lines_to_chunks(
    lines: list[str], domain: str, domain_bn: str, act_name: str
) -> list[dict]:
    """পরিষ্কার লাইনগুলো থেকে প্রতিটি ধারা ও তার সম্পূর্ণ কন্টেন্ট আলাদা করে চাঙ্ক তৈরি করে।"""
    chunks = []
    current_chapter = "সাধারণ অধ্যায়"
    current_sec = None
    current_title = ""
    current_body = []

    def save_current_section():
        if not current_sec or not current_body:
            return
        full_text = " ".join(current_body).strip()
        status, provenance = detect_status(full_text)
        chunks.append(
            {
                "id": f"{domain}_sec_{current_sec}",
                "domain": domain,
                "domain_bn": domain_bn,
                "act_name": act_name,
                "chapter": current_chapter,
                "section_number": current_sec,
                "section_title": current_title or f"ধারা {current_sec}",
                "content": f"আইন: {act_name} | অধ্যায়: {current_chapter} | ধারা {current_sec} ({current_title}): {full_text}",
                "legal_status": status,
                "amendment_provenance": provenance,
            }
        )

    for idx, line in enumerate(lines):
        # ফুটনোট বা রেফারেন্স অংশ শুরু হলে মূল ধারা পার্সিং থামানো
        if line.startswith("১ [") or line.startswith("1 [") or "সংশোধনীসমূহ" in line and idx > len(lines) * 0.7:
            break

        if "অধ্যায়" in line or "অধ্যায়" in line:
            if len(line) < 100:
                current_chapter = line
                continue

        # ব্র্যাকেটের ভেতর থাকা ধারা নম্বরও ধরা (যেমন: [৪ক। ...])
        cleaned_line = line.lstrip("[")
        match = SECTION_RE.match(cleaned_line)

        # উপধারা যেমন (১), (২) যেন নতুন ধারা হিসেবে না ধরে তা নিশ্চিত করা
        if match and not line.startswith("("):
            sec_no = match.group(1)
            rest_text = match.group(2).strip()

            # পূর্বের ধারা সেভ করা
            save_current_section()

            current_sec = sec_no
            # আগের লাইনটি যদি ছোট শিরোনাম হয় (যেমন: "সংজ্ঞা", "দণ্ড") তবে সেটি টাইটেল হিসেবে নেওয়া
            prev_line = lines[idx - 1] if idx > 0 else ""
            if prev_line and len(prev_line) < 90 and not SECTION_RE.match(prev_line.lstrip("[")) and "অধ্যায়" not in prev_line and "অধ্যায়" not in prev_line:
                current_title = prev_line.strip("[]।. ")
            else:
                first_clause = re.split(r"[।—:-]", rest_text, maxsplit=1)[0].strip()
                current_title = first_clause[:100] if first_clause else f"ধারা {sec_no}"

            current_body = [line]
        else:
            if current_sec:
                current_body.append(line)

    save_current_section()
    return chunks


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    all_new_chunks = []

    for config in DOMAINS_CONFIG:
        domain = config["domain"]
        domain_bn = config["domain_bn"]

        act_url, act_title = find_exact_act_url(session, config)
        if not act_url:
            print(f"[!] '{domain_bn}' খুঁজে পাওয়া যায়নি।\n")
            continue

        html = fetch_page(session, act_url)
        lines = extract_clean_lines(html)

        # Raw টেক্সট ফাইল সেভ করা
        raw_path = RAW_DIR / f"{domain}_raw.txt"
        raw_path.write_text("\n".join(lines), encoding="utf-8")

        # চাঙ্ক তৈরি করা
        chunks = parse_lines_to_chunks(lines, domain, domain_bn, act_title)
        print(f"[✓] '{domain_bn}' ({act_title}) থেকে মোট {len(chunks)}টি ধারা এক্সট্রাক্ট হয়েছে!\n")

        # আলাদা ডোমেইন চাঙ্ক সেভ করা
        domain_json = PROCESSED_DIR / f"{domain}_chunks.json"
        with open(domain_json, "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)

        all_new_chunks.extend(chunks)

    # সব নতুন ডোমেইনের সম্মিলিত চাঙ্ক সেভ করা
    combined_json = PROCESSED_DIR / "new_domains_chunks.json"
    with open(combined_json, "w", encoding="utf-8") as f:
        json.dump(all_new_chunks, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print(f"✅ সর্বমোট সংগৃহীত নতুন ধারা: {len(all_new_chunks)}টি")
    print(f"📁 সেভ লোকেশন: {combined_json}")
    print("=" * 60)


if __name__ == "__main__":
    main()