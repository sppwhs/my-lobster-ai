import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ================= 1. 初始化 (務必確認 Render 環境變數已設定) =================
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not all([api_key, url, key]):
    st.error("❌ 配置不足，請檢查 Render 環境變數")
    st.stop()

# 鎖定使用 2.5 版本
genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')
supabase = create_client(url, key)

# ================= 2. 側邊欄：歷史主題分類 (解決紀錄不見的問題) =================
with st.sidebar:
    st.write("### 📁 歷史對話主題")
    
    try:
        # 從資料庫撈取所有對話，按時間由新到舊排序
        resp = supabase.table("chat_history").select("session_id, content, role").order("created_at", descending=True).execute()
        
        # 整理出不重複的對話節點 (Sessions)
        sessions = {}
        for row in resp.data:
            sid = row["session_id"]
            if sid not in sessions and row["role"] == "user":
                # 取第一句話的前 15 個字作為主題標題
                sessions[sid] = row["content"][:15] + "..."

        if st.button("➕ 開啟新對話", use_container_width=True):
            st.session_state.current_sid = str(uuid.uuid4())
            st.session_state.messages = []
            st.rerun()

        st.write("---")
        # 顯示歷史清單，點擊後切換
        for sid, title in sessions.items():
            if st.button(f"💬 {title}", key=sid, use_container_width=True):
                st.session_state.current_sid = sid
                # 重新載入該主題的所有對話
                h_resp = supabase.table("chat_history").select("*").eq("session_id", sid).order("created_at").execute()
                st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in h_resp.data]
                st.rerun()
    except Exception as e:
        st.write("尚無歷史紀錄或連線錯誤")

    st.write("---")
    uploaded_file = st.file_uploader("➕ 夾帶檔案分析", type=["pdf", "txt", "csv", "xlsx", "png", "jpg", "jpeg"])

# ================= 3. 主畫面介面 =================
st.title("🦞 龍蝦王小助手")

if "current_sid" not in st.session_state:
    st.session_state.current_sid = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

# 顯示目前的對話內容
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ================= 4. 對話觸發 (按鈕連動) =================
if prompt := st.chat_input("跟龍蝦說說話..."):
    # 1. 存入畫面
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 2. 存入資料庫 (這步失敗會導致歷史紀錄消失，所以要確保成功)
    supabase.table("chat_history").insert({
        "session_id": st.session_state.current_sid,
        "role": "user",
        "content": prompt
    }).execute()

    # 3. 獲取 AI 回應
    with st.chat_message("assistant"):
        try:
            content_parts = [prompt]
            if uploaded_file:
                bytes_data = uploaded_file.read()
                content_parts.append({"mime_type": uploaded_file.type, "data": bytes_data})
                st.caption(f"📎 已讀取：{uploaded_file.name}")

            response = model.generate_content(content_parts)
            reply = response.text
            st.markdown(reply)

            # 4. 存入資料庫與畫面
            st.session_state.messages.append({"role": "assistant", "content": reply})
            supabase.table("chat_history").insert({
                "session_id": st.session_state.current_sid,
                "role": "assistant",
                "content": reply
            }).execute()
        except Exception as e:
            st.error(f"龍蝦斷片了：{e}")
