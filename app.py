import streamlit as st
import google.generativeai as genai
import os

# 1. 設定大腦：使用診斷系統幫我們找到的正確型號
api_key = os.environ.get("GOOGLE_API_KEY")
genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')

st.set_page_config(page_title="龍蝦 AI 助手", page_icon="🦞")
st.title("🦞 龍蝦 AI 助手")

if "messages" not in st.session_state:
    st.session_state.messages = []

# 顯示對話歷史
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 聊天邏輯
if prompt := st.chat_input("跟龍蝦說說話吧！"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            # 打包歷史紀錄，讓牠有記憶
            history = [{"role": "user" if m["role"]=="user" else "model", "parts": [m["content"]]} for m in st.session_state.messages[:-1]]
            chat = model.start_chat(history=history)
            response = chat.send_message(prompt)
            
            st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
        except Exception as e:
            st.error("龍蝦稍微閃神了，請再試一次！")
