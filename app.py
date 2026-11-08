import os
import re
import sys
from pathlib import Path
import pandas as pd
import streamlit as st

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))
from auth import (
    authenticate_user,
    init_auth_db,
    register_user,
    validate_email,
    validate_password,
)
from database import get_audit_trail, log_audit_trail

st.set_page_config(
    page_title="Statute-Grounded Bangla Legal Assistant",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom High-End Legal Tech CSS
st.markdown(
    """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Hind+Siliguri:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] {
        font-family: 'Hind Siliguri', sans-serif;
    }
    .main-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        padding: 24px 30px;
        border-radius: 14px;
        color: white;
        margin-bottom: 25px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        border: 1px solid #334155;
    }
    .metric-box {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
        box-shadow: 0 2px 6px rgba(0,0,0,0.03);
    }
    .metric-value {
        font-size: 24px;
        font-weight: 700;
        color: #0f172a;
    }
    .metric-label {
        font-size: 13px;
        color: #64748b;
        font-weight: 500;
    }
    .statute-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 22px;
        margin-bottom: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        border-left: 6px solid #2563eb;
    }
    .statute-card.repealed {
        border-left: 6px solid #ef4444;
        background: #fef2f2;
    }
    .statute-card.amended {
        border-left: 6px solid #f59e0b;
        background: #fffbeb;
    }
    .badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 600;
        margin-right: 8px;
    }
    .badge-active { background: #dcfce7; color: #166534; }
    .badge-repealed { background: #fee2e2; color: #991b1b; }
    .badge-amended { background: #fef3c7; color: #92400e; }
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
    }
</style>
""",
    unsafe_allow_html=True,
)

# Initialize Databases
init_auth_db()

if "authenticated" not in st.session_state:
  st.session_state["authenticated"] = False
if "user" not in st.session_state:
  st.session_state["user"] = None
if "quick_query" not in st.session_state:
  st.session_state["quick_query"] = ""


# Vector Store Loading with caching
@st.cache_resource(show_spinner="লোকাল ভেক্টর ডাটাবেজ প্রস্তুত হচ্ছে...")
def load_vector_db():
  try:
    import importlib

    mod = importlib.import_module("scripts.03_vector_store")
    return mod.get_vector_collection()
  except Exception as e:
    st.error(f"Vector DB লোড হতে সমস্যা হয়েছে: {str(e)}")
    return None


collection = load_vector_db()

# SIDEBAR: Authentication & System Info
with st.sidebar:
  st.image("https://img.icons8.com/color/96/scales.png", width=64)
  st.markdown("### আইনি সহায়তা সিস্টেম")
  st.caption("বাংলাদেশ শ্রম আইন, ২০০৬ (সর্বশেষ সংশোধিত)")
  st.markdown("---")

  if not st.session_state["authenticated"]:
    auth_mode = st.radio(
        "প্রবেশ করুন / একাউন্ট খুলুন", ["লগইন (Login)", "নিবন্ধন (Register)"]
    )

    if auth_mode == "লগইন (Login)":
      with st.form("login_form"):
        st.markdown("##### 🔑 লগইন")
        username = st.text_input("ইউজারনেম বা ইমেইল")
        password = st.text_input("পাসওয়ার্ড", type="password")
        submit = st.form_submit_button("লগইন", use_container_width=True)

        if submit:
          ok, res = authenticate_user(username, password)
          if ok:
            st.session_state["authenticated"] = True
            st.session_state["user"] = res
            st.success(f"স্বাগতম, {res['full_name']}!")
            st.rerun()
          else:
            st.error(res)
    else:
      with st.form("register_form"):
        st.markdown("##### 📝 নতুন একাউন্ট")
        r_username = st.text_input("ইউজারনেম")
        r_name = st.text_input("পুরো নাম")
        r_email = st.text_input("ইমেইল")
        r_password = st.text_input(
            "পাসওয়ার্ড (কমপক্ষে ৮ অক্ষর)", type="password"
        )
        r_submit = st.form_submit_button(
            "নিবন্ধন সম্পন্ন করুন", use_container_width=True
        )

        if r_submit:
          ok, msg = register_user(r_username, r_name, r_email, r_password)
          if ok:
            st.success("নিবন্ধন সফল হয়েছে! অনুগ্রহ করে লগইন করুন।")
          else:
            st.error(msg)
  else:
    st.markdown(f"**স্বাগতম,** `{st.session_state['user']['full_name']}`")
    st.caption(f"ইউজারনেম: {st.session_state['user']['username']}")
    st.caption(f"রোল: {st.session_state['user']['role'].upper()}")

    if st.button("🚪 লগআউট", use_container_width=True):
      st.session_state["authenticated"] = False
      st.session_state["user"] = None
      st.rerun()

  st.markdown("---")
  st.markdown("**প্রজেক্ট টিম:**")
  st.markdown("- **Ashikur Rahman Sazim** (Backend & Auth)")
  st.markdown("- **Prarthona Biswas Puja** (Vector DB & Chunking)")
  st.markdown("- **Ani** (UI/UX & Hybrid RAG)")

# MAIN CONTENT
st.markdown(
    """
<div class='main-header'>
    <h2 style='margin:0; font-size:26px;'>⚖️ Statute-Grounded Bangla Legal Assistant</h2>
    <p style='margin:5px 0 0 0; opacity:0.85; font-size:14px;'>বাংলাদেশ শ্রম আইন, ২০০৬-এর নির্ভুল ধারাকেন্দ্রিক আইনি অনুসন্ধান ও অডিট সিস্টেম</p>
</div>
""",
    unsafe_allow_html=True,
)

# System Metric Cards
c1, c2, c3, c4 = st.columns(4)
with c1:
  st.markdown(
      "<div class='metric-box'><div class='metric-value'>৩৭৫টি</div><div"
      " class='metric-label'>মোট সংকলিত ধারা</div></div>",
      unsafe_allow_html=True,
  )
with c2:
  st.markdown(
      "<div class='metric-box'><div class='metric-value'>১০০%</div><div"
      " class='metric-label'>স্ট্যাটিউট গ্রাউন্ডেড</div></div>",
      unsafe_allow_html=True,
  )
with c3:
  st.markdown(
      "<div class='metric-box'><div class='metric-value'>সংশোধিত"
      " ২০২৬</div><div class='metric-label'>লিগ্যাল স্ট্যাটাস"
      " ট্র্যাকিং</div></div>",
      unsafe_allow_html=True,
  )
with c4:
  st.markdown(
      "<div class='metric-box'><div class='metric-value'>SQLite Audit</div><div"
      " class='metric-label'>ফুল অডিট লগিং</div></div>",
      unsafe_allow_html=True,
  )

st.markdown("<br>", unsafe_allow_html=True)

# Guard: Check authentication
if not st.session_state["authenticated"]:
  st.info(
      "💡 সিস্টেমের অনুসন্ধান সুবিধা ও অডিট ট্রেইল দেখতে অনুগ্রহ করে বামপাশের"
      " সাইডবার থেকে লগইন করুন।"
  )
  st.stop()

# TABS
tab_search, tab_audit = st.tabs([
    "🔍 আইনি ধারা অনুসন্ধান (Hybrid RAG)",
    "📊 ডেটাবেজ হিস্ট্রি (Audit Trail)",
])

with tab_search:
  st.markdown("##### দ্রুত অনুসন্ধান বাটন (Quick Suggestion Chips): ")
  chip_cols = st.columns(5)
  if chip_cols[0].button("🤰 মাতৃত্বকালীন ছুটি", use_container_width=True):
    st.session_state["quick_query"] = "মাতৃত্বকালীন সুবিধা ও ছুটির বিধান কি?"
  if chip_cols[1].button("⏱️ ওভারটাইম ভাতা", use_container_width=True):
    st.session_state["quick_query"] = (
        "অতিরিক্ত কাজের জন্য ওভারটাইম মজুরি কত হবে?"
    )
  if chip_cols[2].button("🚫 ধারা ১৮৪ (বিলুপ্ত)", use_container_width=True):
    st.session_state["quick_query"] = "ধারা ১৮৪"
  if chip_cols[3].button("⚠️ ধারা ৯৯৯ (অস্তিত্বহীন)", use_container_width=True):
    st.session_state["quick_query"] = "ধারা ৯৯৯ অনুযায়ী শাস্তি"
  if chip_cols[4].button("📄 বরখাস্তের নিয়ম", use_container_width=True):
    st.session_state["quick_query"] = "মালিক কর্তৃক শ্রমিক বরখাস্তের নিয়ম কি?"

  query_input = st.text_input(
      "আপনার আইনি প্রশ্ন বা নির্দিষ্ট ধারা লিখুন:",
      value=st.session_state["quick_query"],
      placeholder="যেমন: মাতৃত্বকালীন ছুটির সময়সীমা কত? বা ধারা ১০০",
  )

  col_search, col_clear = st.columns([6, 1])
  search_clicked = col_search.button(
      "🔍 আইনি ধারা খুঁজুন", type="primary", use_container_width=True
  )
  if col_clear.button("ক্লিয়ার", use_container_width=True):
    st.session_state["quick_query"] = ""
    st.rerun()

  if (search_clicked or query_input) and query_input.strip():
    q = query_input.strip()

    # Guardrail: Check for out-of-range statutes
    sec_num_match = re.search(r"ধারা\s*([০-৯0-9]+)", q)
    if sec_num_match:
      raw_n = sec_num_match.group(1)
      bengali_digits = {
          "০": "0",
          "১": "1",
          "২": "2",
          "৩": "3",
          "৪": "4",
          "৫": "5",
          "৬": "6",
          "৭": "7",
          "৮": "8",
          "৯": "9",
      }
      norm_n = int("".join(bengali_digits.get(ch, ch) for ch in raw_n))
      if norm_n > 353:
        st.error(
            f"🚨 **আইনি সতর্কতা:** বাংলাদেশ শ্রম আইন, ২০০৬-এ **ধারা {raw_n}** নামে"
            " কোনো ধারার অস্তিত্ব নেই। সর্বোচ্চ ধারা সংখ্যা ৩৫৩। সিস্টেম কোনো"
            " ভুল তথ্য প্রদান করবে না।"
        )
        log_audit_trail(
            st.session_state["user"]["user_id"],
            q,
            f"ধারা {raw_n} [Not Found]",
            "Rejected",
        )
        st.stop()

    if collection is not None:
      with st.spinner("হাইব্রিড সার্চ ও গ্রাউন্ডেড ডাটা রিট্রিভ হচ্ছে..."):
        results = collection.query(
            query_texts=[q],
            n_results=3,
            include=["documents", "metadatas", "distances"],
        )

      if results and results["documents"] and len(results["documents"][0]) > 0:
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]

        best_distance = distances[0]
        confidence_score = round(max(0.0, 1.0 - (best_distance / 2.0)), 2)

        if confidence_score < 0.25:
          st.warning(
              "⚠️ আপনার অনুসন্ধানের সাথে সুনির্দিষ্ট কোনো ধারার সরাসরি মিল পাওয়া"
              " যায়নি। অনুগ্রহ করে সুনির্দিষ্ট আইনি শব্দ ব্যবহার করুন।"
          )
        else:
          st.success(
              "✅ অনুসন্ধানের ফলাফল পাওয়া গেছে (কনফিডেন্স স্কোর:"
              f" {confidence_score * 100:.0f}%)"
          )

          for i, (doc, meta) in enumerate(zip(docs, metas)):
            sec_num = meta.get("section_number", "N/A")
            sec_title = meta.get("section_title", "আই