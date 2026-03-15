import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ================= 1. 安全初始化 (防洩漏) =================
# 從 Render 的 Environment Variables 抓取金鑰
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not all([api_key, url, key]):
    st.error("❌ 系統配置不足，請檢查 Render 的環境變數設定。")
    st.stop()

# 設定 Gemini
genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-1.5-flash')

# 設定 Supabase
supabase = create_client(url, key)

# ================= 2. 網頁介面配置 (找回標題) =================
st.set_page_config(page_title="龍蝦王小助手", page_icon="🦞")
st.title("🦞 龍蝦王小助手")
st.markdown("---")

# ================= 3. 主題分類與記憶讀取邏輯 (核心功能回歸) =================
# 1. 初始化 session_state
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# 2. 側邊欄：顯示所有主題（對話節）
with st.sidebar:
    st.subheader("📁 歷史對話主題")
    
    # 從資料庫抓取所有不重複的 session_id，作為主題
    try:
        response = supabase.table("chat_history").select("session_id, content, role").execute()
        # 整理出不重複的 session 列表，並選第一句話當主題名稱
        all_sessions = {}
        for row in response.data:
            sid = row["session_id"]
            if sid not in all_sessions and row["role"] == "user":
                all_sessions[sid] = row["content"][:20] + "..." # 截取前 20 個字當主題名
        
        # 顯示所有主題供選擇
        if st.button("➕ 開啟新對話"):
            st.session_state.current_session_id = str(uuid.uuid4()) # 生成新的 ID
            st.session_state.messages = [] # 清空畫面
            st.rerun() # 重新整理網頁
            
        for sid, title in all_sessions.items():
            if st.button(title, key=sid): # 點擊主題按鈕
                st.session_state.current_session_id = sid # 切換到該 ID
                # 重新從資料庫讀取該主題的對話
                resp = supabase.table("chat_history").select("*").eq("session_id", sid).order("created_at").execute()
                st.session_state.messages = [{"role": r["role"], "content": r["content"]} for r in resp.data]
                st.rerun() # 重新整理網頁
    except:
        pass # 忽略錯誤（例如：第一次使用資料庫沒資料）

# 3. 如果沒有選中任何主題，就生成一個新的 ID
if st.session_state.current_session_id is None:
    st.session_state.current_session_id = str(uuid.uuid4())

# 4. 在畫面上顯示當前主題的所有對話歷史
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ================= 4. 對話邏輯 (修復輸入欄和+號) =================
# 在側邊欄放「+號」上傳檔案，避免干擾主對話欄
with st.sidebar:
    st.subheader("➕ 夾帶檔案")
    uploaded_file = st.file_uploader("選擇圖片、PDF 或文字檔", type=["pdf", "txt", "png", "jpg", "jpeg"], key="lobster_uploader")
    if uploaded_file:
        st.info(f"📁 已就緒: {uploaded_file.name}")

# 主對話輸入欄
if prompt := st.chat_input("跟龍蝦說說話..."):
    # 1. 顯示使用者文字
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 存入資料庫 (包含 session_id，依主題分類)
    supabase.table("chat_history").insert({
        "session_id": st.session_state.current_session_id,
        "role": "user", 
        "content": prompt
    }).execute()

    # 2. 讓龍蝦思考與回答
    with st.chat_message("assistant"):
        try:
            # 準備發送給 Gemini 的內容清單
            content_to_send = [prompt]
            
            # 如果有上傳檔案，就把檔案塞進去給 Gemini 看
            if uploaded_file is not None:
                file_bytes = uploaded_file.read()
                # Gemini 1.5 Flash 支援文字和圖片混合
                if uploaded_file.type.startswith("image"):
                    content_to_send.append({"mime_type": uploaded_file.type, "data": file_bytes})
                else:
                    # 如果是文字檔或 PDF，轉成文字（這裡簡化處理，Gemini 1.5 支援直接傳 bytes）
                    content_to_send.append({"mime_type": uploaded_file.type, "data": file_bytes})
                st.caption(f"📎 龍蝦正在分析檔案：{uploaded_file.name}")

            # 發送給模型
            response = model.generate_content(content_to_send)
            full_response = response.text
            st.markdown(full_response)
            
            # 3. 儲存龍蝦的回答
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            # 存入資料庫
            supabase.table("chat_history").insert({
                "session_id": st.session_state.current_session_id,
                "role": "assistant", 
                "content": full_response
            }).execute()
        except Exception as e:
            st.error(f"龍蝦稍微閃神了，請再試一次！(錯誤: {e})")
