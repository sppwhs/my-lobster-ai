import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# 1. 基礎設定
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

genai.configure(api_key=api_key)
# 根據你的權限，使用最穩定的型號
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    system_instruction="你是一隻博學多聞且幽默的龍蝦助理。你對高爾夫球、台灣期指交易、特斯拉電動車非常了解。說話風格簡潔、精準，偶爾會帶一點點幽默感，稱呼使用者為『老大』。"
)
supabase = create_client(url, key)

st.set_page_config(page_title="龍蝦旗艦版", page_icon="🦞", layout="wide")

# --- 側邊欄邏輯 ---
with st.sidebar:
    st.title("🦞 龍蝦對話錄")
    if st.button("➕ 開啟新對話"):
        st.session_state.current_session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.subheader("歷史紀錄")
    # 從資料庫抓取不重複的對話清單
    try:
        sessions = supabase.table("chat_history").select("session_id, title").execute()
        # 去重處理
        unique_sessions = {s['session_id']: s['title'] for s in sessions.data if s.get('title')}.items()
        for s_id, s_title in reversed(list(unique_sessions)):
            if st.button(f"💬 {s_title[:15]}...", key=s_id):
                st.session_state.current_session_id = s_id
                # 切換 session 時重新抓取該 session 的訊息
                res = supabase.table("chat_history").select("*").eq("session_id", s_id).order("created_at").execute()
                st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in res.data]
                st.rerun()
    except:
        st.write("尚無歷史紀錄")

# --- 主畫面邏輯 ---
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

st.title("🦞 龍蝦助理")

# 顯示當前對話
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 聊天輸入
if prompt := st.chat_input("今天想聊什麼主題？"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 如果是第一句話，產生標題
    is_new_session = len(st.session_state.messages) == 1
    session_title = prompt[:20] if is_new_session else None

    # 存入資料庫
    supabase.table("chat_history").insert({
        "role": "user", 
        "content": prompt, 
        "session_id": st.session_state.current_session_id,
        "title": session_title
    }).execute()

    with st.chat_message("assistant"):
        # 抓取該 session 的歷史脈絡餵給 AI
        history = [{"role": "user" if m["role"]=="user" else "model", "parts": [m["content"]]} for m in st.session_state.messages[:-1]]
        chat = model.start_chat(history=history)
        response = chat.send_message(prompt)
        
        st.markdown(response.text)
        
        # 存入資料庫
        supabase.table("chat_history").insert({
            "role": "assistant", 
            "content": response.text, 
            "session_id": st.session_state.current_session_id,
            "title": session_title
        }).execute()
        st.session_state.messages.append({"role": "assistant", "content": response.text})
