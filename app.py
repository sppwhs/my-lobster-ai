import streamlit as st
import google.generativeai as genai
import os
import uuid
from supabase import create_client

# ================= 1. 安全初始化 (只留必要的) =================
api_key = os.environ.get("GOOGLE_API_KEY")
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')
supabase = create_client(url, key)

# ================= 2. 側邊欄 (回歸最簡單的顯示邏輯) =================
with st.sidebar:
    st.header("🦞 龍蝦選單")
    if st.button("➕ 開啟新對話", use_container_width=True):
        st.session_state.current_sid = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()
    
    st.write("---")
    try:
        # 單純撈取有對話過的 Session，不加多餘篩選
        resp = supabase.table("chat_history").select("session_id, content").order("created_at", descending=True).limit(30).execute()
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
        st.write("尚無歷史紀錄")

# ================= 3. 主畫面 =================
st.title("🦞 龍蝦王助手")

if "messages" not in st.session_state: st.session_state.messages = []
if "current_sid" not in st.session_state: st.session_state.current_sid = str(uuid.uuid4())

# 顯示目前的對話內容
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ================= 4. 對話觸發 (回到最初成功的單純流程) =================
if prompt := st.chat_input("跟龍蝦聊聊吧..."):
    # 1. 立即顯示 User
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 2. 直接請求回應 (不讓存檔卡住對話)
    try:
        response = model.generate_content(prompt)
        reply = response.text
        
        with st.chat_message("assistant"):
            st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        
        # 3. 最後再背景存入資料庫 (成功與否都不影響對話)
        supabase.table("chat_history").insert([
            {"session_id": st.session_state.current_sid, "role": "user", "content": prompt},
            {"session_id": st.session_state.current_sid, "role": "assistant", "content": reply}
        ]).execute()
        
    except Exception as e:
        if "429" in str(e):
            st.error("Google 暫時忙碌，請等 15 秒再試一次。")
        else:
            st.error("連線超時，請重試。")
