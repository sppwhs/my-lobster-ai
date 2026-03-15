import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ================= 1. 初始化 =================
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not all([api_key, url, key]):
    st.error("❌ 配置不足，請檢查環境變數")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')
supabase = create_client(url, key)

# ================= 2. 側邊欄：主題分類 (強效讀取版) =================
with st.sidebar:
    st.write("### 📁 歷史對話主題")
    
    try:
        # 抓取所有對話內容
        resp = supabase.table("chat_history").select("session_id, content, role").order("created_at", descending=True).execute()
        
        sessions = {}
        for row in resp.data:
            # 如果 session_id 是空的，給它一個預設值，確保它會出現在清單中
            sid = row.get("session_id") or "legacy-archive"
            if sid not in sessions and row["role"] == "user":
                sessions[sid] = row["content"][:15] + "..."

        if st.button("➕ 開啟新對話", use_container_width=True):
            st.session_state.current_sid = str(uuid.uuid4())
            st.session_state.messages = []
            st.rerun()

        st.write("---")
        for sid, title in sessions.items():
            col1, col2 = st.columns([4, 1])
            with col1:
                if st.button(f"💬 {title}", key=f"btn_{sid}", use_container_width=True):
                    st.session_state.current_sid = sid
                    h_resp = supabase.table("chat_history").select("*").eq("session_id", sid).order("created_at").execute()
                    st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in h_resp.data]
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"del_{sid}"):
                    supabase.table("chat_history").delete().eq("session_id", sid).execute()
                    st.rerun()
    except Exception as e:
        st.write("尚未建立紀錄")

    st.write("---")
    uploaded_file = st.file_uploader("➕ 夾帶檔案分析", type=["pdf", "txt", "csv", "xlsx", "png", "jpg", "jpeg"])

# ================= 3. 主畫面 =================
st.title("🦞 龍蝦王小助手")

if "current_sid" not in st.session_state:
    st.session_state.current_sid = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ================= 4. 對話觸發 =================
if prompt := st.chat_input("跟龍蝦說說話..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 存入資料庫
    supabase.table("chat_history").insert({
        "session_id": st.session_state.current_sid,
        "role": "user",
        "content": prompt
    }).execute()

    with st.chat_message("assistant"):
        try:
            content_parts = [prompt]
            if uploaded_file:
                content_parts.append({"mime_type": uploaded_file.type, "data": uploaded_file.read()})
            
            response = model.generate_content(content_parts)
            reply = response.text
            st.markdown(reply)

            st.session_state.messages.append({"role": "assistant", "content": reply})
            supabase.table("chat_history").insert({
                "session_id": st.session_state.current_sid,
                "role": "assistant",
                "content": reply
            }).execute()
        except Exception as e:
            st.error(f"錯誤: {e}")
