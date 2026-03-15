import streamlit as st
import google.generativeai as genai
import os
from supabase import create_client

# --- 1. 初始化與安全設定 (保持不變) ---
google_api_key = os.environ.get("GOOGLE_API_KEY")
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")

if not all([google_api_key, supabase_url, supabase_key]):
    st.error("❌ 系統配置不足")
    st.stop()

genai.configure(api_key=google_api_key)
model = genai.GenerativeModel('gemini-2.5-flash')
supabase = create_client(supabase_url, supabase_key)

# --- 2. 介面配置 ---
st.set_page_config(page_title="龍蝦王小助手", page_icon="🦞")
st.write("<h1>🦞 龍蝦王小助手</h1>", unsafe_allow_html=True)
st.caption("您的專屬永恆記憶助手")
st.markdown("---")

# --- 3. 記憶讀取 ---
if "messages" not in st.session_state:
    try:
        response = supabase.table("chat_history").select("*").order("created_at").execute()
        st.session_state.messages = [{"role": row["role"], "content": row["content"]} for row in response.data]
    except:
        st.session_state.messages = []

# 顯示對話歷史
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- 4. 檔案與對話區塊 (修復核心) ---
# 使用 st.container 確保輸入框在最下面
container = st.container()

with container:
    with st.expander("➕ 夾帶檔案 (圖片、PDF)"):
        uploaded_file = st.file_uploader("選取檔案", type=["pdf", "txt", "png", "jpg", "jpeg"], label_visibility="collapsed")
    
    # 使用 chat_input 並加上 key 確保狀態獨立
    if prompt := st.chat_input("跟龍蝦聊聊吧...", key="lobster_input"):
        # 顯示使用者文字
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # 存入資料庫
        try:
            supabase.table("chat_history").insert({"role": "user", "content": prompt}).execute()
        except: pass

        # 龍蝦回答
        with st.chat_message("assistant"):
            try:
                content_to_send = [prompt]
                if uploaded_file:
                    file_bytes = uploaded_file.read()
                    content_to_send.append({"mime_type": uploaded_file.type, "data": file_bytes})
                    st.toast(f"📎 正在分析：{uploaded_file.name}")

                response = model.generate_content(content_to_send)
                full_response = response.text
                st.markdown(full_response)
                
                # 存檔
                st.session_state.messages.append({"role": "assistant", "content": full_response})
                supabase.table("chat_history").insert({"role": "assistant", "content": full_response}).execute()
            except Exception as e:
                st.error(f"龍蝦斷片了：{e}")

# --- 5. 隱藏預設元件 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)
