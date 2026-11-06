"""
Statute-Grounded Bangla Legal Assistant - Full Application Interface.
Module: Streamlit Web UI, Precision Hybrid Search & Audit Logging
Author: Ani (241-35-279)
"""
import sys
from pathlib import Path
import re
import streamlit as st
import importlib
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR / "backend"))

from auth import register_user, authenticate_user
from database import get_db_connection

vector_module = importlib.import_module("scripts.03_vector_store")
get_vector_collection = vector_module.get_vector_collection

st.set_page_config(
    page_title="Statute-Grounded Bangla Legal Assistant",
    page_icon="⚖️",
    layout="wide"
)

def log_query_to_db(user_id, query_text, sections, answer, status):
    """Database audit logging"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO query_logs (user_id, query_text, retrieved_sections, generated_answer, evidence_status)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, query_text, sections, answer, status))
    conn.commit()
    conn.close()

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None

st.title("⚖️ Statute-Grounded Bangla Legal Assistant")
st.caption("বাংলাদেশ শ্রম আইন, ২০০৬ (সংশোধনীসহ) এর ওপর ভিত্তি করে স্ট্যাটাস-অ্যাওয়ার আইনি সহায়তা")

# --- সাইডবার অথেনটিকেশন ---
st.sidebar.header("🔐 ইউজার অথেনটিকেশন")

if not st.session_state.logged_in:
    auth_mode = st.sidebar.radio("অ্যাকশন:", ["লগইন", "রেজিস্ট্রেশন"])
    if auth_mode == "লগইন":
        with st.sidebar.form("login_form"):
            email = st.text_input("ইমেইল:")
            password = st.text_input("পাসওয়ার্ড:", type="password")
            submit = st.form_submit_button("লগইন")
            if submit:
                res = authenticate_user(email, password)
                if res["status"] == "success":
                    st.session_state.logged_in = True
                    st.session_state.user = res["user"]
                    st.sidebar.success(f"স্বাগতম, {res['user']['full_name']}!")
                    st.rerun()
                else:
                    st.sidebar.error(res["message"])
    else:
        with st.sidebar.form("register_form"):
            name = st.text_input("পুরো নাম:")
            reg_email = st.text_input("ইমেইল:")
            reg_password = st.text_input("পাসওয়ার্ড (কমপক্ষে ৬ অক্ষর):", type="password")
            reg_submit = st.form_submit_button("রেজিস্ট্রেশন")
            if reg_submit:
                res = register_user(name, reg_email, reg_password)
                if res["status"] == "success":
                    st.sidebar.success(res["message"])
                else:
                    st.sidebar.error(res["message"])
else:
    st.sidebar.success(f"👤 **{st.session_state.user['full_name']}**")
    st.sidebar.info(f"📧 {st.session_state.user['email']}")
    if st.sidebar.button("লগআউট"):
        st.session_state.logged_in = False
        st.session_state.user = None
        st.rerun()

# --- মূল ইন্টারফেস ---
if not st.session_state.logged_in:
    st.warning("⚠️ অনুগ্রহ করে বাম পাশের সাইডবার থেকে লগইন করুন।")
else:
    tab1, tab2 = st.tabs(["🔍 আইনি অনুসন্ধান (Legal Assistant)", "📊 ডেটাবেজ হিস্ট্রি (Audit Trail)"])

    with tab1:
        query = st.text_input(
            "আপনার আইনি প্রশ্নটি বাংলায় লিখুন (অথবা নির্দিষ্ট ধারা খুঁজুন):",
            placeholder="যেমন: শ্রমিকের দৈনিক কাজের সময় কত? অথবা ধারা ১৮৪"
        )

        if st.button("আইনি অনুসন্ধান চালান") and query.strip():
            with st.spinner("যাচাই ও অনুসন্ধান করা হচ্ছে..."):
                col = get_vector_collection()
                
                eng_to_ben = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
                
                # ১. ধারা নম্বর কুয়েরি চেক (e.g. ধারা ৯৯৯, ধারা ১০০)
                sec_match = re.search(r'(?:ধারা|সেকশন)\s*([০-৯0-9]+)', query)
                exact_sec_num = None
                if sec_match:
                    exact_sec_num = sec_match.group(1).translate(eng_to_ben)
                elif query.strip().isdigit():
                    exact_sec_num = query.strip().translate(eng_to_ben)

                meta_match = None
                invalid_section_requested = False

                if exact_sec_num:
                    exact_res = col.get(where={"section_number": exact_sec_num})
                    if exact_res and exact_res["ids"]:
                        meta_match = {
                            "id": exact_res["ids"][0],
                            "doc": exact_res["documents"][0],
                            "meta": exact_res["metadatas"][0]
                        }
                    else:
                        # অস্তিত্বহীন ধারা চাওয়া হয়েছে
                        invalid_section_requested = True

                # ২. প্রায়োরিটি ভিত্তিক লিগ্যাল কি-ওয়ার্ড ম্যাপিং
                # লম্বা ও সুনির্দিষ্ট কি-ওয়ার্ড আগে চেক হবে
                keyword_map = [
                    (r"মাতৃত্ব|প্রসূতি|গর্ভবতী", "৪৬"),
                    (r"বরখাস্ত|অব্যাহতি|চাকরি\s*চ্যুতি|চাকরি\s*থেকে\s*বাদ", "২৩"),
                    (r"দৈনিক|কর্মঘণ্টা|কাজের\s*সময়|কাজের\s*সময়কাল", "১০০"),
                    (r"সাপ্তাহিক|সপ্তাহে\s*কাজের|সপ্তাহের\s*ছুটি", "১০২"),
                    (r"ওভারটাইম|অতিরিক্ত\s*কাজ|অধিকাল", "১০৮"),
                    (r"মজুরি\s*পরিশোধ|বেতন", "১২১"),
                    (r"বাৎসরিক\s*ছুটি|অর্জিত\s*ছুটি", "১১৭"),
                    (r"নৈমিত্তিক\s*ছুটি", "১১৫"),
                    (r"পীড়া\s*ছুটি|অসুস্থতার\s*ছুটি", "১১৬")
                ]

                hybrid_target_sec = None
                if not meta_match and not invalid_section_requested:
                    for pattern, sec_target in keyword_map:
                        if re.search(pattern, query):
                            hybrid_target_sec = sec_target
                            break

                if hybrid_target_sec and not meta_match:
                    kw_res = col.get(where={"section_number": hybrid_target_sec})
                    if kw_res and kw_res["ids"]:
                        meta_match = {
                            "id": kw_res["ids"][0],
                            "doc": kw_res["documents"][0],
                            "meta": kw_res["metadatas"][0]
                        }

                # ৩. অস্তিত্বহীন ধারা হ্যান্ডলিং
                if invalid_section_requested:
                    st.error(f"❌ **ত্রুটি:** বাংলাদেশ শ্রম আইন, ২০০৬-এ **ধারা {exact_sec_num}** নামে কোনো ধারা বিদ্যমান নেই। (সর্বোচ্চ ধারা সংখ্যা: ৩৫৩)")
                    log_query_to_db(
                        user_id=st.session_state.user["id"],
                        query_text=query,
                        sections="নেই (Invalid Section)",
                        answer="অস্তিত্বহীন ধারার জন্য প্রত্যাখ্যান করা হয়েছে।",
                        status="প্রত্যাখ্যাত (Rejected)"
                    )
                else:
                    st.markdown("### 📋 আইনি রেফারেন্স ও ধারা:")
                    retrieved_sec_names = []
                    
                    # সুনির্দিষ্ট বিধান প্রদর্শন
                    if meta_match:
                        meta = meta_match["meta"]
                        doc = meta_match["doc"]
                        retrieved_sec_names.append(f"ধারা {meta['section_number']}")
                        
                        st.success(f"🎯 **প্রধান প্রাসঙ্গিক ধারা:** ধারা {meta['section_number']} - {meta['section_title']}")
                        st.write(f"**বর্তমান আইনি অবস্থা:** `{meta['legal_status']}`")
                        
                        clean_text = doc.split("আইনি বিবরণ:")[-1].strip() if "আইনি বিবরণ:" in doc else doc
                        st.info(f"📜 **আইনি বিধান (পূর্ণাঙ্গ পাঠ):**\n\n{clean_text}")
                        
                        if meta.get("amendment_provenance"):
                            st.caption(f"📌 **সংশোধনী রেফারেন্স:** {meta['amendment_provenance']}")
                        st.divider()

                    # ভেক্টর সার্চ
                    vector_results = col.query(query_texts=[query], n_results=4)
                    
                    valid_semantic_found = False
                    for i in range(len(vector_results["ids"][0])):
                        meta = vector_results["metadatas"][0][i]
                        doc = vector_results["documents"][0][i]
                        dist = vector_results["distances"][0][i]
                        score = round(1 - dist, 3)

                        # Threshold filtering: Score 0.60 এর নিচে হলে অপ্রাসঙ্গিক ধরে বাদ দেওয়া
                        if score < 0.60:
                            continue

                        if meta_match and meta["section_number"] == meta_match["meta"]["section_number"]:
                            continue

                        valid_semantic_found = True
                        retrieved_sec_names.append(f"ধারা {meta['section_number']}")
                        with st.expander(f"ধারা {meta['section_number']} - {meta['section_title']} (রিট্রিভাল কনফিডেন্স: {score})"):
                            st.write(f"**আইনি অবস্থা:** `{meta['legal_status']}`")
                            clean_doc = doc.split("আইনি বিবরণ:")[-1].strip() if "আইনি বিবরণ:" in doc else doc
                            st.write(clean_doc)
                            if meta.get("amendment_provenance"):
                                st.caption(f"রেফারেন্স: {meta['amendment_provenance']}")

                    if not meta_match and not valid_semantic_found:
                        st.warning("⚠️ আপনার প্রশ্নের সাথে সুনির্দিষ্ট কোনো আইনি বিধানের মিল পাওয়া যায়নি। অনুগ্রহ করে প্রমিত বাংলা শব্দে প্রশ্নটি লিখুন।")
                        status_str = "অপ্রতুল মিল (Low Confidence)"
                    else:
                        status_str = "সমর্থিত (Supported)"

                    # ডেটাবেজে লগ সংরক্ষণ
                    ans_log = f"রিট্রিভড ধারা: {', '.join(retrieved_sec_names) if retrieved_sec_names else 'কোনোটিই নয়'}"
                    log_query_to_db(
                        user_id=st.session_state.user["id"],
                        query_text=query,
                        sections=", ".join(retrieved_sec_names) if retrieved_sec_names else "নেই",
                        answer=ans_log,
                        status=status_str
                    )
                    st.toast("✅ অনুসন্ধানটি সফলভাবে ডেটাবেজে সংরক্ষিত হয়েছে।")

    # --- ২. ডেটাবেজ অডিট ভিউয়ার ট্যাব ---
    with tab2:
        st.subheader("📊 আপনার অ্যাকাউন্টের অডিট হিস্ট্রি (SQLite Database)")
        conn = get_db_connection()
        logs = conn.execute(
            """SELECT id, query_text, retrieved_sections, evidence_status, created_at 
               FROM query_logs 
               WHERE user_id = ? 
               ORDER BY id DESC LIMIT 15""",
            (st.session_state.user["id"],)
        ).fetchall()
        conn.close()

        if logs:
            df = pd.DataFrame([dict(log) for log in logs])
            df.columns = ["লগ আইডি", "আইনি প্রশ্ন", "রিট্রিভড ধারা", "স্ট্যাটাস", "অনুসন্ধানের সময়কাল"]
            st.dataframe(df, use_container_width=True)
        else:
            st.info("এখনো কোনো অনুসন্ধানের ইতিহাস তৈরি হয়নি।")