import streamlit as st
import google.generativeai as genai
import os

# 從雲端環境變數抓取 Key，安全又專業
api_key = os.environ.get("GOOGLE_API_KEY")
genai.configure(api_key="AIzaSyAKW7Nis9FXhN4Gcez0ClnEd5LiD4zJ8VA")
model = genai.GenerativeModel('gemini-1.5-flash-latest')

st.set_page_config(page_title="龍蝦 AI 助手", page_icon="🦞")
st.title("🦞 龍蝦 AI：您的專屬助手")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("今天想聊什麼？"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            history = [{"role": "user" if m["role"]=="user" else "model", "parts": [m["content"]]} for m in st.session_state.messages[:-1]]
            chat = model.start_chat(history=history)
            response = chat.send_message(prompt)
            st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
        except Exception as e:
            st.error(f"龍蝦目前忙碌中，請稍後再試。")
