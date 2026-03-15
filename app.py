import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ================= 1. 安全初始化 =================
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')

# 嘗試連線
try:
    supabase = create_client(url, key)
    # 測試連線是否真的通了
    test_resp = supabase.table("chat_history").select("count", count="exact").limit(1).execute()
    db_status = "✅ 資料庫連線正常"
except Exception as e:
    db_status = f"❌ 資料庫連線失敗: {e}"

# ================= 2. 介面與側邊欄 =================
st.set_page_config(page_title="龍蝦助手", page_icon="🦞")
st.title("🦞 龍蝦助手 (穩定診斷版)")

with st.sidebar:
    st.info(db_status) # 這裡會顯示到底連不連得通
    if st.button("➕ 開啟新對話"):
        st.session_state.current_sid = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()
    
    st.write("---")
    # 讀取主題清單
    try:
        resp = supabase.table("chat_history").select("session_id, content, role").order("created_at", descending=True).limit(50).execute()
        sessions = {}
        for row in resp.data:
            sid = row.get("session_id")
            if sid and sid not in sessions and row["role"] == "user":
                sessions[sid] = row["content"][:12] + "..."
        for sid, title in sessions.items():
            if st.button(f"💬 {title}", key=sid, use_container_width=True):
                st.session_state.current_sid = sid
                h_resp = supabase.table("chat_history").select("*").eq("session_id", sid).order("created_at").execute()
                st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in h_resp.data]
                st.rerun()
    except:
        pass

# ================= 3. 聊天與存檔 =================
if "messages" not in st.session_state: st.session_state.messages = []
if "current_sid" not in st.session_state: st.session_state.current_sid = str(uuid.uuid4())

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

if prompt := st.chat_input("輸入訊息..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # 嘗試存檔
    try:
        supabase.table("chat_history").insert({"session_id": st.session_state.current_sid, "role": "user", "content": prompt}).execute()
        response = model.generate_content(prompt)
        reply = response.text
        st.chat_message("assistant").markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        supabase.table("chat_history").insert({"session_id": st.session_state.current_sid, "role": "assistant", "content": reply}).execute()
    except Exception as e:
        st.error(f"操作失敗: {e}")
