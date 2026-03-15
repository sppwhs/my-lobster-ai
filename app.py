import streamlit as st
import google.generativeai as genai
import os

# 1. 核心設定
api_key = os.environ.get("GOOGLE_API_KEY")
genai.configure(api_key=api_key)
# 使用剛才診斷出的最新型號，若失效則自動換回 1.5
try:
    model = genai.GenerativeModel('gemini-2.5-flash')
except:
    model = genai.GenerativeModel('gemini-1.5-flash')

st.set_page_config(page_title="龍蝦 AI 助手", page_icon="🦞")
st.title("🦞 龍蝦 AI 助手")

# 2. 記憶初始化
if "messages" not in st.session_state:
    st.session_state.messages = []

# 顯示歷史訊息
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 3. 聊天邏輯 (簡化版，確保不閃神)
if prompt := st.chat_input("跟龍蝦說說話吧！"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            # 這次不使用 start_chat，直接用 generate_content 確保連線最穩
            response = model.generate_content(prompt)
            st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
        except Exception as e:
            st.error(f"龍蝦還在調整呼吸... 請再試一次！(錯誤: {e})")
