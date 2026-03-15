import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ================= 1. 初始化設定 (鎖定 2.5) =================
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')
supabase = create_client(url, key)

# ================= 2. 頁面配置 (強制展開側邊欄) =================
st.set_page_config(
    page_title="龍蝦王助手", 
    page_icon="🦞", 
    initial_sidebar_state="expanded" # 強制在手機版也展開側邊欄
)

# 隱藏 Streamlit 預設介面與頁首頁尾
st.markdown("<style>#MainMenu, footer, header {visibility: hidden;}</style>", unsafe_allow_html=True)

# ================= 3. 側邊欄核心功能 =================
with st.sidebar:
    st.header("🦞 龍蝦選單")
    
    # 初始化 Session 變數
    if "current_sid" not in st.session_state:
        st.session_state.current_sid = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # 按鈕：開啟新對話
    if st.button("➕ 開啟新對話", use_container_width=True):
        st.session_state.current_sid = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()
    
    st.write("---")
    
    # 夾帶檔案區
    st.subheader("📎 檔案分析")
    uploaded_file = st.file_uploader("上傳圖片/PDF/CSV", type=["pdf", "txt", "csv", "xlsx", "png", "jpg", "jpeg"])
    
    st.write("---")
    
    # 歷史紀錄清單
    st.subheader("📁 歷史主題")
    try:
        # 直接讀取所有紀錄
        resp = supabase.table("chat_history").select("session_id, content, role").order("created_at", descending=True).limit(50).execute()
        sessions = {}
        for row in resp.data:
            sid = row.get("session_id")
            if sid and sid not in sessions and row["role"] == "user":
                sessions[sid] = row["content"][:12] + "..."
        
        for sid, title in sessions.items():
            col1, col2 = st.columns([4, 1])
            with col1:
                if st.button(f"💬 {title}", key=f"h_{sid}", use_container_width=True):
                    st.session_state.current_sid = sid
                    h_resp = supabase.table("chat_history").select("*").eq("session_id", sid).order("created_at").execute()
                    st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in h_resp.data]
                    st.rerun()
            with col2:
                # 刪除按鈕
                if st.button("🗑️", key=f"d_{sid}"):
                    supabase.table("chat_history").delete().eq("session_id", sid).execute()
                    st.rerun()
    except:
        st.caption("⚠️ 記憶載入中...")

# ================= 4. 主畫面顯示 =================
st.title("🦞 龍蝦王助手")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ================= 5. 對話觸發 =================
if prompt := st.chat_input("跟龍蝦聊聊吧..."):
    # 顯示使用者訊息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    try:
        # 準備傳送給 AI 的內容
        content_parts = [prompt]
        if uploaded_file:
            content_parts.append({"mime_type": uploaded_file.type, "data": uploaded_file.read()})
            st.info("💡 正在分析檔案內容...")

        # 獲取回應
        response = model.generate_content(content_parts)
        reply = response.text
        
        # 顯示 AI 回應
        with st.chat_message("assistant"):
            st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        
        # 寫入資料庫
        supabase.table("chat_history").insert([
            {"session_id": st.session_state.current_sid, "role": "user", "content": prompt},
            {"session_id": st.session_state.current_sid, "role": "assistant", "content": reply}
        ]).execute()
            
    except Exception as e:
        if "429" in str(e):
            st.error("⚠️ Google 暫時忙碌中，請等待約 30 秒後重新傳送。")
        else:
            st.error(f"⚠️ 發生錯誤：{e}")
