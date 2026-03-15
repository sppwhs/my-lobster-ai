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

# ================= 2. 側邊欄 (主題分類 + 檔案上傳) =================
with st.sidebar:
    st.header("🦞 龍蝦選單")
    if st.button("➕ 開啟新對話", use_container_width=True):
        st.session_state.current_sid = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()
    
    st.write("---")
    # 夾帶檔案區 (放在側邊欄，乾淨且穩定)
    st.subheader("➕ 夾帶檔案分析")
    uploaded_file = st.file_uploader("支援圖片、PDF、CSV 等", type=["pdf", "txt", "csv", "xlsx", "png", "jpg", "jpeg"])
    if uploaded_file:
        st.success(f"📎 已載入: {uploaded_file.name}")

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
            if st.button(f"💬 {title}", key=sid, use_container_width=True):
                st.session_state.current_sid = sid
                h_resp = supabase.table("chat_history").select("*").eq("session_id", sid).order("created_at").execute()
                st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in h_resp.data]
                st.rerun()
    except:
        pass

# ================= 3. 主介面 =================
st.title("🦞 龍蝦王助手")

if "messages" not in st.session_state: st.session_state.messages = []
if "current_sid" not in st.session_state: st.session_state.current_sid = str(uuid.uuid4())

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

# ================= 4. 對話觸發 (支援檔案分析) =================
if prompt := st.chat_input("跟龍蝦聊聊吧..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)
    
    try:
        # 準備發送給 AI 的內容
        content_parts = [prompt]
        if uploaded_file:
            bytes_data = uploaded_file.read()
            content_parts.append({
                "mime_type": uploaded_file.type if uploaded_file.type else "application/octet-stream",
                "data": bytes_data
            })
            st.info(f"💡 龍蝦正在閱讀檔案並思考...")

        # 獲取回應
        response = model.generate_content(content_parts)
        reply = response.text
        
        with st.chat_message("assistant"): st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        
        # 寫入資料庫 (僅存文字，檔案不存入 DB 以節省空間)
        supabase.table("chat_history").insert({"session_id": st.session_state.current_sid, "role": "user", "content": prompt}).execute()
        supabase.table("chat_history").insert({"session_id": st.session_state.current_sid, "role": "assistant", "content": reply}).execute()
        
    except Exception as e:
        if "429" in str(e):
            st.error("⚠️ Google 暫時忙碌，請等 30 秒再試一次。")
        else:
            st.error(f"⚠️ 發生錯誤：{e}")
