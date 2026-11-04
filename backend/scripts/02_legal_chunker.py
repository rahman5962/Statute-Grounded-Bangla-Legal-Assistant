"""
Statute-Grounded & Status-Aware Legal Chunker.
Bangladesh Labour Act, 2006 (with 2013, 2018, 2026 amendments).
Author: Prarthona Biswas (AI / Retrieval Engineer)
Module: Temporal Document Chunking & Metadata Enrichment
"""

import json
from pathlib import Path
import re

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RAW_FILE = PROJECT_ROOT / "backend" / "data" / "raw" / "labour_act_raw.txt"
PROCESSED_DIR = PROJECT_ROOT / "backend" / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_JSON = PROCESSED_DIR / "labour_act_chunks.json"

SECTION_PATTERN = re.compile(r"^([১২৩৪৫৬৭৮৯০]+[ক-হ]?)\s*[\।৷:\.]\s*(.*)$")
CHAPTER_PATTERN = re.compile(r"^.*(অধ্যায়|অধ্যায়).*$")
FOOTNOTE_SECTION_RE = re.compile(r"^ধারা\s*([১২৩৪৫৬৭৮৯০]+[ক-হ]?)$")


def determine_legal_status(section_no: str, text: str, footnotes: list) -> tuple:
  clean_text = text.strip()

  is_pure_repealed_body = clean_text in [
      "[বিলুপ্ত]",
      "বিলুপ্ত",
      "[***]",
  ] or (len(clean_text) < 40 and "বিলুপ্ত" in clean_text)
  has_repealed_footnote = any(
      f"ধারা {section_no} বিলুপ্ত" in fn
      or f"ধারা {section_no} এর বিধানাবলী বিলুপ্ত" in fn
      for fn in footnotes
  )

  if is_pure_repealed_body or has_repealed_footnote:
    provenance = next(
        (fn for fn in footnotes if "বিলুপ্ত" in fn),
        "আইন সংশোধনীর মাধ্যমে ধারাটি বিলুপ্ত করা হয়েছে",
    )
    return "বিলুপ্ত (Repealed)", provenance

  has_amendment_markers = (
      "[" in clean_text
      or "[***]" in clean_text
      or any(
          k in " ".join(footnotes)
          for k in ["প্রতিস্থাপিত", "সন্নিবেশিত", "সংশোধিত", "বিলুপ্ত"]
      )
  )

  if has_amendment_markers:
    provenance = next(
        (
            fn
            for fn in footnotes
            if any(k in fn for k in ["প্রতিস্থাপিত", "সন্নিবেশিত", "ধারাবলে"])
        ),
        (
            next((fn for fn in footnotes if "বিলুপ্ত" in fn), None)
            or "সংশোধনীর মাধ্যমে কতিপয় বিধান পরিবর্তিত/পরিমার্জিত"
        ),
    )
    return "সংশোধিত (Amended)", provenance

  return "সক্রিয় (Active)", "২০০৬ সনের মূল বিধিমালার অধীনে অপরিবর্তিত"


def extract_repealed_from_footnotes(footnote_lines: list, existing_chunks: list):
  existing_sec_nums = {c["section_number"] for c in existing_chunks}
  added_repealed = []

  # ১. ফুটনোট থেকে সরাসরি শনাক্তকৃত ধারা (যেমন ১৮৪)
  for idx, line in enumerate(footnote_lines):
    match = FOOTNOTE_SECTION_RE.match(line.strip())
    if match:
      sec_no = match.group(1)
      if sec_no not in existing_sec_nums:
        context_window = footnote_lines[idx : idx + 4]
        combined_text = " ".join(context_window)
        if "বিলুপ্ত" in combined_text:
          ref_note = " ".join(context_window[1:]).strip()
          record = {
              "id": f"sec_{sec_no}",
              "act_name": "বাংলাদেশ শ্রম আইন, ২০০৬",
              "chapter": "অপ্রযোজ্য (বিলুপ্ত ধারা)",
              "section_number": sec_no,
              "section_title": "ধারাটি আইনত বিলুপ্ত",
              "legal_status": "বিলুপ্ত (Repealed)",
              "amendment_provenance": ref_note,
              "content": (
                  f"আইন: বাংলাদেশ শ্রম আইন, ২০০৬\n"
                  f"অধ্যায়: অপ্রযোজ্য (বিলুপ্ত ধারা)\n"
                  f"ধারা: {sec_no} | শিরোনাম: ধারাটি আইনত বিলুপ্ত\n"
                  f"বর্তমান আইনি অবস্থা: বিলুপ্ত (Repealed)\n"
                  f"সংশোধনী/ঐতিহাসিক রেফারেন্স: {ref_note}\n"
                  f"আইনি বিবরণ:\nএই ধারাটি আইন সংশোধনীর মাধ্যমে বিলুপ্ত ঘোষণা করা হয়েছে। বর্তমান আইনে এর কোনো কার্যকারিতা নেই।"
              ),
              "raw_body": "ধারাটি আইন সংশোধনীর মাধ্যমে বিলুপ্ত ঘোষণা করা হয়েছে।",
          }
          added_repealed.append(record)
          existing_sec_nums.add(sec_no)

  # ২. পঞ্চদশ অধ্যায়ের বিলুপ্ত ধারা ২৫৩ হইতে ২৬২
  bangla_digits = "০১২৩৪৫৬৭৮৯"
  to_bangla = lambda n: "".join(bangla_digits[int(d)] for d in str(n))
  dock_repeal_ref = (
      "বাংলাদেশ শ্রম (সংশোধন) আইন, ২০১৩ দ্বারা পঞ্চদশ অধ্যায় (ধারা ২৫৩-২৬২) বিলুপ্ত এবং ধারা ২৬৩ক দ্বারা প্রতিস্থাপিত বিধান।"
  )

  for n in range(253, 263):
    bn_sec = to_bangla(n)
    if bn_sec not in existing_sec_nums:
      record = {
          "id": f"sec_{bn_sec}",
          "act_name": "বাংলাদেশ শ্রম আইন, ২০০৬",
          "chapter": "পঞ্চদশ অধ্যায় (বিলুপ্ত)",
          "section_number": bn_sec,
          "section_title": "ডক-শ্রমিক ব্যবস্থাপনা বোর্ড সংক্রান্ত (ধারাটি বিলুপ্ত)",
          "legal_status": "বিলুপ্ত (Repealed)",
          "amendment_provenance": dock_repeal_ref,
          "content": (
              f"আইন: বাংলাদেশ শ্রম আইন, ২০০৬\n"
              f"অধ্যায়: পঞ্চদশ অধ্যায় (বিলুপ্ত)\n"
              f"ধারা: {bn_sec} | শিরোনাম: ডক-শ্রমিক ব্যবস্থাপনা বোর্ড সংক্রান্ত (ধারাটি বিলুপ্ত)\n"
              f"বর্তমান আইনি অবস্থা: বিলুপ্ত (Repealed)\n"
              f"সংশোধনী/ঐতিহাসিক রেফারেন্স: {dock_repeal_ref}\n"
              f"আইনি বিবরণ:\nডক-শ্রমিক ব্যবস্থাপনা বোর্ড সংক্রান্ত এই ধারাটি বাংলাদেশ শ্রম (সংশোধন) আইন, ২০১৩ দ্বারা সম্পূর্ণ বিলুপ্ত ঘোষণা করা হয়েছে। বর্তমানে এই সংক্রান্ত কার্যক্রম ধারা ২৬৩ক অনুযায়ী পরিচালিত হয়।"
          ),
          "raw_body": "ডক-শ্রমিক ব্যবস্থাপনা বোর্ড সংক্রান্ত এই ধারাটি বাংলাদেশ শ্রম (সংশোধন) আইন, ২০১৩ দ্বারা সম্পূর্ণ বিলুপ্ত।",
      }
      added_repealed.append(record)
      existing_sec_nums.add(bn_sec)

  return added_repealed


def run_legal_chunking():
  print(f"[*] ডেটাসেট বিশ্লেষণ শুরু হচ্ছে: {RAW_FILE}")
  raw_text = RAW_FILE.read_text(encoding="utf-8")
  all_lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

  body_lines = []
  footnote_lines = []
  is_footnote_zone = False

  for idx, line in enumerate(all_lines):
    if idx > 3100 and ("ধারাবলে" in line or ("সনের" in line and "আইন" in line)):
      is_footnote_zone = True

    if is_footnote_zone:
      footnote_lines.append(line)
    else:
      body_lines.append(line)

  print(f"[*] মূল টেক্সট লাইন: {len(body_lines)}, সংশোধনীর রেফারেন্স লাইন: {len(footnote_lines)}")

  chunks = []
  current_chapter = "সাধারণ প্রস্তাবনা"
  current_section_no = None
  current_title = ""
  current_body_lines = []

  def flush_chunk():
    if current_section_no and current_body_lines:
      body_text = "\n".join(current_body_lines).strip()

      relevant_notes = [
          fn
          for fn in footnote_lines
          if f"ধারা {current_section_no}" in fn
          or ("দফা" in fn and current_section_no in fn)
      ]

      status, provenance = determine_legal_status(current_section_no, body_text, relevant_notes)

      enriched_content = (
          f"আইন: বাংলাদেশ শ্রম আইন, ২০০৬\n"
          f"অধ্যায়: {current_chapter}\n"
          f"ধারা: {current_section_no} | শিরোনাম: {current_title}\n"
          f"বর্তমান আইনি অবস্থা: {status}\n"
          f"সংশোধনী/ঐতিহাসিক রেফারেন্স: {provenance}\n"
          f"আইনি বিবরণ:\n{body_text}"
      )

      record = {
          "id": f"sec_{current_section_no}",
          "act_name": "বাংলাদেশ শ্রম আইন, ২০০৬",
          "chapter": current_chapter,
          "section_number": current_section_no,
          "section_title": current_title,
          "legal_status": status,
          "amendment_provenance": provenance,
          "content": enriched_content,
          "raw_body": body_text,
      }
      chunks.append(record)

  for i, line in enumerate(body_lines):
    if CHAPTER_PATTERN.match(line) and len(line) < 35 and not line.startswith("("):
      next_l = (
          body_lines[i + 1]
          if (i + 1 < len(body_lines) and not SECTION_PATTERN.match(body_lines[i + 1]))
          else ""
      )
      current_chapter = f"{line} ({next_l})" if next_l else line
      continue

    if (line.startswith("(") or line.startswith("[***]")) and not re.match(r"^\[\s*[১২৩৪৫৬৭৮৯০]", line):
      if current_section_no is not None:
        current_body_lines.append(line)
      continue

    cleaned = line.lstrip("[\t ")
    match = SECTION_PATTERN.match(cleaned)

    if match:
      flush_chunk()
      current_section_no = match.group(1)

      prev_line = body_lines[i - 1] if i > 0 else ""
      if (
          prev_line
          and not CHAPTER_PATTERN.match(prev_line)
          and not SECTION_PATTERN.match(prev_line.lstrip("[\t "))
          and len(prev_line) < 120
      ):
        current_title = prev_line
      else:
        current_title = "শিরোনাম প্রযোজ্য নয়"

      current_body_lines = [line]
    else:
      if current_section_no is not None:
        current_body_lines.append(line)

  flush_chunk()

  repealed_chunks = extract_repealed_from_footnotes(footnote_lines, chunks)
  chunks.extend(repealed_chunks)

  with open(OUTPUT_JSON, "w", encoding="utf-8") as out:
    json.dump(chunks, out, ensure_ascii=False, indent=2)

  print("\n" + "=" * 60)
  print("✅ লিগ্যাল চাংকিং ও হিস্ট্রি ট্র্যাকিং সফলভাবে সম্পন্ন!")
  print(f"📁 আউটপুট ফাইল: {OUTPUT_JSON}")
  print(f"🎯 মোট সংরক্ষিত ধারা (Total Chunks): {len(chunks)}")

  status_counts = {}
  for c in chunks:
    s = c["legal_status"]
    status_counts[s] = status_counts.get(s, 0) + 1

  print("\n📈 সংশোধিত আইনি অবস্থার চূড়ান্ত বিভাজন:")
  for s, cnt in status_counts.items():
    print(f"  - {s}: {cnt} টি ধারা")
  print("=" * 60)


if __name__ == "__main__":
  run_legal_chunking()