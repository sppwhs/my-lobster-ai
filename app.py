import streamlit as st
import google.generativeai as genai
import os
from supabase import create_client

# 1. 初始化連線
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')
supabase = create_client(url, key)

st.set_page_config(page_title="永恆龍蝦", page_icon="🦞")
st.title("🦞 擁有永恆記憶的龍蝦")

# 2. 從資料庫讀取歷史紀錄
if "messages" not in st.session_state:
    try:
        # 從名為 'chat_history' 的表格抓取資料
        response = supabase.table("chat_history").select("*").order("created_at").execute()
        st.session_state.messages = [{"role": row["role"], "content": row["content"]} for row in response.data]
    except:
        st.session_state.messages = []

# 顯示對話
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 3. 聊天與自動存檔
if prompt := st.chat_input("跟我說說話，我會永遠記得..."):
    # 存入畫面
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 存入資料庫
    supabase.table("chat_history").insert({"role": "user", "content": prompt}).execute()

    with st.chat_message("assistant"):
        chat = model.start_chat(history=[])
        response = chat.send_message(prompt)
        full_response = response.text
        st.markdown(full_response)
        
        # 存入畫面與資料庫
        st.session_state.messages.append({"role": "assistant", "content": full_response})
        supabase.table("chat_history").insert({"role": "assistant", "content": full_response}).execute()
