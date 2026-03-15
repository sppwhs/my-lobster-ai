import os
import re
import time
import uuid
from io import BytesIO
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple

import pandas as pd
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
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    #MainMenu, footer, header {
        visibility: hidden;
    }

    html, body, [class*="css"] {
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }

    .block-container {
        padding-top: 0.45rem;
        padding-bottom: 0.7rem;
        padding-left: 0.9rem;
        padding-right: 0.9rem;
        max-width: 880px;
    }

    section[data-testid="stSidebar"] {
        display: none !important;
    }

    /* Header */
    .lobster-appbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 0.35rem;
    }

    .lobster-title-wrap {
        min-width: 0;
    }

    .lobster-title {
        font-size: 1.5rem;
        font-weight: 800;
        margin: 0;
        line-height: 1.1;
        letter-spacing: -0.02em;
    }

    .lobster-subtle {
        color: #6b7280;
        font-size: 0.82rem;
        margin-top: 0.06rem;
        line-height: 1.2;
    }

    /* Toolbar / panels */
    .toolbar-note {
        color: #6b7280;
        font-size: 0.78rem;
        margin-top: -0.15rem;
        margin-bottom: 0.3rem;
    }

    .panel-shell {
        border: 1px solid #ececec;
        border-radius: 16px;
        padding: 0.65rem 0.7rem 0.45rem 0.7rem;
        background: #fcfcfc;
        margin-bottom: 0.65rem;
    }

    .panel-title {
        font-size: 0.95rem;
        font-weight: 700;
        margin-bottom: 0.45rem;
    }

    .memory-box {
        padding: 8px 10px;
        border: 1px solid #efefef;
        border-radius: 12px;
        margin-bottom: 8px;
        background: #ffffff;
    }

    .memory-title {
        font-weight: 700;
        font-size: 0.92rem;
        margin-bottom: 2px;
        line-height: 1.25;
    }

    .memory-meta {
        font-size: 0.75rem;
        color: #666;
        margin-bottom: 3px;
    }

    .memory-body {
        font-size: 0.85rem;
        color: #222;
        line-height: 1.35;
    }

    /* Chat list */
    .chat-empty {
        text-align: center;
        padding: 1.6rem 0.8rem 1.2rem 0.8rem;
        color: #666;
    }

    .chat-empty h2 {
        margin-bottom: 0.3rem;
        font-size: 1.08rem;
    }

    .section-divider {
        margin-top: 0.35rem;
        margin-bottom: 0.45rem;
    }

    /* Streamlit element tuning */
    div[data-testid="stChatMessage"] {
        border-radius: 14px;
    }

    .stButton > button {
        border-radius: 12px !important;
        min-height: 2.2rem !important;
        padding: 0.32rem 0.7rem !important;
        font-size: 0.92rem !important;
    }

    .stTextInput input, .stTextArea textarea {
        border-radius: 12px !important;
    }

    div[data-testid="stFileUploader"] section {
        padding: 0.35rem !important;
        border-radius: 12px !important;
    }

    div[data-testid="stExpander"] {
        border: none !important;
    }

    div[data-testid="stExpander"] details {
        border: 1px solid #ececec !important;
        border-radius: 12px !important;
        background: white !important;
    }

    div[data-testid="stExpander"] summary {
        padding-top: 0.4rem !important;
        padding-bottom: 0.4rem !important;
        font-size: 0.92rem !important;
    }

    /* compact horizontal radio */
    div[role="radiogroup"] {
        gap: 0.35rem;
    }

    /* reduce excessive vertical gaps */
    .element-container {
        margin-bottom: 0.28rem !important;
    }

    hr {
        margin-top: 0.45rem !important;
        margin-bottom: 0.65rem !important;
    }

    @media (max-width: 768px) {
        .block-container {
            padding-top: 0.35rem;
            padding-left: 0.7rem;
            padding-right: 0.7rem;
            padding-bottom: 0.5rem;
            max-width: 100%;
        }

        .lobster-title {
            font-size: 1.24rem;
        }

        .lobster-subtle {
            font-size: 0.75rem;
        }

        .panel-shell {
            padding: 0.55rem 0.55rem 0.35rem 0.55rem;
            border-radius: 14px;
        }

        .stButton > button {
            min-height: 2rem !important;
            padding: 0.28rem 0.6rem !important;
            font-size: 0.88rem !important;
        }

        .chat-empty {
            padding: 1.15rem 0.5rem 0.9rem 0.5rem;
        }

        .chat-empty h2 {
            font-size: 1rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================
# ENV
# =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

raw_api_keys = os.getenv("GOOGLE_API_KEYS", "").strip()
single_api_key = os.getenv("GOOGLE_API_KEY", "").strip()

API_KEY_LIST = []
if raw_api_keys:
    API_KEY_LIST = [k.strip() for k in raw_api_keys.split(",") if k.strip()]
elif single_api_key:
    API_KEY_LIST = [single_api_key]

missing = []
if not SUPABASE_URL:
    missing.append("SUPABASE_URL")
if not SUPABASE_ANON_KEY:
    missing.append("SUPABASE_ANON_KEY")
if not API_KEY_LIST:
    missing.append("GOOGLE_API_KEYS or GOOGLE_API_KEY")

if missing:
    st.error("Missing env vars: " + ", ".join(missing))
    st.stop()

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

if "copy_notice" not in st.session_state:
    st.session_state.copy_notice = None

if "memory_refresh_key" not in st.session_state:
    st.session_state.memory_refresh_key = 0

if "tool_panel" not in st.session_state:
    st.session_state.tool_panel = "收起"


# =========================
# Utility
# =========================
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def shorten_text(text: str, max_len: int = 80) -> str:
    t = (text or "").strip().replace("\n", " ")
    return t[:max_len] if t else "New Chat"


def tokenize(text: str) -> List[str]:
    text = (text or "").lower()
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", text)
    stopwords = {
        "the", "a", "an", "to", "is", "are", "of", "and", "or", "in", "on",
        "我", "你", "他", "她", "它", "我們", "你們", "他們", "請", "幫我", "一下",
        "可以", "想", "要", "這個", "那個", "就是", "然後", "還有", "目前", "今天"
    }
    return [t for t in tokens if t not in stopwords and len(t) > 1]


# =========================
# DB Helpers - Sessions / Messages
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


def create_message(
    session_id: str,
    role: str,
    content: str,
    status: str = "completed",
    error_message: Optional[str] = None,
) -> Optional[int]:
    resp = (
        supabase.table("lobster_messages")
        .insert(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "status": status,
                "error_message": error_message,
            }
        )
        .execute()
    )
    if resp.data and len(resp.data) > 0:
        return resp.data[0]["id"]
    return None


def update_message(
    message_id: int,
    content: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    (
        supabase.table("lobster_messages")
        .update(
            {
                "content": content,
                "status": status,
                "error_message": error_message,
            }
        )
        .eq("id", message_id)
        .execute()
    )


def mark_stale_pending_messages(session_id: str, stale_minutes: int = 5) -> None:
    resp = (
        supabase.table("lobster_messages")
        .select("id, status, updated_at")
        .eq("session_id", session_id)
        .eq("role", "assistant")
        .eq("status", "pending")
        .execute()
    )

    rows = resp.data or []
    cutoff = now_utc() - timedelta(minutes=stale_minutes)

    for row in rows:
        updated_at = parse_iso_dt(row.get("updated_at"))
        if updated_at and updated_at < cutoff:
            update_message(
                row["id"],
                content="⚠️ 上一次回覆在處理途中中斷，請重新發問。",
                status="failed",
                error_message="interrupted_or_closed",
            )


def load_messages(session_id: str) -> None:
    mark_stale_pending_messages(session_id)

    resp = (
        supabase.table("lobster_messages")
        .select("id, role, content, status, error_message, created_at, updated_at")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )

    messages = []
    for row in (resp.data or []):
        messages.append(
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "status": row.get("status", "completed"),
                "error_message": row.get("error_message"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        )

    st.session_state.messages = messages


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
        (
            supabase.table("lobster_sessions")
            .update({"title": shorten_text(prompt, 30)})
            .eq("id", session_id)
            .execute()
        )


def rename_session(session_id: str, new_title: str) -> None:
    (
        supabase.table("lobster_sessions")
        .update({"title": shorten_text(new_title, 80)})
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
# DB Helpers - Memory
# =========================
def list_memory_items(limit: int = 100) -> List[Dict]:
    resp = (
        supabase.table("memory_items")
        .select("id, title, content, tags, source, created_at, updated_at")
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def create_memory_item(title: str, content: str, tags: Optional[List[str]] = None, source: str = "manual") -> None:
    tags = tags or []
    clean_tags = [t.strip() for t in tags if str(t).strip()]
    supabase.table("memory_items").insert(
        {
            "title": shorten_text(title, 120),
            "content": content.strip(),
            "tags": clean_tags,
            "source": source,
        }
    ).execute()


def delete_memory_item(memory_id: str) -> None:
    (
        supabase.table("memory_items")
        .delete()
        .eq("id", memory_id)
        .execute()
    )


def get_relevant_memory(query: str, top_k: int = 5) -> List[Dict]:
    memories = list_memory_items(limit=200)
    if not memories:
        return []

    query_tokens = set(tokenize(query))
    scored = []

    for item in memories:
        body = f"{item.get('title', '')}\n{item.get('content', '')}\n{' '.join(item.get('tags', []) or [])}"
        body_tokens = set(tokenize(body))

        overlap = len(query_tokens.intersection(body_tokens))
        bonus = 0
        q = (query or "").lower()
        if q and q in body.lower():
            bonus += 5

        score = overlap + bonus
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: (x[0], x[1].get("updated_at", "")), reverse=True)
    return [item for _, item in scored[:top_k]]


def format_memory_context(query: str) -> str:
    relevant = get_relevant_memory(query, top_k=5)
    if not relevant:
        return ""

    parts = ["以下是與使用者問題最相關的長期記憶，回答時可優先參考："]
    for idx, item in enumerate(relevant, start=1):
        parts.append(
            f"""
記憶 {idx}
標題：{item.get('title', '')}
標籤：{', '.join(item.get('tags', []) or [])}
內容：
{item.get('content', '')}
""".strip()
        )

    return "\n\n".join(parts)


# =========================
# File Helpers
# =========================
def dataframe_to_text(df: pd.DataFrame, max_rows: int = 50, max_cols: int = 20) -> str:
    clipped = df.iloc[:max_rows, :max_cols].copy()
    clipped = clipped.fillna("")
    return clipped.to_markdown(index=False)


def excel_bytes_to_text(file_bytes: bytes, filename: str) -> str:
    output_parts = [f"Excel file: {filename}"]

    xls = pd.ExcelFile(BytesIO(file_bytes))
    sheet_names = xls.sheet_names[:5]

    for sheet_name in sheet_names:
        try:
            df = pd.read_excel(BytesIO(file_bytes), sheet_name=sheet_name)
            output_parts.append(f"\n=== Sheet: {sheet_name} ===")
            output_parts.append(f"Rows: {len(df)}, Columns: {len(df.columns)}")
            if len(df.columns) > 0:
                output_parts.append("Columns: " + ", ".join([str(c) for c in df.columns[:30]]))
            if not df.empty:
                output_parts.append(dataframe_to_text(df))
            else:
                output_parts.append("(empty sheet)")
        except Exception as e:
            output_parts.append(f"\n=== Sheet: {sheet_name} ===")
            output_parts.append(f"Read failed: {e}")

    return "\n".join(output_parts)


def csv_bytes_to_text(file_bytes: bytes, filename: str) -> str:
    try:
        df = pd.read_csv(BytesIO(file_bytes))
        parts = [
            f"CSV file: {filename}",
            f"Rows: {len(df)}, Columns: {len(df.columns)}",
            "Columns: " + ", ".join([str(c) for c in df.columns[:30]]),
            dataframe_to_text(df),
        ]
        return "\n".join(parts)
    except Exception as e:
        return f"CSV file: {filename}\nRead failed: {e}"


def text_bytes_to_text(file_bytes: bytes, filename: str) -> str:
    try:
        text = file_bytes.decode("utf-8", errors="ignore")
        return f"Text file: {filename}\n\n{text[:30000]}"
    except Exception as e:
        return f"Text file: {filename}\nRead failed: {e}"


def build_content_parts(prompt: str) -> List:
    content_parts = [prompt]

    memory_context = format_memory_context(prompt)
    if memory_context:
        content_parts.append("\n\n" + memory_context)

    cached = st.session_state.uploaded_file_cache
    if not cached:
        return content_parts

    filename = cached["name"]
    mime_type = cached["type"]
    file_bytes = cached["data"]
    ext = filename.lower().split(".")[-1] if "." in filename else ""

    if ext in ["xlsx", "xls"]:
        excel_text = excel_bytes_to_text(file_bytes, filename)
        content_parts.append(f"\n\n以下是使用者上傳的 Excel 內容摘要：\n{excel_text}")
    elif ext == "csv":
        csv_text = csv_bytes_to_text(file_bytes, filename)
        content_parts.append(f"\n\n以下是使用者上傳的 CSV 內容摘要：\n{csv_text}")
    elif ext == "txt":
        txt_text = text_bytes_to_text(file_bytes, filename)
        content_parts.append(f"\n\n以下是使用者上傳的文字檔內容：\n{txt_text}")
    elif ext in ["pdf", "png", "jpg", "jpeg"]:
        content_parts.append(
            {
                "mime_type": mime_type,
                "data": file_bytes,
            }
        )
    else:
        content_parts.append(
            f"\n\n使用者上傳了一個檔案：{filename}，但目前系統無法完整解析這個格式。"
        )

    return content_parts


# =========================
# AI Helpers
# =========================
def build_history_for_model(messages: List[Dict], limit: int = 12) -> List[Dict]:
    history = []
    filtered = [m for m in messages if m["role"] in ["user", "assistant"]]

    for m in filtered[-limit:]:
        content = m.get("content", "")
        if not content:
            continue
        role = "user" if m["role"] == "user" else "model"
        history.append({"role": role, "parts": [content]})

    return history


def get_candidate_models() -> List[str]:
    return [
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
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


def is_model_not_found(err_text: str) -> bool:
    t = err_text.lower()
    return (
        "404" in t
        or "not found" in t
        or "unsupported" in t
        or "is not supported" in t
    )


def generate_reply_with_key_rotation(
    history: List[Dict],
    content_parts: List,
) -> Tuple[str, Optional[str], Optional[str]]:
    last_error = None

    for key_idx, api_key in enumerate(API_KEY_LIST, start=1):
        genai.configure(api_key=api_key)

        for model_name in get_candidate_models():
            try:
                model = genai.GenerativeModel(model_name)

                for attempt in range(2):
                    try:
                        response = model.generate_content(
                            contents=history + [{"role": "user", "parts": content_parts}]
                        )
                        reply = getattr(response, "text", None)

                        if not reply:
                            reply = "⚠️ 龍蝦有收到問題，但這次模型沒有回傳文字內容。"

                        return reply, model_name, f"key-{key_idx}"

                    except Exception as e:
                        err_text = str(e)
                        last_error = err_text

                        if is_quota_error(err_text) and attempt == 0:
                            time.sleep(1.2)
                            continue

                        raise

            except Exception as e:
                err_text = str(e)
                last_error = err_text

                if is_quota_error(err_text):
                    continue

                if is_model_not_found(err_text):
                    continue

                continue

    if last_error and is_quota_error(last_error):
        return (
            "🦞 今天 AI 額度暫時用完了，請稍後再試，或新增更多 API key 輪替。",
            None,
            None,
        )

    return (
        f"⚠️ AI error: {last_error}" if last_error else "⚠️ AI 暫時無法回覆，請稍後再試。",
        None,
        None,
    )


def typewriter_effect(container, text: str, speed: float = 0.008) -> None:
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
# Header
# =========================
header_left, header_right = st.columns([6, 2])

with header_left:
    st.markdown(
        """
        <div class="lobster-appbar">
            <div class="lobster-title-wrap">
                <div class="lobster-title">🦞 龍蝦王助手</div>
                <div class="lobster-subtle">更精簡的手機版 Lobster</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with header_right:
    if st.button("＋ 新對話", use_container_width=True):
        sid = create_session("New Chat")
        st.session_state.active_chat_id = sid
        st.session_state.messages = []
        st.session_state.uploaded_file_cache = None
        st.session_state.rename_target = None
        st.session_state.rename_input = ""
        st.rerun()


# =========================
# Compact Tool Switcher
# =========================
tool_panel = st.radio(
    "工具列",
    ["收起", "Chats", "Upload", "Memory"],
    horizontal=True,
    key="tool_panel",
    label_visibility="collapsed",
)
st.markdown('<div class="toolbar-note">把工具收起來後，聊天區會更大。</div>', unsafe_allow_html=True)

if tool_panel != "收起":
    st.markdown('<div class="panel-shell">', unsafe_allow_html=True)

    # -------------------------
    # Chats
    # -------------------------
    if tool_panel == "Chats":
        st.markdown('<div class="panel-title">💬 Chats</div>', unsafe_allow_html=True)
        sessions = list_sessions()

        if not sessions:
            st.caption("目前沒有聊天紀錄")
        else:
            for s in sessions[:20]:
                session_id = s["id"]
                label = s["title"] or "New Chat"
                active = session_id == st.session_state.active_chat_id

                row1, row2 = st.columns([9, 1])

                with row1:
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

                with row2:
                    if st.button("⋯", key=f"more_{session_id}", use_container_width=True):
                        if st.session_state.rename_target == session_id:
                            st.session_state.rename_target = None
                            st.session_state.rename_input = ""
                        else:
                            st.session_state.rename_target = session_id
                            st.session_state.rename_input = label
                        st.rerun()

                if st.session_state.rename_target == session_id:
                    new_title = st.text_input(
                        "重新命名",
                        value=st.session_state.rename_input,
                        key=f"rename_input_{session_id}",
                        label_visibility="collapsed",
                        placeholder="輸入新名稱",
                    )
                    act1, act2, act3 = st.columns([1, 1, 1])

                    with act1:
                        if st.button("保存", key=f"rename_save_{session_id}", use_container_width=True):
                            rename_session(session_id, new_title)
                            st.session_state.rename_target = None
                            st.session_state.rename_input = ""
                            st.rerun()

                    with act2:
                        if st.button("刪除", key=f"delete_btn_{session_id}", use_container_width=True):
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
                            st.session_state.rename_input = ""
                            st.rerun()

                    with act3:
                        if st.button("取消", key=f"rename_cancel_{session_id}", use_container_width=True):
                            st.session_state.rename_target = None
                            st.session_state.rename_input = ""
                            st.rerun()

    # -------------------------
    # Upload
    # -------------------------
    elif tool_panel == "Upload":
        st.markdown('<div class="panel-title">📎 Upload</div>', unsafe_allow_html=True)

        uploaded_file = st.file_uploader(
            "Upload context",
            type=["txt", "pdf", "csv", "xlsx", "xls", "png", "jpg", "jpeg"],
            key="context_file",
            label_visibility="collapsed",
        )

        if uploaded_file is not None:
            st.session_state.uploaded_file_cache = {
                "name": uploaded_file.name,
                "type": uploaded_file.type,
                "data": uploaded_file.getvalue(),
            }
            st.success(f"已載入：{uploaded_file.name}")

        if st.session_state.uploaded_file_cache:
            st.caption(f"目前檔案：{st.session_state.uploaded_file_cache['name']}")
            if st.button("清除檔案", use_container_width=True):
                st.session_state.uploaded_file_cache = None
                st.rerun()

    # -------------------------
    # Memory
    # -------------------------
    elif tool_panel == "Memory":
        st.markdown('<div class="panel-title">🧠 Memory</div>', unsafe_allow_html=True)

        with st.expander("新增記憶", expanded=False):
            mem_title = st.text_input("記憶標題", key=f"mem_title_{st.session_state.memory_refresh_key}")
            mem_tags = st.text_input("標籤（逗號分隔）", key=f"mem_tags_{st.session_state.memory_refresh_key}")
            mem_content = st.text_area("記憶內容", height=110, key=f"mem_content_{st.session_state.memory_refresh_key}")

            if st.button("保存記憶", use_container_width=True):
                if mem_content.strip():
                    tags = [t.strip() for t in mem_tags.split(",")] if mem_tags.strip() else []
                    create_memory_item(
                        title=mem_title or mem_content[:30],
                        content=mem_content,
                        tags=tags,
                        source="manual",
                    )
                    st.session_state.memory_refresh_key += 1
                    st.rerun()

        memory_items = list_memory_items(limit=5)
        if not memory_items:
            st.caption("目前沒有長期記憶")
        else:
            for item in memory_items:
                st.markdown(
                    f"""
                    <div class="memory-box">
                        <div class="memory-title">{item.get('title', '')}</div>
                        <div class="memory-meta">{", ".join(item.get('tags', []) or [])}</div>
                        <div class="memory-body">{(item.get('content', '')[:72] + '...') if len(item.get('content', '')) > 72 else item.get('content', '')}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button("刪除這筆記憶", key=f"del_mem_{item['id']}", use_container_width=True):
                    delete_memory_item(item["id"])
                    st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

st.caption(f"API keys loaded: {len(API_KEY_LIST)}")


# =========================
# Main Chat Area
# =========================
st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
st.markdown("---")

if not st.session_state.messages:
    st.markdown(
        """
        <div class="chat-empty">
            <h2>今天想問龍蝦什麼？</h2>
            <div>上方工具列可以切換 Chats、Upload、Memory。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

for idx, msg in enumerate(st.session_state.messages):
    display_content = msg["content"]

    if msg["role"] == "assistant":
        if msg.get("status") == "pending":
            display_content = "🦞 龍蝦正在思考中..."
        elif msg.get("status") == "failed" and msg.get("error_message"):
            display_content = f"{msg['content']}\n\n> {msg['error_message']}"

    with st.chat_message("assistant" if msg["role"] == "assistant" else "user"):
        st.markdown(display_content)

        if msg["role"] == "assistant" and msg.get("status") == "completed":
            copy_key = f"copy_{msg.get('id', idx)}"
            if st.button("複製回答", key=copy_key):
                st.session_state.copy_notice = "請手動複製這段回答。"
                st.code(msg["content"], language=None)

if st.session_state.copy_notice:
    st.caption(st.session_state.copy_notice)


# =========================
# Chat Input
# =========================
prompt = st.chat_input("Message Lobster...")

if prompt:
    session_id = st.session_state.active_chat_id

    user_local = {
        "role": "user",
        "content": prompt,
        "status": "completed",
        "error_message": None,
    }
    st.session_state.messages.append(user_local)

    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        create_message(session_id, "user", prompt, status="completed")
        update_session_title_if_needed(session_id, prompt)
        touch_session(session_id)
    except Exception as e:
        st.warning(f"Save user message failed: {e}")

    pending_text = "🦞 龍蝦正在思考中..."
    pending_id = None

    try:
        pending_id = create_message(
            session_id,
            "assistant",
            pending_text,
            status="pending",
        )
    except Exception as e:
        st.warning(f"Create pending assistant message failed: {e}")

    pending_local = {
        "id": pending_id,
        "role": "assistant",
        "content": pending_text,
        "status": "pending",
        "error_message": None,
    }
    st.session_state.messages.append(pending_local)

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
                reply, used_model, used_key = generate_reply_with_key_rotation(
                    history, content_parts
                )

            final_status = "failed" if reply.startswith("⚠️") or reply.startswith("🦞 今天 AI 額度") else "completed"
            final_error = reply if final_status == "failed" else None

            output_placeholder = st.empty()
            thinking_placeholder.empty()

            if final_status == "failed":
                output_placeholder.markdown(reply)
            else:
                typewriter_effect(output_placeholder, reply, speed=0.008)
                if used_model and used_key:
                    st.caption(f"模型：{used_model} · {used_key}")

        except Exception as e:
            reply = f"⚠️ AI error: {e}"
            final_status = "failed"
            final_error = str(e)
            thinking_placeholder.markdown(reply)

    st.session_state.messages[-1] = {
        "id": pending_id,
        "role": "assistant",
        "content": reply,
        "status": final_status,
        "error_message": final_error,
    }

    try:
        if pending_id is not None:
            update_message(
                pending_id,
                content=reply,
                status=final_status,
                error_message=final_error,
            )
        else:
            create_message(
                session_id,
                "assistant",
                reply,
                status=final_status,
                error_message=final_error,
            )
        touch_session(session_id)
    except Exception as e:
        st.warning(f"Save assistant message failed: {e}")

    st.rerun()
