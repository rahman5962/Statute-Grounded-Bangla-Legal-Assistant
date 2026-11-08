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
    register_user,
    validate_user_input,
)
from database import init_db, get_audit_trail, log_audit_trail

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
        box-shadow: 0 4px 20px rgba(0,0,0,0.25);
        border: 1px solid #334155;
    }
    .metric-box {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    }
    .metric-value {
        font-size: 24px;
        font-weight: 700;
        color: #38bdf8;
    }
    .metric-label {
        font-size: 13px;
        color: #94a3b8;
        font-weight: 500;
    }
    .statute-card {
        background: #0f172a;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 22px;
        margin-bottom: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        border-left: 6px solid #38bdf8;
    }
    .statute-card.repealed {
        border-left: 6px solid #ef4444;
        background: #1a1016;
    }
    .statute-card.amended {
        border-left: 6px solid #f59e0b;
        background: #1f1a10;
    }
    .statute-body {
        background: #1e293b;
        padding: 16px;
        border-radius: 8px;
        line-height: 1.8;
        color: #f1f5f9;
        font-size: 15px;
        border: 1px solid #334155;
    }
    .badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 600;
        margin-right: 8px;
    }
    .badge-active { background: #064e3b; color: #6ee7b7; border: 1px solid #059669; }
    .badge-repealed { background: #7f1d1d; color: #fca5a5; border: 1px solid #dc2626; }
    .badge-amended { background: #78350f; color: #fde68a; border: 1px solid #d97706; }
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
    }
</style>
""",
    unsafe_allow_html=True,
)

# Initialize Relational Database
init_db()

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "user" not in st.session_state:
    st.session_state["user"] = None


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

# SIDEBAR: Authentication & Controls
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
                email_input = st.text_input("ইমেইল (Email)")
                password_input = st.text_input("পাসওয়ার্ড", type="password")
                submit = st.form_submit_button("লগইন", use_container_width=True)

                if submit:
                    res = authenticate_user(email_input, password_input)
                    if res.get("status") == "success":
                        st.session_state["authenticated"] = True
                        st.session_state["user"] = res.get("user")
                        st.success(f"স্বাগতম, {res.get('user', {}).get('full_name')}!")
                        st.rerun()
                    else:
                        st.error(res.get("message", "লগইন ব্যর্থ হয়েছে।"))
        else:
            with st.form("register_form"):
                st.markdown("##### 📝 নতুন একাউন্ট")
                r_name = st.text_input("পুরো নাম")
                r_email = st.text_input("ইমেইল")
                r_password = st.text_input(
                    "পাসওয়ার্ড (কমপক্ষে ৮ অক্ষর)", type="password"
                )
                r_role = st.selectbox("আপনার ভূমিকা (Role)", ["citizen", "lawyer", "student"])
                r_submit = st.form_submit_button(
                    "নিবন্ধন সম্পন্ন করুন", use_container_width=True
                )

                if r_submit:
                    val_err = validate_user_input(r_name, r_email, r_password)
                    if val_err:
                        st.error(val_err)
                    else:
                        res = register_user(r_name, r_email, r_password, r_role)
                        if res.get("status") == "success":
                            st.success("নিবন্ধন সফল হয়েছে! অনুগ্রহ করে লগইন ট্যাবে গিয়ে লগইন করুন।")
                        else:
                            st.error(res.get("message", "নিবন্ধন ব্যর্থ হয়েছে।"))
    else:
        st.markdown(f"**স্বাগতম,** `{st.session_state['user'].get('full_name')}`")
        st.caption(f"ইমেইল: {st.session_state['user'].get('email')}")
        st.caption(f"রোল: {str(st.session_state['user'].get('role', 'citizen')).upper()}")

        st.markdown("---")
        st.markdown("##### ⚙️ অনুসন্ধান সেটিংস")
        top_k = st.slider("প্রাসঙ্গিক ধারার সংখ্যা (Top-K):", min_value=1, max_value=5, value=3)

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
        "<div class='metric-box'><div class='metric-value'>সংশোধিত ২০২৬</div><div"
        " class='metric-label'>লিগ্যাল স্ট্যাটাস ট্র্যাকিং</div></div>",
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
    "🔍 আইনি অনুসন্ধান (Dynamic AI Search)",
    "📊 ডেটাবেজ হিস্ট্রি (Audit Trail)",
])

with tab_search:
    st.markdown("##### 💬 আপনার আইনি প্রশ্ন বা সমস্যাটি বাংলায় লিখুন:")
    
    with st.form("search_form"):
        query_input = st.text_area(
            "প্রশ্ন বা ঘটনা ইনপুট দিন:",
            placeholder="উদাহরণ:\n- কোনো কর্মীকে হঠাৎ চাকরি থেকে বাদ দিলে কী ক্ষতিপূরণ দিতে হবে?\n- অতিরিক্ত কাজের জন্য মালিক কত টাকা ভাতা প্রদান করবে?\n- ধারা ১৮৪ বা ধারা ৬৫ অনুযায়ী কী নিয়ম রয়েছে?",
            height=100
        )
        col_btn1, col_btn2 = st.columns([5, 1])
        search_clicked = col_btn1.form_submit_button("🔍 আইনি বিশ্লেষণ ও ধারা খুঁজুন", type="primary", use_container_width=True)
        clear_clicked = col_btn2.form_submit_button("রিসেট", use_container_width=True)

    if clear_clicked:
        st.rerun()

    if search_clicked and query_input.strip():
        q = query_input.strip()

        # Guardrail: Check for out-of-range statutes
        sec_num_match = re.search(r"ধারা\s*([০-৯0-9]+)", q)
        if sec_num_match:
            raw_n = sec_num_match.group(1)
            bengali_digits = {
                "০": "0", "১": "1", "২": "2", "৩": "3", "৪": "4",
                "৫": "5", "৬": "6", "৭": "7", "৮": "8", "৯": "9",
            }
            norm_n = int("".join(bengali_digits.get(ch, ch) for ch in raw_n))
            if norm_n > 353:
                st.error(
                    f"🚨 **আইনি সতর্কতা:** বাংলাদেশ শ্রম আইন, ২০০৬-এ **ধারা {raw_n}** নামে"
                    " কোনো ধারার অস্তিত্ব নেই। সর্বোচ্চ ধারা সংখ্যা ৩৫৩। সিস্টেম কোনো"
                    " কাল্পনিক বা হ্যালুসিনেটেড তথ্য প্রদান করবে না।"
                )
                log_audit_trail(
                    st.session_state["user"].get("id"),
                    q,
                    f"ধারা {raw_n} [Not Found]",
                    "Rejected",
                )
                st.stop()

        if collection is not None:
            chosen_k = top_k if 'top_k' in locals() else 3
            with st.spinner("শ্রম আইন, ২০০৬-এর ৩৭৫টি ধারার ভেক্টর স্পেসে অনুসন্ধান করা হচ্ছে..."):
                results = collection.query(
                    query_texts=[q],
                    n_results=chosen_k,
                    include=["documents", "metadatas", "distances"],
                )

            if results and results.get("documents") and len(results["documents"][0]) > 0:
                docs = results["documents"][0]
                metas = results["metadatas"][0]
                distances = results["distances"][0]

                best_distance = distances[0]
                confidence_score = round(max(0.0, 1.0 - (best_distance / 2.0)), 2)

                if confidence_score < 0.25:
                    st.warning(
                        "⚠️ আপনার প্রশ্নের সাথে সুনির্দিষ্ট কোনো ধারার সরাসরি মিল পাওয়া যায়নি। অনুগ্রহ করে শ্রম অধিকার বা ধারা সম্পর্কিত শব্দ ব্যবহার করুন।"
                    )
                else:
                    st.success(f"✅ আইনি রেফারেন্স পাওয়া গেছে (কনফিডেন্স স্কোর: {confidence_score * 100:.0f}%)")

                    for i, (doc, meta) in enumerate(zip(docs, metas)):
                        sec_num = meta.get("section_number", "N/A")
                        sec_title = meta.get("section_title", "আইনি ধারা")
                        status = meta.get("legal_status", "Active")
                        amendment = meta.get("amendment_provenance", "মূল শ্রম আইন, ২০০৬")

                        card_class = "statute-card"
                        badge_html = "<span class='badge badge-active'>সক্রিয় (Active)</span>"

                        if "repeal" in str(status).lower() or "বিলুপ্ত" in str(status):
                            card_class += " repealed"
                            badge_html = "<span class='badge badge-repealed'>⚠️ বিলুপ্ত (Repealed)</span>"
                        elif "amend" in str(status).lower() or "সংশোধিত" in str(status):
                            card_class += " amended"
                            badge_html = "<span class='badge badge-amended'>🔄 সংশোধিত (Amended)</span>"

                        st.markdown(
                            f"""
                            <div class='{card_class}'>
                                <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;'>
                                    <h3 style='margin:0; font-size:18px; color:#38bdf8;'>ধারা {sec_num}: {sec_title}</h3>
                                    <div>{badge_html}</div>
                                </div>
                                <div style='color:#94a3b8; font-size:13px; margin-bottom:12px;'>
                                    📜 <b>সূত্র ও সংশোধনী ইতিহাস:</b> {amendment}
                                </div>
                                <div class='statute-body'>
                                    {doc}
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        if i == 0:
                            log_audit_trail(
                                st.session_state["user"].get("id"),
                                q,
                                f"ধারা {sec_num}: {sec_title}",
                                status,
                            )
            else:
                st.warning("কোনো তথ্য পাওয়া যায়নি।")

with tab_audit:
    st.markdown("#### 📊 ডেটাবেজ অডিট ট্রেইল (Audit Logs)")
    st.caption("প্রতিটি আইনি প্রশ্ন, সংশ্লিষ্ট ধারা এবং প্রোভেন্যান্স রিয়েল-টাইম SQLite ডেটাবেজে সংরক্ষিত হচ্ছে।")

    logs = get_audit_trail(limit=50)
    if logs:
        df = pd.DataFrame(logs)
        df.columns = [
            "লগ আইডি",
            "ব্যবহারকারী",
            "অনুসন্ধান প্রশ্ন",
            "রিট্রিভড ধারা",
            "আইনি স্ট্যাটাস",
            "সময়",
        ]
        st.dataframe(df, use_container_width=True)

        # CSV Export
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 অডিট হিস্ট্রি CSV ডাউনলোড করুন",
            data=csv,
            file_name="legal_assistant_audit_logs.csv",
            mime="text/csv",
            use_container_width=True,
        )
    else:
        st.info("এখনও কোনো অডিট লগ রেকর্ড তৈরি হয়নি।")