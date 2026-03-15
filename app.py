import os
import uuid
from datetime import datetime

import streamlit as st
import google.generativeai as genai


# =========================
# Page Config
# =========================
st.set_page_config(
    page_title="Lobster AI",
    page_icon="🦞",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    #MainMenu, footer, header {visibility: hidden;}

    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 1rem;
        max-width: 1100px;
    }

    section[data-testid="stSidebar"] {
        width: 320px !important;
    }

    .lobster-title {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }

    .lobster-subtitle {
        color: #666;
        margin-bottom: 1rem;
    }

    .chat-empty {
        text-align: center;
        padding: 3rem 1rem 2rem 1rem;
        color: #666;
    }

    .chat-empty h2 {
        margin-bottom: 0.5rem;
    }

    .session-meta {
        font-size: 0.8rem;
        color: #888;
    }

    .stButton > button {
        border-radius: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================
# ENV / Gemini
# =========================
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    st.error("Missing env var: GOOGLE_API_KEY")
    st.stop()

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")


# =========================
# Session State
# =========================
if "chat_sessions" not in st.session_state:
    st.session_state.chat_sessions = {}

if "active_chat_id" not in st.session_state:
    new_id = str(uuid.uuid4())
    st.session_state.active_chat_id = new_id
    st.session_state.chat_sessions[new_id] = {
        "title": "New Chat",
        "messages": [],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

if "uploaded_file_cache" not in st.session_state:
    st.session_state.uploaded_file_cache = None


# =========================
# Helpers
# =========================
def get_active_chat():
    return st.session_state.chat_sessions[st.session_state.active_chat_id]


def create_new_chat():
    new_id = str(uuid.uuid4())
    st.session_state.chat_sessions[new_id] = {
        "title": "New Chat",
        "messages": [],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    st.session_state.active_chat_id = new_id
    st.session_state.uploaded_file_cache = None


def build_history_for_model(messages, limit=12):
    history = []
    for m in messages[-limit:]:
        role = "user" if m["role"] == "user" else "model"
        history.append({"role": role, "parts": [m["content"]]})
    return history


def update_chat_title_if_needed(chat_id, prompt):
    current_title = st.session_state.chat_sessions[chat_id]["title"]
    if current_title == "New Chat":
        title = prompt.strip().replace("\n", " ")[:30]
        st.session_state.chat_sessions[chat_id]["title"] = title or "New Chat"


def get_sorted_sessions():
    items = list(st.session_state.chat_sessions.items())
    items.sort(
        key=lambda x: x[1].get("created_at", ""),
        reverse=True,
    )
    return items


# =========================
# Sidebar (ChatGPT-like)
# =========================
with st.sidebar:
    st.markdown("## 🦞 Lobster")

    if st.button("＋ New Chat", use_container_width=True):
        create_new_chat()
        st.rerun()

    st.markdown("---")
    st.markdown("### Chats")

    for chat_id, chat_data in get_sorted_sessions():
        label = chat_data["title"] or "New Chat"
        is_active = chat_id == st.session_state.active_chat_id
        prefix = "🟣 " if is_active else "⚪ "
        if st.button(
            f"{prefix}{label}",
            key=f"chat_{chat_id}",
            use_container_width=True,
        ):
            st.session_state.active_chat_id = chat_id
            st.rerun()

    st.markdown("---")
    uploaded_file = st.file_uploader(
        "Upload context",
        type=["txt", "pdf", "csv", "png", "jpg", "jpeg"],
        key="context_file",
    )

    if uploaded_file is not None:
        st.session_state.uploaded_file_cache = {
            "name": uploaded_file.name,
            "type": uploaded_file.type,
            "data": uploaded_file.getvalue(),
        }
        st.caption(f"已載入：{uploaded_file.name}")


# =========================
# Main UI
# =========================
active_chat = get_active_chat()
messages = active_chat["messages"]

st.markdown('<div class="lobster-title">🦞 龍蝦王助手</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="lobster-subtitle">單人版 · ChatGPT 風格介面</div>',
    unsafe_allow_html=True,
)

if not messages:
    st.markdown(
        """
        <div class="chat-empty">
            <h2>今天想問龍蝦什麼？</h2>
            <div>你可以直接輸入問題，或先在左側上傳檔案。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

for msg in messages:
    with st.chat_message("assistant" if msg["role"] == "assistant" else "user"):
        st.markdown(msg["content"])


# =========================
# Chat Input
# =========================
prompt = st.chat_input("Message Lobster...")

if prompt:
    active_chat = get_active_chat()
    active_chat["messages"].append({"role": "user", "content": prompt})
    update_chat_title_if_needed(st.session_state.active_chat_id, prompt)

    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        content_parts = [prompt]

        if st.session_state.uploaded_file_cache:
            content_parts.append(
                {
                    "mime_type": st.session_state.uploaded_file_cache["type"],
                    "data": st.session_state.uploaded_file_cache["data"],
                }
            )

        history = build_history_for_model(active_chat["messages"][:-1], limit=12)

        response = model.generate_content(
            contents=history + [{"role": "user", "parts": content_parts}]
        )
        reply = response.text

    except Exception as e:
        reply = f"⚠️ AI error: {e}"

    with st.chat_message("assistant"):
        st.markdown(reply)

    active_chat["messages"].append({"role": "assistant", "content": reply})
    st.rerun()
