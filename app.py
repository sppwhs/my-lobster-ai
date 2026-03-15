import os
import time
import uuid
from typing import List, Dict, Optional, Tuple

import streamlit as st
import google.generativeai as genai
from supabase import create_client


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
        margin-bottom: 0.8rem;
    }

    .chat-empty {
        text-align: center;
        padding: 3rem 1rem 2rem 1rem;
        color: #666;
    }

    .chat-empty h2 {
        margin-bottom: 0.5rem;
    }

    .stButton > button {
        border-radius: 12px;
    }

    .thinking-text {
        color: #666;
        font-style: italic;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================
# ENV
# =========================
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

missing = []
if not GOOGLE_API_KEY:
    missing.append("GOOGLE_API_KEY")
if not SUPABASE_URL:
    missing.append("SUPABASE_URL")
if not SUPABASE_ANON_KEY:
    missing.append("SUPABASE_ANON_KEY")

if missing:
    st.error("Missing env vars: " + ", ".join(missing))
    st.stop()

genai.configure(api_key=GOOGLE_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# =========================
# Session State
# =========================
if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = None

if "messages" not in st.session_state:
    st.session_state.messages = []

if "uploaded_file_cache" not in st.session_state:
    st.session_state.uploaded_file_cache = None

if "rename_target" not in st.session_state:
    st.session_state.rename_target = None

if "rename_input" not in st.session_state:
    st.session_state.rename_input = ""


# =========================
# DB Helpers
# =========================
def list_sessions() -> List[Dict]:
    resp = (
        supabase.table("lobster_sessions")
        .select("id, title, created_at, updated_at")
        .order("updated_at", desc=True)
        .limit(200)
        .execute()
    )
    return resp.data or []


def create_session(title: str = "New Chat") -> str:
    sid = str(uuid.uuid4())
    supabase.table("lobster_sessions").insert(
        {
            "id": sid,
            "title": title[:80] or "New Chat",
        }
    ).execute()
    return sid


def load_messages(session_id: str) -> None:
    resp = (
        supabase.table("lobster_messages")
        .select("role, content, created_at")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    st.session_state.messages = [
        {"role": row["role"], "content": row["content"]}
        for row in (resp.data or [])
    ]


def save_message(session_id: str, role: str, content: str) -> None:
    supabase.table("lobster_messages").insert(
        {
            "session_id": session_id,
            "role": role,
            "content": content,
        }
    ).execute()


def update_session_title_if_needed(session_id: str, prompt: str) -> None:
    resp = (
        supabase.table("lobster_sessions")
        .select("title")
        .eq("id", session_id)
        .single()
        .execute()
    )

    current_title = "New Chat"
    if resp.data:
        current_title = resp.data.get("title") or "New Chat"

    if current_title == "New Chat":
        new_title = prompt.strip().replace("\n", " ")[:30] or "New Chat"
        (
            supabase.table("lobster_sessions")
            .update({"title": new_title})
            .eq("id", session_id)
            .execute()
        )


def rename_session(session_id: str, new_title: str) -> None:
    clean_title = (new_title or "").strip()[:80]
    if not clean_title:
        clean_title = "New Chat"

    (
        supabase.table("lobster_sessions")
        .update({"title": clean_title})
        .eq("id", session_id)
        .execute()
    )


def delete_session(session_id: str) -> None:
    (
        supabase.table("lobster_sessions")
        .delete()
        .eq("id", session_id)
        .execute()
    )


def touch_session(session_id: str) -> None:
    resp = (
        supabase.table("lobster_sessions")
        .select("title")
        .eq("id", session_id)
        .single()
        .execute()
    )
    if resp.data:
        current_title = resp.data.get("title") or "New Chat"
        (
            supabase.table("lobster_sessions")
            .update({"title": current_title})
            .eq("id", session_id)
            .execute()
        )


def ensure_active_chat() -> None:
    if st.session_state.active_chat_id:
        return

    sessions = list_sessions()
    if sessions:
        st.session_state.active_chat_id = sessions[0]["id"]
        load_messages(st.session_state.active_chat_id)
    else:
        sid = create_session("New Chat")
        st.session_state.active_chat_id = sid
        st.session_state.messages = []


# =========================
# AI Helpers
# =========================
def build_history_for_model(messages: List[Dict], limit: int = 12) -> List[Dict]:
    history = []
    for m in messages[-limit:]:
        role = "user" if m["role"] == "user" else "model"
        history.append({"role": role, "parts": [m["content"]]})
    return history


def build_content_parts(prompt: str) -> List:
    content_parts = [prompt]

    if st.session_state.uploaded_file_cache:
        content_parts.append(
            {
                "mime_type": st.session_state.uploaded_file_cache["type"],
                "data": st.session_state.uploaded_file_cache["data"],
            }
        )

    return content_parts


def get_candidate_models() -> List[str]:
    # 依序 fallback，改善 2.5 配額爆掉、1.5 某些環境不穩的問題
    return [
        "gemini-2.5-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
    ]


def is_quota_error(err_text: str) -> bool:
    t = err_text.lower()
    return (
        "429" in t
        or "quota" in t
        or "rate limit" in t
        or "resource has been exhausted" in t
        or "exceeded your current quota" in t
    )


def generate_reply_with_fallback(
    history: List[Dict], content_parts: List
) -> Tuple[str, Optional[str]]:
    """
    回傳:
    - reply
    - used_model
    """
    model_names = get_candidate_models()
    last_error = None

    for model_name in model_names:
        try:
            model = genai.GenerativeModel(model_name)

            # 對 429 做一點點 retry，避免瞬間限流
            for attempt in range(2):
                try:
                    response = model.generate_content(
                        contents=history + [{"role": "user", "parts": content_parts}]
                    )
                    reply = getattr(response, "text", None)

                    if not reply:
                        reply = "⚠️ 龍蝦有收到問題，但這次模型沒有回傳文字內容。"

                    return reply, model_name

                except Exception as e:
                    err_text = str(e)
                    last_error = err_text

                    # 如果是 quota / rate limit，短暫等一下再試一次
                    if is_quota_error(err_text) and attempt == 0:
                        time.sleep(1.5)
                        continue

                    raise

        except Exception as e:
            last_error = str(e)
            continue

    if last_error and is_quota_error(last_error):
        return (
            "⚠️ 龍蝦今天的 AI 額度暫時用完了，請稍後再試，或改用新的 Google API Key / 升級額度。",
            None,
        )

    return (
        f"⚠️ AI error: {last_error}" if last_error else "⚠️ AI 暫時無法回覆，請稍後再試。",
        None,
    )


def typewriter_effect(container, text: str, speed: float = 0.01) -> None:
    rendered = ""
    for ch in text:
        rendered += ch
        container.markdown(rendered)
        time.sleep(speed)


# =========================
# Init
# =========================
ensure_active_chat()


# =========================
# Sidebar
# =========================
with st.sidebar:
    st.markdown("## 🦞 Lobster")

    if st.button("＋ New Chat", use_container_width=True):
        sid = create_session("New Chat")
        st.session_state.active_chat_id = sid
        st.session_state.messages = []
        st.session_state.uploaded_file_cache = None
        st.session_state.rename_target = None
        st.session_state.rename_input = ""
        st.rerun()

    st.markdown("---")
    st.markdown("### Chats")

    try:
        sessions = list_sessions()

        for s in sessions:
            session_id = s["id"]
            label = s["title"] or "New Chat"
            active = session_id == st.session_state.active_chat_id

            col1, col2, col3 = st.columns([8, 1, 1])

            with col1:
                prefix = "🟣 " if active else "⚪ "
                if st.button(
                    f"{prefix}{label}",
                    key=f"chat_{session_id}",
                    use_container_width=True,
                ):
                    st.session_state.active_chat_id = session_id
                    load_messages(session_id)
                    st.session_state.rename_target = None
                    st.rerun()

            with col2:
                if st.button("✏️", key=f"rename_btn_{session_id}"):
                    st.session_state.rename_target = session_id
                    st.session_state.rename_input = label
                    st.rerun()

            with col3:
                if st.button("🗑️", key=f"delete_btn_{session_id}"):
                    delete_session(session_id)

                    if st.session_state.active_chat_id == session_id:
                        remaining = list_sessions()
                        if remaining:
                            st.session_state.active_chat_id = remaining[0]["id"]
                            load_messages(remaining[0]["id"])
                        else:
                            new_id = create_session("New Chat")
                            st.session_state.active_chat_id = new_id
                            st.session_state.messages = []

                    st.session_state.rename_target = None
                    st.rerun()

            if st.session_state.rename_target == session_id:
                new_title = st.text_input(
                    "重新命名",
                    value=st.session_state.rename_input,
                    key=f"rename_input_{session_id}",
                    label_visibility="collapsed",
                )

                col_save, col_cancel = st.columns(2)
                with col_save:
                    if st.button("保存", key=f"rename_save_{session_id}", use_container_width=True):
                        rename_session(session_id, new_title)
                        st.session_state.rename_target = None
                        st.session_state.rename_input = ""
                        st.rerun()
                with col_cancel:
                    if st.button("取消", key=f"rename_cancel_{session_id}", use_container_width=True):
                        st.session_state.rename_target = None
                        st.session_state.rename_input = ""
                        st.rerun()

        st.markdown("---")
    except Exception as e:
        st.caption(f"Load sessions failed: {e}")

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

    if st.session_state.uploaded_file_cache:
        if st.button("清除檔案", use_container_width=True):
            st.session_state.uploaded_file_cache = None
            st.rerun()


# =========================
# Main UI
# =========================
st.markdown('<div class="lobster-title">🦞 龍蝦王小助手</div>', unsafe_allow_html=True)

if not st.session_state.messages:
    st.markdown(
        """
        <div class="chat-empty">
            <h2>今天想問龍蝦什麼？</h2>
            <div>你可以直接輸入問題，或先在左側上傳檔案。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

for msg in st.session_state.messages:
    with st.chat_message("assistant" if msg["role"] == "assistant" else "user"):
        st.markdown(msg["content"])


# =========================
# Chat Input
# =========================
prompt = st.chat_input("Message Lobster...")

if prompt:
    session_id = st.session_state.active_chat_id

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        save_message(session_id, "user", prompt)
        update_session_title_if_needed(session_id, prompt)
        touch_session(session_id)
    except Exception as e:
        st.warning(f"Save user message failed: {e}")

    with st.chat_message("assistant"):
        thinking_placeholder = st.empty()

        if st.session_state.uploaded_file_cache:
            thinking_steps = [
                "🦞 龍蝦正在閱讀檔案中...",
                "🦞 龍蝦正在整理上下文...",
                "🦞 龍蝦正在思考中...",
            ]
        else:
            thinking_steps = [
                "🦞 龍蝦正在思考中...",
                "🦞 龍蝦正在整理答案...",
            ]

        for step in thinking_steps:
            thinking_placeholder.markdown(step)

        try:
            content_parts = build_content_parts(prompt)
            history = build_history_for_model(st.session_state.messages[:-1], limit=12)

            with st.spinner("龍蝦正在整理答案..."):
                reply, used_model = generate_reply_with_fallback(history, content_parts)

        except Exception as e:
            reply = f"⚠️ AI error: {e}"
            used_model = None

        output_placeholder = st.empty()
        thinking_placeholder.empty()

        # 如果是錯誤訊息，就不要打字效果
        if reply.startswith("⚠️"):
            output_placeholder.markdown(reply)
        else:
            typewriter_effect(output_placeholder, reply, speed=0.008)

    st.session_state.messages.append({"role": "assistant", "content": reply})

    try:
        save_message(session_id, "assistant", reply)
        touch_session(session_id)
    except Exception as e:
        st.warning(f"Save assistant message failed: {e}")

    st.rerun()
