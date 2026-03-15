import os
from typing import Any, Optional

import streamlit as st
import google.generativeai as genai
from supabase import create_client


# =========================
# 基本設定
# =========================
st.set_page_config(
    page_title="Lobster AI",
    page_icon="🦞",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    "<style>#MainMenu, footer, header {visibility:hidden;}</style>",
    unsafe_allow_html=True,
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
APP_URL = os.getenv("APP_URL")

missing = []
if not SUPABASE_URL:
    missing.append("SUPABASE_URL")
if not SUPABASE_ANON_KEY:
    missing.append("SUPABASE_ANON_KEY")
if not GOOGLE_API_KEY:
    missing.append("GOOGLE_API_KEY")
if not APP_URL:
    missing.append("APP_URL")

if missing:
    st.error("Missing env vars: " + ", ".join(missing))
    st.stop()

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")


# =========================
# Supabase client
# =========================
def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# =========================
# Session State 初始化
# =========================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "active_chat_session_id" not in st.session_state:
    st.session_state.active_chat_session_id = None

if "access_token" not in st.session_state:
    st.session_state.access_token = None

if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = None

if "user" not in st.session_state:
    st.session_state.user = None

if "oauth_exchanged" not in st.session_state:
    st.session_state.oauth_exchanged = False


# =========================
# 工具函式
# =========================
def safe_getattr(obj: Any, name: str, default=None):
    return getattr(obj, name, default) if obj is not None else default


def get_oauth_url(resp: Any) -> Optional[str]:
    if resp is None:
        return None

    if hasattr(resp, "url") and resp.url:
        return resp.url

    data = safe_getattr(resp, "data")
    if data is not None:
        if isinstance(data, dict):
            return data.get("url")
        if hasattr(data, "url"):
            return data.url

    if isinstance(resp, dict):
        return resp.get("url") or (resp.get("data") or {}).get("url")

    return None


def get_session_obj(supabase):
    try:
        if st.session_state.access_token and st.session_state.refresh_token:
            resp = supabase.auth.set_session(
                st.session_state.access_token,
                st.session_state.refresh_token,
            )
            session = safe_getattr(resp, "session")
            if session:
                return session
    except Exception:
        pass

    try:
        resp = supabase.auth.get_session()
        session = safe_getattr(resp, "session")
        if session:
            return session
    except Exception:
        pass

    return None


def load_user_from_session():
    supabase = get_supabase()
    session = get_session_obj(supabase)
    if not session:
        st.session_state.user = None
        return None

    access_token = safe_getattr(session, "access_token")
    refresh_token = safe_getattr(session, "refresh_token")
    user = safe_getattr(session, "user")

    if access_token:
        st.session_state.access_token = access_token
    if refresh_token:
        st.session_state.refresh_token = refresh_token
    if user:
        st.session_state.user = user

    return user


def user_id() -> Optional[str]:
    user = st.session_state.user
    if not user:
        return None
    return safe_getattr(user, "id")


def user_email() -> str:
    user = st.session_state.user
    if not user:
        return ""
    return safe_getattr(user, "email", "") or ""


def clear_auth_state():
    st.session_state.access_token = None
    st.session_state.refresh_token = None
    st.session_state.user = None
    st.session_state.messages = []
    st.session_state.active_chat_session_id = None
    st.session_state.oauth_exchanged = False


def create_chat_session(title: str = "New Chat") -> Optional[str]:
    uid = user_id()
    if not uid:
        return None

    supabase = get_supabase()
    session = get_session_obj(supabase)
    if not session:
        return None

    resp = (
        supabase.table("chat_sessions")
        .insert(
            {
                "user_id": uid,
                "title": title[:80],
            }
        )
        .execute()
    )

    if resp.data and len(resp.data) > 0:
        return resp.data[0]["id"]

    return None


def load_chat_history(session_id: str):
    uid = user_id()
    if not uid:
        return

    supabase = get_supabase()
    session = get_session_obj(supabase)
    if not session:
        return

    resp = (
        supabase.table("chat_history")
        .select("role, content, created_at")
        .eq("user_id", uid)
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )

    st.session_state.messages = [
        {"role": row["role"], "content": row["content"]}
        for row in (resp.data or [])
    ]


def list_my_sessions():
    uid = user_id()
    if not uid:
        return []

    supabase = get_supabase()
    session = get_session_obj(supabase)
    if not session:
        return []

    resp = (
        supabase.table("chat_sessions")
        .select("id, title, created_at, updated_at")
        .eq("user_id", uid)
        .order("updated_at", desc=True)
        .limit(50)
        .execute()
    )
    return resp.data or []


def save_message(session_id: str, role: str, content: str):
    uid = user_id()
    if not uid:
        return

    supabase = get_supabase()
    session = get_session_obj(supabase)
    if not session:
        return

    supabase.table("chat_history").insert(
        {
            "session_id": session_id,
            "user_id": uid,
            "role": role,
            "content": content,
        }
    ).execute()


def touch_session_title_if_needed(session_id: str, user_prompt: str):
    uid = user_id()
    if not uid:
        return

    supabase = get_supabase()
    session = get_session_obj(supabase)
    if not session:
        return

    resp = (
        supabase.table("chat_sessions")
        .select("title")
        .eq("id", session_id)
        .eq("user_id", uid)
        .single()
        .execute()
    )

    current_title = ""
    if resp.data:
        current_title = resp.data.get("title") or ""

    if current_title == "New Chat":
        new_title = user_prompt.strip()[:30] or "New Chat"
        (
            supabase.table("chat_sessions")
            .update({"title": new_title})
            .eq("id", session_id)
            .eq("user_id", uid)
            .execute()
        )


def build_history_for_model():
    history = []
    for m in st.session_state.messages[-12:]:
        role = "user" if m["role"] == "user" else "model"
        history.append({"role": role, "parts": [m["content"]]})
    return history


def exchange_code_if_present():
    code = st.query_params.get("code")
    if not code or st.session_state.oauth_exchanged:
        return

    supabase = get_supabase()
    try:
        resp = supabase.auth.exchange_code_for_session({"auth_code": code})
        session = safe_getattr(resp, "session")

        if session:
            st.session_state.access_token = safe_getattr(session, "access_token")
            st.session_state.refresh_token = safe_getattr(session, "refresh_token")
            st.session_state.user = safe_getattr(session, "user")
            st.session_state.oauth_exchanged = True

            st.query_params.clear()
            st.rerun()
    except Exception as e:
        st.error(f"Google login failed: {e}")


# 先處理 OAuth callback
exchange_code_if_present()
load_user_from_session()


# =========================
# Sidebar
# =========================
with st.sidebar:
    st.title("🦞 Lobster")

    if st.session_state.user:
        st.success(f"已登入：{user_email()}")

        if st.button("➕ New Chat", use_container_width=True):
            sid = create_chat_session("New Chat")
            st.session_state.active_chat_session_id = sid
            st.session_state.messages = []
            st.rerun()

        if st.button("登出", use_container_width=True):
            try:
                supabase = get_supabase()
                _ = get_session_obj(supabase)
                supabase.auth.sign_out()
            except Exception:
                pass

            clear_auth_state()
            st.rerun()

        st.write("---")
        st.subheader("History")

        try:
            sessions = list_my_sessions()
            for s in sessions:
                label = s["title"] or "New Chat"
                if st.button(f"💬 {label}", key=f"session_{s['id']}", use_container_width=True):
                    st.session_state.active_chat_session_id = s["id"]
                    load_chat_history(s["id"])
                    st.rerun()
        except Exception as e:
            st.caption(f"Load history failed: {e}")

    else:
        st.info("請先用 Google 登入")

        if st.button("使用 Google 登入", use_container_width=True):
            try:
                supabase = get_supabase()
                resp = supabase.auth.sign_in_with_oauth(
                    {
                        "provider": "google",
                        "options": {
                            "redirect_to": APP_URL,
                        },
                    }
                )
                oauth_url = get_oauth_url(resp)
                if oauth_url:
                    st.link_button("點這裡前往 Google 登入", oauth_url, use_container_width=True)
                else:
                    st.error("Cannot generate Google login URL.")
            except Exception as e:
                st.error(f"OAuth init failed: {e}")


# =========================
# Main
# =========================
st.title("🦞 龍蝦王助手")

if not st.session_state.user:
    st.write("先按左側 **使用 Google 登入**。")
    st.stop()

if not st.session_state.active_chat_session_id:
    st.info("先按左側 `New Chat` 建立新對話。")

for msg in st.session_state.messages:
    with st.chat_message("assistant" if msg["role"] == "assistant" else "user"):
        st.markdown(msg["content"])

uploaded_file = st.file_uploader(
    "Upload context",
    type=["txt", "pdf", "csv", "png", "jpg", "jpeg"],
    key="context_file",
)

prompt = st.chat_input("Message Lobster...")

if prompt:
    if not st.session_state.active_chat_session_id:
        sid = create_chat_session(prompt[:30] or "New Chat")
        st.session_state.active_chat_session_id = sid

    session_id = st.session_state.active_chat_session_id
    if not session_id:
        st.error("Cannot create chat session.")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        save_message(session_id, "user", prompt)
        touch_session_title_if_needed(session_id, prompt)
    except Exception as e:
        st.warning(f"Save user message failed: {e}")

    try:
        content_parts = [prompt]

        if uploaded_file is not None:
            file_bytes = uploaded_file.getvalue()
            content_parts.append(
                {
                    "mime_type": uploaded_file.type,
                    "data": file_bytes,
                }
            )

        history = build_history_for_model()
        response = model.generate_content(
            contents=history + [{"role": "user", "parts": content_parts}]
        )
        reply = response.text

    except Exception as e:
        reply = f"⚠️ AI error: {e}"

    with st.chat_message("assistant"):
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})

    try:
        save_message(session_id, "assistant", reply)
    except Exception as e:
        st.warning(f"Save assistant message failed: {e}")
