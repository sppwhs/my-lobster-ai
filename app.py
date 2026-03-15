import streamlit as st
import google.generativeai as genai
import os
import sys

# 診斷資訊：檢查環境變數是否真的有讀到
api_key = os.environ.get("GOOGLE_API_KEY")

st.set_page_config(page_title="龍蝦診斷中", page_icon="🦞")
st.title("🦞 龍蝦自我診斷系統")

if not api_key:
    st.error("❌ 診斷結果：Render 保險箱裡找不到 GOOGLE_API_KEY！請檢查 Environment 頁面。")
else:
    st.success("✅ 診斷結果：已成功讀取到 API Key (開頭為: " + api_key[:5] + "...)")

try:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("輸入測試文字..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            # 這裡不使用 try-except 隱藏錯誤，讓它直接噴出來
            history = [{"role": "user" if m["role"]=="user" else "model", "parts": [m["content"]]} for m in st.session_state.messages[:-1]]
            chat = model.start_chat(history=history)
            response = chat.send_message(prompt)
            st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})

except Exception as e:
    # 這裡會顯示真正的錯誤原因
    st.error(f"❌ 龍蝦崩潰原因：{type(e).__name__}")
    st.code(str(e))
