"""
BDLaws Scraper for Bangladesh Labour Act, 2006.
Author: Ani (Data Engineer)
Module: Data Pipeline Ingestion
"""

from pathlib import Path
import sys
from bs4 import BeautifulSoup
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RAW_DATA_DIR = PROJECT_ROOT / "backend" / "data" / "raw"
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = RAW_DATA_DIR / "labour_act_raw.txt"
ACT_URL = "https://bdlaws.minlaw.gov.bd/act-details-952.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "bn,en;q=0.9",
}


def decode_html_bytes(raw_bytes: bytes) -> str:
  """সার্ভার বাইটের আসল এনকোডিং শনাক্ত করে পরিষ্কার স্ট্রিং রিটার্ন করে।"""
  for enc in ["utf-16", "utf-16-le", "utf-8", "windows-1252"]:
    try:
      decoded = raw_bytes.decode(enc)
      if "<html" in decoded.lower() or "ধারা" in decoded or "আইন" in decoded:
        return decoded
    except (UnicodeDecodeError, LookupError):
      continue
  return raw_bytes.decode("utf-8", errors="ignore")


def fetch_and_clean_act():
  print(f"[*] সংযোগ স্থাপন করা হচ্ছে: {ACT_URL}")
  session = requests.Session()
  session.headers.update(HEADERS)

  try:
    response = session.get(ACT_URL, timeout=45, verify=False)
    if response.status_code != 200:
      print(f"[!] ব্যর্থ: HTTP Status {response.status_code}")
      sys.exit(1)

    print("[+] পেজ বাইট ডাউনলোড সম্পন্ন। ডিকোড করা হচ্ছে...")
    html_text = decode_html_bytes(response.content)

    soup = BeautifulSoup(html_text, "html.parser")

    # স্ক্রিপ্ট, সিএসএস ও নেভিগেশন মুছে ফেলা
    for tag in soup(
        ["script", "style", "nav", "footer", "header", "noscript", "aside"]
    ):
      tag.decompose()

    # মূল কন্টেন্ট এক্সট্রাক্ট করা
    lines = []
    for line in soup.get_text(separator="\n").splitlines():
      cleaned = line.strip().replace("\x00", "")
      if cleaned:
        lines.append(cleaned)

    cleaned_output = "\n".join(lines)

    # ভ্যালিডেশন: বাংলায় আইন সংক্রান্ত শব্দ পাওয়া গেছে কি না
    if "ধারা" not in cleaned_output and "আইন" not in cleaned_output:
      print("[!] সতর্কতা: বাংলায় কোনো ধারার টেক্সট পাওয়া যায়নি।")
      sys.exit(1)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
      f.write(cleaned_output)

    total_lines = len(lines)
    file_size_kb = OUTPUT_FILE.stat().st_size / 1024

    print("\n" + "=" * 50)
    print("✅ খাঁটি বাংলা টেক্সটে শ্রম আইন ২০০৬ সেভ হয়েছে!")
    print(f"📁 ফাইল: {OUTPUT_FILE}")
    print(f"📊 লাইন সংখ্যা: {total_lines}")
    print(f"💾 ফাইল সাইজ: {file_size_kb:.2f} KB")
    print("=" * 50)

  except Exception as e:
    print(f"[!] ত্রুটি: {e}")
    sys.exit(1)


if __name__ == "__main__":
  fetch_and_clean_act()