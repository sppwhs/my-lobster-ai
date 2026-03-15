import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ================= 1. 初始化 (鎖定 2.5) =================
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

genai.configure(api_key=api_key)
# 絕不再換，固定使用 2.5
model = genai.GenerativeModel('gemini-2.5-flash')
supabase = create_client(url, key)

# ================= 2. 側邊欄 (固定顯示 + 功能全開) =================
with st.sidebar:
    st.header("🦞 龍蝦選單")
    if st.button("➕ 開啟新對話", use_container_width=True):
        st.session_state.current_sid = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()
    
    st.write("---")
    st.subheader("➕ 夾帶檔案分析")
    uploaded_file = st.file_uploader("支援圖片、PDF、CSV 等", type=["pdf", "txt", "csv", "xlsx", "png", "jpg", "jpeg"])
    
    st.write("---")
    st.subheader("📁 歷史紀錄")
    try:
        resp = supabase.table("chat_history").select("session_id, content").order("created_at", descending=True).execute()
        sessions = {}
        for row in resp.data:
            sid = row.get("session_id")
            if sid and sid not in sessions:
                sessions[sid] = row["content"][:15] + "..."
        
        for sid, title in sessions.items():
            col1, col2 = st.columns([4, 1])
            with col1:
                if st.button(f"💬 {title}", key=f"s_{sid}", use_container_width=True):
                    st.session_state.current_sid = sid
                    h_resp = supabase.table("chat_history").select("*").eq("session_id", sid).order("created_at").execute()
                    st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in h_resp.data]
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"d_{sid}"):
                    supabase.table("chat_history").delete().eq("session_id", sid).execute()
                    st.rerun()
    except:
        st.write("連線紀錄中...")

# ================= 3. 主畫面 =================
st.set_page_config(page_title="龍蝦王小助手", page_icon="🦞")
st.title("🦞 龍蝦王小助手")

if "messages" not in st.session_state: st.session_state.messages = []
if "current_sid" not in st.session_state: st.session_state.current_sid = str(uuid.uuid4())

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

# ================= 4. 對話邏輯 =================
if prompt := st.chat_input("跟龍蝦聊聊吧..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)
    
    try:
        content_parts = [prompt]
        if uploaded_file:
            content_parts.append({"mime_type": uploaded_file.type, "data": uploaded_file.read()})
            st.info("📎 檔案已讀取，龍蝦思考中...")

        # AI 回應
        response = model.generate_content(content_parts)
        reply = response.text
        
        with st.chat_message("assistant"): st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        
        # 背景存檔
        supabase.table("chat_history").insert({"session_id": st.session_state.current_sid, "role": "user", "content": prompt}).execute()
        supabase.table("chat_history").insert({"session_id": st.session_state.current_sid, "role": "assistant", "content": reply}).execute()
        
    except Exception as e:
        if "429" in str(e):
            st.error("⚠️ Google 暫時忙碌 (429)，請稍等 30 秒後點擊右方箭頭重試。")
        else:
            st.error(f"⚠️ 發生小錯誤：{e}")

st.markdown("<style>#MainMenu, footer, header {visibility: hidden;}</style>", unsafe_allow_html=True)
