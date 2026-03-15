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
# 使用你帳號目前最通暢的型號
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    system_instruction="你是一隻博學多聞且幽默的龍蝦小助理。你對高爾夫球、台灣期指交易、電動車非常了解。說話風格簡潔、精準，偶爾會帶一點點幽默感，稱呼使用者為『老大』。"
)
supabase = create_client(url, key)

st.set_page_config(page_title="龍蝦王小助手", page_icon="🦞")

# 把 st.title 換成這兩行，龍蝦會更大更有氣勢
st.write(f"<h1>🦞 龍蝦王小助手</h1>", unsafe_allow_html=True)
st.caption("您的專屬永恆記憶助手")
st.markdown("---") # 加一條分隔線會更有質感
# -------------------------

# --- 側邊欄：歷史紀錄與下載 ---
with st.sidebar:
    st.title("🦞 龍蝦對話錄")
    if st.button("➕ 開啟新對話", use_container_width=True):
        st.session_state.current_session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.subheader("📜 歷史紀錄")
    try:
        sessions = supabase.table("chat_history").select("session_id, title").execute()
        unique_sessions = {s['session_id']: s['title'] for s in sessions.data if s.get('title')}.items()
        for s_id, s_title in reversed(list(unique_sessions)):
            if st.button(f"💬 {s_title[:12]}...", key=s_id, use_container_width=True):
                st.session_state.current_session_id = s_id
                res = supabase.table("chat_history").select("*").eq("session_id", s_id).order("created_at").execute()
                st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in res.data]
                st.rerun()
    except:
        st.write("尚無紀錄")
    
    # 導出當前對話按鈕
    if st.session_state.get("messages"):
        st.divider()
        chat_text = "\n\n".join([f"{'主理人' if m['role']=='user' else '龍蝦'}: {m['content']}" for m in st.session_state.messages])
        st.download_button("📥 導出全文 (.txt)", chat_text, file_name="lobster_chat.txt", use_container_width=True)

# --- 主畫面 ---
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

# 顯示對話與複製功能
for i, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        # 如果是 AI 的回覆，提供複製按鈕
        if message["role"] == "assistant":
            st.button(f"📋 複製內容", key=f"copy_{i}", on_click=lambda c=message["content"]: st.write(f"已選取內容，請手動複製"))

# 聊天輸入
if prompt := st.chat_input("跟龍蝦聊聊吧..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 處理標題與存檔
    is_new = len(st.session_state.messages) == 1
    title = prompt[:20] if is_new else None
    supabase.table("chat_history").insert({"role": "user", "content": prompt, "session_id": st.session_state.current_session_id, "title": title}).execute()

    with st.chat_message("assistant"):
        history = [{"role": "user" if m["role"]=="user" else "model", "parts": [m["content"]]} for m in st.session_state.messages[:-1]]
        chat = model.start_chat(history=history)
        response = chat.send_message(prompt)
        st.markdown(response.text)
        
        # 存檔助理回覆
        supabase.table("chat_history").insert({"role": "assistant", "content": response.text, "session_id": st.session_state.current_session_id, "title": title}).execute()
        st.session_state.messages.append({"role": "assistant", "content": response.text})
