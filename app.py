import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ================= 1. 安全初始化 =================
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not all([api_key, url, key]):
    st.error("❌ 配置錯誤，請檢查環境變數")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-1.5-flash')
supabase = create_client(url, key)

# ================= 2. 側邊欄：主題分類與檔案管理 =================
with st.sidebar:
    st.write("### 📁 歷史對話主題")
    
    # [修復]：確保資料庫能正確撈出主題列表
    try:
        # 抓取所有對話，按時間倒序
        resp = supabase.table("chat_history").select("session_id, content, role").order("created_at", descending=True).execute()
        
        # 建立不重複的主題字典
        sessions = {}
        for row in resp.data:
            sid = row["session_id"]
            if sid not in sessions and row["role"] == "user":
                # 取前 15 個字當標題
                sessions[sid] = row["content"][:15] + "..."

        if st.button("➕ 開啟新對話", use_container_width=True):
            st.session_state.current_sid = str(uuid.uuid4())
            st.session_state.messages = []
            st.rerun()

        st.write("---")
        # 顯示歷史對話按鈕
        for sid, title in sessions.items():
            if st.button(f"💬 {title}", key=sid, use_container_width=True):
                st.session_state.current_sid = sid
                # 載入該主題歷史
                history_resp = supabase.table("chat_history").select("*").eq("session_id", sid).order("created_at").execute()
                st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in history_resp.data]
                st.rerun()
    except Exception as e:
        st.write("尚無歷史對話")

    st.write("---")
    st.write("### ➕ 夾帶檔案")
    # [修復]：移除限制，增加 csv, xlsx 等格式
    uploaded_file = st.file_uploader(
        "選擇檔案分析", 
        type=["pdf", "txt", "csv", "xlsx", "png", "jpg", "jpeg", "docx"],
        key="global_uploader"
    )

# ================= 3. 聊天介面 =================
st.title("🦞 龍蝦王小助手")
st.caption("您的專屬永恆記憶助手")

if "current_sid" not in st.session_state:
    st.session_state.current_sid = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

# 顯示對話歷史
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ================= 4. 對話觸發 (箭頭功能恢復) =================
if prompt := st.chat_input("跟龍蝦說說話..."):
    # 1. 紀錄使用者輸入
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 寫入資料庫
    supabase.table("chat_history").insert({
        "session_id": st.session_state.current_sid,
        "role": "user",
        "content": prompt
    }).execute()

    # 2. 處理回覆
    with st.chat_message("assistant"):
        try:
            content_parts = [prompt]
            
            # [邏輯確認]：如果有上傳檔案，這一次的對話就會帶上檔案
            if uploaded_file:
                bytes_data = uploaded_file.read()
                content_parts.append({
                    "mime_type": uploaded_file.type if uploaded_file.type else "text/plain",
                    "data": bytes_data
                })
                st.info(f"📁 已夾帶附件：{uploaded_file.name}")

            response = model.generate_content(content_parts)
            reply = response.text
            st.markdown(reply)

            # 儲存回覆
            st.session_state.messages.append({"role": "assistant", "content": reply})
            supabase.table("chat_history").insert({
                "session_id": st.session_state.current_sid,
                "role": "assistant",
                "content": reply
            }).execute()
        except Exception as e:
            st.error(f"龍蝦斷片了：{e}")
