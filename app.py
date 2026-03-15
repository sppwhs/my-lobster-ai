import streamlit as st
import google.generativeai as genai
import os
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

# ================= 2. 介面配置 (找回標題) =================
st.set_page_config(page_title="龍蝦王小助手", page_icon="🦞")
st.title("🦞 龍蝦王小助手")
st.markdown("---")

# ================= 3. 記憶邏輯 (核心功能回歸) =================
# 1. 頁面啟動時，初始化 session_state
if "messages" not in st.session_state:
    st.session_state.messages = []
    # 2. 從資料庫讀取所有歷史對話
    try:
        response = supabase.table("chat_history").select("*").order("created_at").execute()
        # 將資料庫資料格式化並存入 session_state
        for row in response.data:
            st.session_state.messages.append({"role": row["role"], "content": row["content"]})
    except:
        pass # 第一次使用時資料庫可能是空的，忽略錯誤

# 3. 在畫面上顯示所有歷史對話
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ================= 4. 對話邏輯 (修復輸入欄和+號) =================
# 在側邊欄放「+號」上傳檔案，避免干擾主對話欄
with st.sidebar:
    st.subheader("➕ 夾帶檔案")
    uploaded_file = st.file_uploader("選擇圖片、PDF 或文字檔", type=["pdf", "txt", "png", "jpg", "jpeg"])
    if uploaded_file:
        st.info(f"📁 已就緒: {uploaded_file.name}")

# 主對話輸入欄
if prompt := st.chat_input("跟龍蝦說說話..."):
    # 1. 顯示使用者文字
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 存入資料庫
    supabase.table("chat_history").insert({"role": "user", "content": prompt}).execute()

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
            supabase.table("chat_history").insert({"role": "assistant", "content": full_response}).execute()
        except:
            st.error("龍蝦稍微閃神了，請再試一次！")
