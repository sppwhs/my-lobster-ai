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

# ================= 2. 介面配置 (恢復最穩定的手機模式) =================
st.set_page_config(
    page_title="Lobster AI", 
    page_icon="🦞", 
    initial_sidebar_state="expanded" # 強制展開，不讓它躲起來
)

# 隱藏多餘 UI，但保留核心結構
st.markdown("<style>#MainMenu, footer, header {visibility: hidden;}</style>", unsafe_allow_html=True)

# ================= 3. 側邊欄 (回歸最簡單的寫法，保證內容顯示) =================
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
    
    # 檔案上傳
    uploaded_file = st.file_uploader("Upload context", type=["pdf", "txt", "csv", "xlsx", "png", "jpg", "jpeg"])
    
    st.write("---")
    st.subheader("History")
    
    # 歷史紀錄
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
        st.write("Loading history...")

# ================= 4. 主畫面 =================
st.title("🦞 龍蝦王助手")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ================= 5. 對話觸發 =================
if prompt := st.chat_input("Message Lobster..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    try:
        content_parts = [prompt]
        if uploaded_file:
            content_parts.append({"mime_type": uploaded_file.type, "data": uploaded_file.read()})

        response = model.generate_content(content_parts)
        reply = response.text
        
        with st.chat_message("assistant"):
            st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        
        # 存檔
        supabase.table("chat_history").insert([
            {"session_id": st.session_state.current_sid, "role": "user", "content": prompt},
            {"session_id": st.session_state.current_sid, "role": "assistant", "content": reply}
        ]).execute()
            
    except Exception as e:
        if "429" in str(e):
            st.error("Too many requests. Please wait a moment.")
        else:
            st.error(f"Error: {e}")
