import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ================= 1. 安全初始化 =================
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')
supabase = create_client(url, key)

# ================= 2. 側邊欄：強制穩定載入 =================
with st.sidebar:
    st.header("🦞 龍蝦選單")
    
    # 初始化 session 變數 (避免閃退)
    if "current_sid" not in st.session_state:
        st.session_state.current_sid = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # 1. 開啟新對話按鈕
    if st.button("➕ 開啟新對話", use_container_width=True):
        st.session_state.current_sid = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()
    
    st.write("---")
    st.subheader("📁 歷史紀錄")
    
    # 2. 讀取主題 (加上防錯，避免讀取失敗導致側邊欄消失)
    try:
        resp = supabase.table("chat_history").select("session_id, content, role").order("created_at", descending=True).limit(50).execute()
        sessions = {}
        for row in resp.data:
            sid = row.get("session_id")
            if sid and sid not in sessions and row["role"] == "user":
                sessions[sid] = row["content"][:12] + "..."
        
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
        st.write("⚠️ 正在嘗試連接記憶庫...")

# ================= 3. 主畫面介面 =================
st.set_page_config(page_title="龍蝦王助手", page_icon="🦞")
st.title("🦞 龍蝦王助手")

# 顯示目前的對話內容
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ================= 4. 對話觸發 (穩健存檔與回應) =================
if prompt := st.chat_input("跟龍蝦聊聊吧..."):
    # 顯示並存入畫面
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 存入資料庫
    try:
        supabase.table("chat_history").insert({"session_id": st.session_state.current_sid, "role": "user", "content": prompt}).execute()
        
        # 獲取回應
        with st.chat_message("assistant"):
            response = model.generate_content(prompt)
            reply = response.text
            st.markdown(reply)
            
            # 存入紀錄
            st.session_state.messages.append({"role": "assistant", "content": reply})
            supabase.table("chat_history").insert({"session_id": st.session_state.current_sid, "role": "assistant", "content": reply}).execute()
            
    except Exception as e:
        if "429" in str(e):
            st.error("⚠️ 龍蝦說太快累了，請等 30 秒後重新發送。")
        else:
            st.error(f"⚠️ 發生錯誤：{e}")

# 隱藏 Streamlit 預設介面
st.markdown("<style>#MainMenu, footer, header {visibility: hidden;}</style>", unsafe_allow_html=True)
