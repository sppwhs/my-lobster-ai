import streamlit as st
import google.generativeai as genai
import os

# 1. 初始化設定
api_key = os.environ.get("GOOGLE_API_KEY")
st.set_page_config(page_title="龍蝦 AI：自動修復版", page_icon="🦞")
st.title("🦞 龍蝦 AI：大腦自動匹配中")

if not api_key:
    st.error("❌ 找不到 API Key，請檢查 Render 設定。")
    st.stop()

genai.configure(api_key=api_key)

# 2. 自動偵測可用大腦 (核心邏輯)
@st.cache_resource
def get_working_model():
    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    
    # 定義我們心目中的大腦順位
    preferences = [
        'models/gemini-1.5-flash',
        'models/gemini-1.5-flash-latest',
        'models/gemini-pro',
        'models/gemini-1.0-pro'
    ]
    
    # 開始面試
    for pref in preferences:
        if pref in available_models:
            try:
                m = genai.GenerativeModel(pref)
                m.generate_content("Hi") # 試探性問候
                return m, pref
            except:
                continue
    
    # 如果順位都失敗，隨便抓一個能用的
    if available_models:
        return genai.GenerativeModel(available_models[0]), available_models[0]
    return None, None

# 3. 啟動大腦
model, model_name = get_working_model()

if model:
    st.success(f"✅ 龍蝦已上線！目前使用大腦：{model_name}")
else:
    st.error("❌ 找不到任何可用的大腦，請確認 API Key 是否已啟用 Gemini API 權限。")
    st.stop()

# 4. 聊天邏輯 (與之前相同)
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("跟我說說話吧！"):
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
            st.error(f"龍蝦暫時短路了：{e}")
