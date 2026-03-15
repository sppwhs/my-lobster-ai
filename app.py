import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ================= 1. 初始化 (Gemini 2.5) =================
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')
supabase = create_client(url, key)

# ================= 2. 極簡 UI 配置 =================
st.set_page_config(
    page_title="Lobster AI", 
    page_icon="🦞", 
    layout="wide", # 寬螢幕模式
    initial_sidebar_state="collapsed" # 手機版預設收起，保持清爽
)

# 注入 CSS：打造 ChatGPT 風格 (深色質感、隱藏多餘 UI)
st.markdown("""
    <style>
    /* 隱藏 Streamlit 原生元素 */
    #MainMenu, footer, header {visibility: hidden;}
    .stApp {max-width: 800px; margin: 0 auto;} /* 限制寬度，對話更集中 */
    
    /* 側邊欄樣式優化 */
    section[data-testid="stSidebar"] {background-color: #f9f9f9;}
    .stButton>button {border-radius: 20px; border: 1px solid #ddd; transition: 0.3s;}
    .stButton>button:hover {border-color: #FF4B4B; color: #FF4B4B;}
    
    /* 輸入框美化 */
    .stChatInputContainer {padding-bottom: 20px;}
    </style>
    """, unsafe_allow_html=True)

# ================= 3. 側邊欄 (隱藏式選單) =================
with st.sidebar:
    st.title("🦞 Lobster")
    
    if "current_sid" not in st.session_state:
        st.session_state.current_sid = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if st.button("➕ New Chat", use_container_width=True):
        st.session_state.current_sid = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()
    
    st.write("---")
    # 歷史紀錄清單
    try:
        resp = supabase.table("chat_history").select("session_id, content, role").order("created_at", descending=True).limit(40).execute()
        sessions = {}
        for row in resp.data:
            sid = row.get("session_id")
            if sid and sid not in sessions and row["role"] == "user":
                sessions[sid] = row["content"][:15] + "..."
        
        for sid, title in sessions.items():
            if st.button(f"💬 {title}", key=f"h_{sid}", use_container_width=True):
                st.session_state.current_sid = sid
                h_resp = supabase.table("chat_history").select("*").eq("session_id", sid).order("created_at").execute()
                st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in h_resp.data]
                st.rerun()
    except:
        pass

    st.write("---")
    uploaded_file = st.file_uploader("Upload context", type=["pdf", "txt", "csv", "xlsx", "png", "jpg", "jpeg"])

# ================= 4. 主畫面 (對話流) =================
# 只有對話，沒有多餘的標題或 Caption
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ================= 5. 輸入邏輯 =================
if prompt := st.chat_input("Message Lobster..."):
    # 顯示 User
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    try:
        # 準備請求
        content_parts = [prompt]
        if uploaded_file:
            content_parts.append({"mime_type": uploaded_file.type, "data": uploaded_file.read()})

        # 獲取 AI 回應 (ChatGPT 風格不顯示中途提示)
        response = model.generate_content(content_parts)
        reply = response.text
        
        with st.chat_message("assistant"):
            st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        
        # 背景存檔
        supabase.table("chat_history").insert([
            {"session_id": st.session_state.current_sid, "role": "user", "content": prompt},
            {"session_id": st.session_state.current_sid, "role": "assistant", "content": reply}
        ]).execute()
            
    except Exception as e:
        if "429" in str(e):
            st.error("Too many requests. Please wait a moment.")
