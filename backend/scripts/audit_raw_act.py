"""
Bangladesh Labour Act, 2006 - Raw Data Structure Auditor
Author: Prarthona Biswas
Module: Data Quality Audit
"""

from pathlib import Path
import re

# পাথ কনফিগারেশন
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RAW_FILE = PROJECT_ROOT / "backend" / "data" / "raw" / "labour_act_raw.txt"
AUDIT_LOG_FILE = PROJECT_ROOT / "backend" / "data" / "raw" / "audit_report.txt"

# সংখ্যা রূপান্তর টেবিল
BN_TO_EN = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
EN_TO_BN = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")

# ধারা ও উপধারা প্যাটার্ন
SECTION_PATTERN = re.compile(r"^([১২৩৪৫৬৭৮৯০]+[ক-হ]?)\s*[\।৷:\.]\s*(.*)$")


def audit():
  lines = [
      line.strip()
      for line in RAW_FILE.read_text(encoding="utf-8").splitlines()
      if line.strip()
  ]

  found_sections = {}
  for idx, line in enumerate(lines):
    if line.startswith("(") or line.startswith("[***]"):
      continue

    # থার্ড ব্র্যাকেট থাকলেও ভেতরের ধারা ধরা (যেমন: [১৭। ...])
    cleaned_line = line.lstrip("[")
    match = SECTION_PATTERN.match(cleaned_line)
    if match:
      sec_no = match.group(1)
      if sec_no not in found_sections:
        found_sections[sec_no] = {
            "line_no": idx + 1,
            "preview": line[:80],
        }

  # মিসিং ধারা যাচাই
  found_nums = set()
  for s in found_sections:
    base = re.sub(r"[^\d]", "", s.translate(BN_TO_EN))
    if base.isdigit():
      found_nums.add(int(base))

  all_expected = set(range(1, 354))
  missing_nums = sorted(list(all_expected - found_nums))

  # রিপোর্ট ফাইল তৈরি
  with open(AUDIT_LOG_FILE, "w", encoding="utf-8") as rep:
    rep.write("=" * 60 + "\n")
    rep.write("বাংলাদেশ শ্রম আইন ২০০৬ - ডেটা অডিট রিপোর্ট\n")
    rep.write("=" * 60 + "\n\n")
    rep.write(f"মোট ভ্যালিড লাইন সংখ্যা: {len(lines)}\n")
    rep.write(f"শনাক্ত হওয়া ধারার সংখ্যা: {len(found_sections)}\n")
    rep.write(f"অনুপস্থিত ধারা সংখ্যা: {len(missing_nums)}\n\n")

    rep.write("--- অনুপস্থিত ধারাগুলোর তালিকা ---\n")
    rep.write(", ".join([str(n).translate(EN_TO_BN) for n in missing_nums]))
    rep.write("\n\n" + "=" * 60 + "\n")
    rep.write("অনুপস্থিত ধারাগুলো ফাইলে আসলে কীভাবে আছে (খোঁজের ফলাফল):\n")
    rep.write("=" * 60 + "\n")

    # মিসিং ধারার টেক্সট ফাইলে কীভাবে আছে তা লগ করা
    for m in missing_nums:
      bn_str = str(m).translate(EN_TO_BN)
      rep.write(f"\n[অনুসন্ধান: ধারা {bn_str}]\n")
      matched_lines = [
          (i + 1, l) for i, l in enumerate(lines) if bn_str in l[:20]
      ][:2]
      if matched_lines:
        for l_no, text in matched_lines:
          rep.write(f"  Line {l_no}: {text}\n")
      else:
        rep.write("  ফাইলে কোনো সরাসরি লাইন পাওয়া যায়নি (সম্ভবত বিলুপ্ত/বাতিল)\n")

  print(f"[+] অডিট রিপোর্ট সফলভাবে তৈরি হয়েছে: {AUDIT_LOG_FILE}")


if __name__ == "__main__":
  audit()