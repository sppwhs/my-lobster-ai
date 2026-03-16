import os
import uuid
import time
from io import BytesIO
from datetime import datetime, timezone

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

st.markdown("""
<style>
#MainMenu, footer, header { visibility:hidden; }
section[data-testid="stSidebar"] { display:none !important; }

.block-container{
    padding-top:1rem;
    padding-bottom:1rem;
    max-width:850px;
}

.lobster-title{ font-size:1.2rem; font-weight:800; margin:0; color: #1f2937; }
.lobster-sub{ font-size:0.8rem; color:#6b7280; margin-bottom: 1rem; }

.stButton>button {
    border-radius:12px;
    transition: all 0.2s;
}
.stButton>button:hover {
    border-color: #ff4b4b;
    color: #ff4b4b;
}
</style>
""", unsafe_allow_html=True)

# =========================
# ENV & Clients
# =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
GOOGLE_KEY = os.getenv("GOOGLE_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY or not GOOGLE_KEY:
    st.error("環境變數缺失，請檢查 API Key 設定。")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GOOGLE_KEY)

# =========================
# Session State Initialization
# =========================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "chat_id" not in st.session_state:
    st.session_state.chat_id = str(uuid.uuid4())

# =========================
# Header UI
# =========================
c1, c2 = st.columns([6, 2])

with c1:
    st.markdown("""
    <div class="lobster-title">🦞 龍蝦王助手</div>
    <div class="lobster-sub">您的專屬智能開發與生活夥伴</div>
    """, unsafe_allow_html=True)

with c2:
    if st.button("＋ 開啟新對話", use_container_width=True):
        st.session_state.messages = []
        st.session_state.chat_id = str(uuid.uuid4())
        st.rerun()

# =========================
# Tabs / Tools Switch
# =========================
tool = st.radio(
    "",
    ["收起", "歷史對話", "檔案上傳", "長期記憶"],
    horizontal=True,
    label_visibility="collapsed"
)

# --- 歷史對話 ---
if tool == "歷史對話":
    st.write("### 最近的對話")
    try:
        rows = supabase.table("lobster_sessions").select("*").order("updated_at", desc=True).limit(20).execute().data
        if not rows:
            st.info("尚無對話紀錄")
        for r in rows:
            btn_label = f"💬 {r['title'] if r['title'] else '未命名對話'}"
            if st.button(btn_label, key=r["id"], use_container_width=True):
                st.session_state.chat_id = r["id"]
                msgs = supabase.table("lobster_messages").select("*").eq("session_id", r["id"]).order("created_at").execute().data
                st.session_state.messages = [{"role": m["role"], "content": m["content"]} for m in msgs]
                st.rerun()
    except Exception as e:
        st.error(f"讀取紀錄失敗: {e}")

# --- 檔案上傳 ---
elif tool == "檔案上傳":
    file = st.file_uploader("上傳文件供 AI 分析", type=["txt", "pdf", "csv", "xlsx"])
    if file:
        data = file.read()
        st.session_state.file = {"name": file.name, "data": data}
        st.success(f"✅ 已讀取檔案: {file.name}")

# --- 長期記憶 ---
elif tool == "長期記憶":
    m_title = st.text_input("記憶標題 (例如：交易策略、家庭活動)")
    m_content = st.text_area("詳細內容")
    if st.button("永久保存到記憶庫"):
        if m_title and m_content:
            supabase.table("memory_items").insert({"title": m_title, "content": m_content}).execute()
            st.success("記憶已存檔，未來的對話將可引用。")
        else:
            st.warning("請填寫標題與內容")

st.divider()

# =========================
# Chat Display
# =========================
if not st.session_state.messages:
    st.markdown("""
    <div style="text-align:center; padding:3rem; color:#9ca3af">
        <h2>今天有什麼想聊的嗎？</h2>
        <p>我可以幫你優化程式、分析策略或計劃行程。</p>
    </div>
    """, unsafe_allow_html=True)

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# =========================
# Chat Input & AI Engine
# =========================
prompt = st.chat_input("輸入您的問題...")

if prompt:
    # 1. 顯示與存儲 User 訊息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. AI 配置與安全設定 (避免被拒絕)
    safe_config = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
    # 使用目前最穩定的 2.0 Flash
    model = genai.GenerativeModel("gemini-2.0-flash", safety_settings=safe_config)

    # 3. Assistant 串流回應
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""
        
        try:
            # 開啟串流
            response_stream = model.generate_content(prompt, stream=True)
            for chunk in response_stream:
                full_response += chunk.text
                placeholder.markdown(full_response + "▌") # 模擬打字中
            placeholder.markdown(full_response)
        except Exception as e:
            st.error(f"發生錯誤: {e}")
            full_response = "對不起，目前無法處理您的請求。"
            placeholder.markdown(full_response)

    # 4. 更新 Session State
    st.session_state.messages.append({"role": "assistant", "content": full_response})

    # 5. 資料庫異步同步 (先寫入 Session 確保關聯完整)
    try:
        # A. 確保 Session 存在
        session_exists = supabase.table("lobster_sessions").select("id").eq("id", st.session_state.chat_id).execute()
        if not session_exists.data:
            # 第一次對話，生成標題並建立 Session
            title_gen = model.generate_content(f"將此問題摘要成5字內標題：{prompt}").text.strip()
            supabase.table("lobster_sessions").insert({
                "id": st.session_state.chat_id, 
                "title": title_gen
            }).execute()
        
        # B. 批次寫入 User 與 Assistant 訊息
        msg_payload = [
            {"session_id": st.session_state.chat_id, "role": "user", "content": prompt},
            {"session_id": st.session_state.chat_id, "role": "assistant", "content": full_response}
        ]
        supabase.table("lobster_messages").insert(msg_payload).execute()
    except Exception as db_err:
        st.warning(f"訊息已顯示，但存檔至資料庫時失敗: {db_err}")
