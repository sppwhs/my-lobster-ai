import streamlit as st
import google.generativeai as genai
import os

# 1. 核心設定
api_key = os.environ.get("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    # 使用你目前最穩定的 2.5 版本
    model = genai.GenerativeModel('gemini-2.5-flash')
else:
    st.error("環境變數中找不到 GOOGLE_API_KEY")

st.set_page_config(page_title="龍蝦 AI 助手", page_icon="🦞")
st.title("🦞 龍蝦 AI 助手")

# 2. 初始化記憶體 (Session State)
if "messages" not in st.session_state:
    st.session_state.messages = []

# 3. 顯示對話歷史 (讓你在網頁上看到過去的對話)
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. 聊天邏輯
if prompt := st.chat_input("跟龍蝦聊聊吧！"):
    # 紀錄你的話
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            # 【關鍵】將歷史訊息格式化，傳送給大腦
            # 將 streamlit 的格式轉換為 Google Gemini 需要的格式
            history_for_api = []
            for m in st.session_state.messages[:-1]:
                role = "user" if m["role"] == "user" else "model"
                history_for_api.append({"role": role, "parts": [m["content"]]})
            
            # 帶著記憶開始對話
            chat = model.start_chat(history=history_for_api)
            response = chat.send_message(prompt)
            
            # 顯示並紀錄龍蝦的回覆
            st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
            
        except Exception as e:
            st.error(f"龍蝦暫時斷片了... (錯誤: {e})")
