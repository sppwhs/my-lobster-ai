import streamlit as st
import google.generativeai as genai
import os
from supabase import create_client

# 1. 核心基礎設定 (從 Render 環境變數讀取)
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

# 初始化 Google Gemini
genai.configure(api_key=api_key)
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    system_instruction="你是一隻博學多聞且幽默的龍蝦小助理。你對高爾夫球、台灣期指交易、電動車非常了解。說話風格簡潔、精準，偶爾會帶一點點幽默感，稱呼使用者為『老大』。"
)

# 初始化 Supabase 連線
supabase = create_client(url, key)

# 2. 網頁頁面設定
st.set_page_config(page_title="龍蝦王小助手", page_icon="🦞")

# 繪製霸氣標題
st.write(f"<h1>🦞 龍蝦王小助手</h1>", unsafe_allow_html=True)
st.caption("您的專屬永恆記憶助手 | 已連線至雲端資料庫")
st.markdown("---")

# 3. 讀取永恆記憶 (從資料庫抓取歷史紀錄)
if "messages" not in st.session_state:
    try:
        # 嘗試從 Supabase 抓取所有對話，按時間排序
        response = supabase.table("chat_history").select("*").order("created_at").execute()
        st.session_state.messages = [{"role": row["role"], "content": row["content"]} for row in response.data]
    except Exception as e:
        # 如果讀取失敗（例如表格還沒建好），先給空列表
        st.session_state.messages = []

# 4. 在畫面上顯示所有歷史對話
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 5. 聊天輸入框邏輯
if prompt := st.chat_input("老大，今天想聊點什麼？"):
    # A. 顯示並儲存使用者的話
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # B. 同步寫入資料庫 (確保永恆記憶)
    try:
        supabase.table("chat_history").insert({"role": "user", "content": prompt}).execute()
    except:
        pass # 防止資料庫暫時連不上導致程式崩潰

    # C. 龍蝦王思考並回答
    with st.chat_message("assistant"):
        try:
            # 建立簡易對話 (此處不帶入過長歷史以節省額度，靠資料庫維持視覺記憶)
            chat = model.start_chat(history=[])
            response = chat.send_message(prompt)
            full_response = response.text
            
            st.markdown(full_response)
            
            # D. 儲存龍蝦的話到畫面與資料庫
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            supabase.table("chat_history").insert({"role": "assistant", "content": full_response}).execute()
            
        except Exception as e:
            st.error(f"老大抱歉，龍蝦剛才閃神了... 錯誤訊息: {e}")

# 6. 側邊欄：功能區
with st.sidebar:
    st.title("龍蝦控制室")
    if st.button("清空對話顯示 (僅限本次)"):
        st.session_state.messages = []
        st.rerun()
    
    st.info("提示：這隻龍蝦會記得你說過的話，即使重新整理網頁也不會忘記。")
