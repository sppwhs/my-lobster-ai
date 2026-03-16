import os
import uuid
import time
from io import BytesIO
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import google.generativeai as genai
from supabase import create_client


# =========================
# Page
# =========================
st.set_page_config(
    page_title="Lobster AI",
    page_icon="🦞",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>

#MainMenu, footer, header {
visibility:hidden;
}

section[data-testid="stSidebar"] {
display:none !important;
}

.block-container{
padding-top:0.3rem;
padding-bottom:0.4rem;
max-width:850px;
}

.lobster-title{
font-size:1rem;
font-weight:800;
margin:0;
}

.lobster-sub{
font-size:0.7rem;
color:#6b7280;
margin-top:2px;
}

.stButton>button{
border-radius:12px;
min-height:2rem;
}

</style>
""", unsafe_allow_html=True)


# =========================
# ENV
# =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
GOOGLE_KEY = os.getenv("GOOGLE_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY or not GOOGLE_KEY:
    st.error("ENV missing")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GOOGLE_KEY)


# =========================
# Session
# =========================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "chat_id" not in st.session_state:
    st.session_state.chat_id = str(uuid.uuid4())


# =========================
# Header
# =========================
c1, c2 = st.columns([6,2])

with c1:
    st.markdown("""
<div class="lobster-title">🦞 龍蝦王助手</div>
<div class="lobster-sub">私人 AI 助手</div>
""", unsafe_allow_html=True)

with c2:
    if st.button("＋ 新對話", use_container_width=True):
        st.session_state.messages = []
        st.session_state.chat_id = str(uuid.uuid4())
        st.rerun()


# =========================
# Tool switch
# =========================
tool = st.radio(
"",
["收起","Chats","Upload","Memory"],
horizontal=True,
label_visibility="collapsed"
)


# =========================
# Chats
# =========================
if tool=="Chats":

    rows = supabase.table("lobster_sessions").select("*").order("updated_at",desc=True).limit(30).execute().data

    for r in rows:
        if st.button(r["title"],use_container_width=True):
            st.session_state.chat_id = r["id"]

            msgs = supabase.table("lobster_messages").select("*").eq("session_id",r["id"]).order("created_at").execute().data
            st.session_state.messages = msgs

            st.rerun()


# =========================
# Upload
# =========================
if tool=="Upload":

    file = st.file_uploader("upload")

    if file:

        data = file.read()

        st.session_state.file = {
            "name":file.name,
            "data":data
        }

        st.success("file loaded")


# =========================
# Memory
# =========================
if tool=="Memory":

    title = st.text_input("title")
    content = st.text_area("content")

    if st.button("save memory"):

        supabase.table("memory_items").insert({
            "title":title,
            "content":content
        }).execute()

        st.success("saved")


# =========================
# Chat
# =========================
if not st.session_state.messages:

    st.markdown("""
<div style="text-align:center;padding:1rem;color:#6b7280">
<h3>今天想問什麼？</h3>
</div>
""",unsafe_allow_html=True)


for m in st.session_state.messages:

    with st.chat_message("assistant" if m["role"]=="assistant" else "user"):
        st.markdown(m["content"])


# =========================
# Input
# =========================
prompt = st.chat_input("Message Lobster...")

if prompt:

    st.session_state.messages.append({
        "role":"user",
        "content":prompt
    })

    with st.chat_message("user"):
        st.markdown(prompt)

    model = genai.GenerativeModel("gemini-2.5-flash")

    with st.chat_message("assistant"):

        placeholder = st.empty()

        placeholder.markdown("🦞 thinking...")

        response = model.generate_content(prompt)

        text = response.text

        placeholder.markdown(text)

    st.session_state.messages.append({
        "role":"assistant",
        "content":text
    })

    supabase.table("lobster_messages").insert({
        "session_id":st.session_state.chat_id,
        "role":"user",
        "content":prompt
    }).execute()

    supabase.table("lobster_messages").insert({
        "session_id":st.session_state.chat_id,
        "role":"assistant",
        "content":text
    }).execute()
