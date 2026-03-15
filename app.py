import streamlit as st
import google.generativeai as genai
import os

# 從系統環境變數讀取，這才是專業且安全的做法
api_key = os.environ.get("GOOGLE_API_KEY")

if api_key:
    genai.configure(api_key=api_key)
    # 根據剛才診斷的結果，使用 2.5 版本
    model = genai.GenerativeModel('gemini-2.5-flash')
else:
    st.error("環境變數中找不到 GOOGLE_API_KEY")

st.set_page_config(page_title="龍蝦 AI 助手", page_icon="🦞")
st.title("🦞 龍蝦 AI 助手")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("這次絕對安全了！"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            # 簡化歷史紀錄格式確保穩定
            chat = model.start_chat(history=[])
            response = chat.send_message(prompt)
            st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
        except Exception as e:
            st.error(f"龍蝦還在調整呼吸... 請再試一次！(錯誤: {e})")
