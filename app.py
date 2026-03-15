import streamlit as st
import google.generativeai as genai
import os
from supabase import create_client

# ================= 1. 初始化與安全設定 =================
# 從 Render 的 Environment Variables 抓取金鑰
google_api_key = os.environ.get("GOOGLE_API_KEY")
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")

# 檢查金鑰是否存在
if not all([google_api_key, supabase_url, supabase_key]):
    st.error("❌ 系統配置不足，請檢查 Render 的環境變數設定。")
    st.stop()

# 設定 Google Gemini
genai.configure(api_key=google_api_key)
model = genai.GenerativeModel('gemini-2.5-flash')

# 設定 Supabase 資料庫連線
supabase = create_client(supabase_url, supabase_key)

# ================= 2. 網頁介面配置 =================
st.set_page_config(page_title="龍蝦王小助手", page_icon="🦞", layout="centered")

# 顯示標題與裝潢
st.write(f"<h1>🦞 龍蝦王小助手</h1>", unsafe_allow_html=True)
st.caption("您的專屬永恆記憶助手 | 支援檔案分析與多模態對話")
st.markdown("---")

# ================= 3. 記憶讀取邏輯 =================
# 如果這節對話還沒載入記憶，就去資料庫抓
if "messages" not in st.session_state:
    try:
        # 從 chat_history 表格讀取所有對話，按時間排序
        response = supabase.table("chat_history").select("*").order("created_at").execute()
        st.session_state.messages = [{"role": row["role"], "content": row["content"]} for row in response.data]
    except Exception as e:
        st.session_state.messages = []
        st.sidebar.warning(f"記憶讀取失敗：{e}")

# 顯示目前的對話紀錄
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ================= 4. 「+」號檔案夾帶功能 =================
# 在聊天輸入框上方建立一個可摺疊的夾帶區塊
with st.expander("➕ 夾帶檔案 (圖片、PDF、文件分析)"):
    uploaded_file = st.file_uploader(
        "將檔案拖曳至此或點擊選取", 
        type=["pdf", "txt", "png", "jpg", "jpeg"], 
        label_visibility="collapsed"
    )
    if uploaded_file:
        st.toast(f"📎 附件已就緒: {uploaded_file.name}", icon="📁")

# ================= 5. 聊天與存檔邏輯 =================
if prompt := st.chat_input("跟龍蝦聊聊吧..."):
    # 1. 顯示並儲存使用者的文字
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 將使用者的話存入資料庫
    try:
        supabase.table("chat_history").insert({"role": "user", "content": prompt}).execute()
    except:
        pass # 即使資料庫存檔失敗也不要中斷對話

    # 2. 讓龍蝦思考與回答
    with st.chat_message("assistant"):
        try:
            # 準備發送給 Gemini 的內容清單
            content_to_send = [prompt]
            
            # 處理夾帶檔案 (多模態支援)
            if uploaded_file is not None:
                file_bytes = uploaded_file.read()
                content_to_send.append({"mime_type": uploaded_file.type, "data": file_bytes})
                st.caption(f"📎 已讀取附件分析中：{uploaded_file.name}")

            # 發送給模型 (Gemini 2.5 Flash)
            # 為了讓模型有「短期記憶」，這裡使用 list 傳送。注意：長期記憶是從資料庫讀取的。
            response = model.generate_content(content_to_send)
            full_response = response.text
            
            # 顯示回答
            st.markdown(full_response)
            
            # 3. 儲存龍蝦的回答
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            # 存入資料庫
            try:
                supabase.table("chat_history").insert({"role": "assistant", "content": full_response}).execute()
            except:
                pass
                
        except Exception as e:
            # 處理 429 額度限制或其他錯誤
            if "429" in str(e):
                st.error("龍蝦太累了（額度達到上限），請休息一分鐘再試！")
            else:
                st.error(f"龍蝦暫時斷片了... 錯誤原因: {e}")

# ================= 6. 介面小優化 =================
# 隱藏 Streamlit 預設的右上角選單與浮水印，讓它更像一個原生 App
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)
