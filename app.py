import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ================= 1. 安全初始化 =================
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

# 初始化 Gemini
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')
else:
    st.error("API Key 缺失")
    st.stop()

# 初始化 Supabase (加上 Try 避免連線失敗導致閃退)
try:
    supabase = create_client(url, key)
except Exception as e:
    st.error(f"資料庫連線失敗: {e}")
    supabase = None

# ================= 2. 介面配置 =================
st.set_page_config(page_title="龍蝦王助手", page_icon="🦞")
st.title("🦞 龍蝦王助手 (穩定版)")

# 初始化 Session 變數
if "current_sid" not in st.session_state:
    st.session_state.current_sid = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

# ================= 3. 側邊欄 (防禦性讀取) =================
with st.sidebar:
    st.write("### 📁 對話主題")
    if st.button("➕ 開啟新對話", use_container_width=True):
        st.session_state.current_sid = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()

    if supabase:
        try:
            # 限制讀取數量，避免資料太多導致手機端閃退
            resp = supabase.table("chat_history").select("session_id, content, role").order("created_at", descending=True).limit(50).execute()
            
            sessions = {}
            for row in resp.data:
                sid = row.get("session_id")
                if sid and sid not in sessions and row["role"] == "user":
                    sessions[sid] = row["content"][:15] + "..."

            for sid, title in sessions.items():
                if st.button(f"💬 {title}", key=sid, use_container_width=True):
                    st.session_state.current_sid = sid
                    h_resp = supabase.table("chat_history").select("*").eq("session_id", sid).order("created_at").execute()
                    st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in h_resp.data]
                    st.rerun()
        except:
            st.write("暫時無法載入歷史紀錄")

    st.write("---")
    uploaded_file = st.file_uploader("➕ 夾帶檔案", type=["pdf", "txt", "csv", "xlsx", "png", "jpg", "jpeg"])

# ================= 4. 顯示對話 =================
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ================= 5. 對話觸發 (穩健存檔) =================
if prompt := st.chat_input("跟龍蝦聊聊吧..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 異步存檔提示：即使存檔失敗，也要讓 AI 先回答
    if supabase:
        try:
            supabase.table("chat_history").insert({"session_id": st.session_state.current_sid, "role": "user", "content": prompt}).execute()
        except:
            pass

    with st.chat_message("assistant"):
        try:
            content_parts = [prompt]
            if uploaded_file:
                content_parts.append({"mime_type": uploaded_file.type, "data": uploaded_file.read()})
            
            response = model.generate_content(content_parts)
            reply = response.text
            st.markdown(reply)

            st.session_state.messages.append({"role": "assistant", "content": reply})
            if supabase:
                try:
                    supabase.table("chat_history").insert({"session_id": st.session_state.current_sid, "role": "assistant", "content": reply}).execute()
                except:
                    pass
        except Exception as e:
            st.error(f"AI 回應失敗: {e}")
