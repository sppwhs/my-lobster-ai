import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# 1. 初始化
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')
supabase = create_client(url, key)

# 2. 側邊欄邏輯
with st.sidebar:
    st.header("🦞 龍蝦選單")
    if st.button("➕ 開啟新對話", use_container_width=True):
        st.session_state.current_sid = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()
    
    st.write("---")
    try:
        # 撈取歷史紀錄清單
        resp = supabase.table("chat_history").select("session_id, content").order("created_at", descending=True).execute()
        sessions = {}
        for row in resp.data:
            sid = row.get("session_id")
            if sid and sid not in sessions:
                sessions[sid] = row["content"][:15] + "..."
        
        for sid, title in sessions.items():
            if st.button(f"💬 {title}", key=sid, use_container_width=True):
                st.session_state.current_sid = sid
                h_resp = supabase.table("chat_history").select("*").eq("session_id", sid).order("created_at").execute()
                st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in h_resp.data]
                st.rerun()
    except:
        pass

# 3. 主介面
st.title("🦞 龍蝦王助手")

if "messages" not in st.session_state: st.session_state.messages = []
if "current_sid" not in st.session_state: st.session_state.current_sid = str(uuid.uuid4())

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

# 4. 對話與強制存檔
if prompt := st.chat_input("跟龍蝦聊聊吧..."):
    # 先在螢幕顯示
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)
    
    # AI 回應
    try:
        response = model.generate_content(prompt)
        reply = response.text
        
        with st.chat_message("assistant"): st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        
        # 強制寫入資料庫 (分開寫，保證成功)
        supabase.table("chat_history").insert({"session_id": st.session_state.current_sid, "role": "user", "content": prompt}).execute()
        supabase.table("chat_history").insert({"session_id": st.session_state.current_sid, "role": "assistant", "content": reply}).execute()
        
    except Exception as e:
        st.error(f"⚠️ 發生錯誤：{e}")
