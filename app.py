import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ===============================
# 1. 環境檢查
# ===============================

api_key = os.getenv("GOOGLE_API_KEY")
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

if not api_key:
    st.error("Missing GOOGLE_API_KEY")
    st.stop()

if not supabase_url or not supabase_key:
    st.error("Missing Supabase config")
    st.stop()

genai.configure(api_key=api_key)

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash"
)

supabase = create_client(supabase_url, supabase_key)

# ===============================
# 2. Session 初始化
# ===============================

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

# ===============================
# 3. Streamlit UI
# ===============================

st.set_page_config(
    page_title="Lobster AI",
    page_icon="🦞",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown(
    "<style>#MainMenu, footer, header {visibility: hidden;}</style>",
    unsafe_allow_html=True
)

# ===============================
# Sidebar
# ===============================

with st.sidebar:

    st.title("🦞 Lobster")

    if st.button("➕ New Chat", use_container_width=True):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()

    st.write("---")

    uploaded_file = st.file_uploader(
        "Upload context",
        type=["txt", "pdf", "csv", "png", "jpg", "jpeg"]
    )

    st.write("---")
    st.subheader("History")

    try:

        resp = (
            supabase
            .table("chat_history")
            .select("session_id, content, role, created_at")
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )

        sessions = {}

        for r in resp.data:
            sid = r["session_id"]

            if r["role"] == "user" and sid not in sessions:
                sessions[sid] = r["content"][:25]

        for sid, title in sessions.items():

            if st.button(f"💬 {title}", key=sid):

                st.session_state.session_id = sid

                h = (
                    supabase
                    .table("chat_history")
                    .select("*")
                    .eq("session_id", sid)
                    .order("created_at")
                    .execute()
                )

                st.session_state.messages = [
                    {"role": r["role"], "content": r["content"]}
                    for r in h.data
                ]

                st.rerun()

    except Exception as e:

        st.caption("History loading failed")

# ===============================
# 主畫面
# ===============================

st.title("🦞 龍蝦王助手")

for msg in st.session_state.messages:

    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ===============================
# Gemini 對話
# ===============================

def build_history():

    history = []

    for m in st.session_state.messages[-12:]:

        role = "user" if m["role"] == "user" else "model"

        history.append({
            "role": role,
            "parts": [m["content"]]
        })

    return history


# ===============================
# Chat input
# ===============================

prompt = st.chat_input("Message Lobster...")

if prompt:

    st.session_state.messages.append({
        "role": "user",
        "content": prompt
    })

    with st.chat_message("user"):
        st.markdown(prompt)

    try:

        content_parts = [prompt]

        if uploaded_file:

            file_bytes = uploaded_file.getvalue()

            content_parts.append({
                "mime_type": uploaded_file.type,
                "data": file_bytes
            })

        history = build_history()

        response = model.generate_content(
            contents=history + [{
                "role": "user",
                "parts": content_parts
            }]
        )

        reply = response.text

    except Exception as e:

        reply = f"⚠️ AI error: {str(e)}"

    with st.chat_message("assistant"):
        st.markdown(reply)

    st.session_state.messages.append({
        "role": "assistant",
        "content": reply
    })

    # ===============================
    # 存入 Supabase
    # ===============================

    try:

        supabase.table("chat_history").insert([

            {
                "session_id": st.session_state.session_id,
                "role": "user",
                "content": prompt
            },

            {
                "session_id": st.session_state.session_id,
                "role": "assistant",
                "content": reply
            }

        ]).execute()

    except Exception as e:

        st.warning("History save failed")
