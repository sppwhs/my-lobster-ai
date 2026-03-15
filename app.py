import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ================= 1. 安全初始化 (鎖定 2.5 型號) =================
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not all([api_key, url, key]):
    st.error("❌ 系統配置不足，請檢查 Render 的環境變數設定。")
    st.stop()

# 鎖定您的環境認可的 2.5 版本
genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')
supabase = create_client(url, key)

# ================= 2. 介面配置與側邊欄 (主題分類與檔案) =================
st.set_page_config(page_title="龍蝦王小助手", page_icon="🦞")

with st.sidebar:
    st.write("### 📁 歷史對話主題")
    
    # 從資料庫抓取所有 session，並取第一句話當標題
    try:
        resp = supabase.table("chat_history").select("session_id, content, role").order("created_at", descending=True).execute()
        
        sessions = {}
        for row in resp.data:
            sid = row["session_id"]
            if sid not in sessions and row["role"] == "user":
                sessions[sid] = row["content"][:15] + "..."

        if st.button("➕ 開啟新對話", use_container_width=True):
            st.session_state.current_sid = str(uuid.uuid4())
            st.session_state.messages = []
            st.rerun()

        st.write("---")
        # 顯示歷史主題按鈕
        for sid, title in sessions.items():
            if st.button(f"💬 {title}", key=sid, use_container_width=True):
                st.session_state.current_sid = sid
                # 重新載入該主題對話
                history_resp = supabase.table("chat_history").select("*").eq("session_id", sid).order("created_at").execute()
                st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in history_resp.data]
                st.rerun()
    except:
        st.write("尚未有歷史紀錄")

    st.write("---")
    st.write("### ➕ 夾帶檔案")
    # 開放 CSV, Excel 等所有您需要的格式
    uploaded_file = st.file_uploader(
        "選擇檔案分析 (圖片/CSV/PDF)", 
        type=["pdf", "txt", "csv", "xlsx", "png", "jpg", "jpeg", "docx"],
        key="global_uploader"
    )

# ================= 3. 主畫面顯示 =================
st.title("🦞 龍蝦王小助手")
st.caption("您的專屬永恆記憶助手 | 支援 CSV 資料分析")

# 初始化 Session ID 與 訊息清單
if "current_sid" not in st.session_state:
    st.session_state.current_sid = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

# 顯示目前的對話內容
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ================= 4. 對話觸發 (箭頭發送功能) =================
if prompt := st.chat_input("跟龍蝦說說話..."):
    # 1. 顯示使用者輸入並存入資料庫
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    supabase.table("chat_history").insert({
        "session_id": st.session_state.current_sid,
        "role": "user",
        "content": prompt
    }).execute()

    # 2. 龍蝦思考回覆
    with st.chat_message("assistant"):
        try:
            content_parts = [prompt]
            
            # 如果側邊欄有選檔案，這一次發送就會帶上它
            if uploaded_file:
                bytes_data = uploaded_file.read()
                content_parts.append({
                    "mime_type": uploaded_file.type if uploaded_file.type else "text/plain",
                    "data": bytes_data
                })
                st.info(f"📎 正在分析附件：{uploaded_file.name}")

            # 呼叫 Gemini 2.5
            response = model.generate_content(content_parts)
            reply = response.text
            st.markdown(reply)

            # 儲存回覆到資料庫
            st.session_state.messages.append({"role": "assistant", "content": reply})
            supabase.table("chat_history").insert({
                "session_id": st.session_state.current_sid,
                "role": "assistant",
                "content": reply
            }).execute()
        except Exception as e:
            st.error(f"龍蝦斷片了，可能是額度問題或格式錯誤：{e}")

# ================= 5. 介面美化 =================
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)
