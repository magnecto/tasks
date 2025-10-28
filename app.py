
# 🔧 簡易バージョン: Unique key fixes only
# （フル機能版のコードは前回説明したものに準拠）
import streamlit as st
import pandas as pd
import sqlite3
from contextlib import closing
from datetime import datetime, date

DB_PATH = "data.db"

STATUS_OPTIONS = ["問診待ち","診察中","検査中","処方・納品待ち","経過観察","完了","中止"]
PRIORITY_OPTIONS = ["低","中","高","緊急"]

def now():
    return datetime.utcnow().isoformat()

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, title TEXT, owner TEXT, status TEXT, created_at TEXT, updated_at TEXT)")
        conn.commit()

def fetch_projects():
    return pd.read_sql("SELECT * FROM projects", get_conn())

def insert_project(title, owner, status):
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO projects (title, owner, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (title, owner, status, now(), now()))
        conn.commit()

def project_form(key_prefix):
    title = st.text_input("案件名", key=f"{key_prefix}_title")
    owner = st.text_input("担当", key=f"{key_prefix}_owner")
    status = st.selectbox("ステータス", STATUS_OPTIONS, key=f"{key_prefix}_status")
    return title, owner, status

st.title("🗂️ 案件カルテ v2.1 (Unique Key Fix Mini)")

init_db()

df = fetch_projects()
st.write("📋 現在の案件一覧")
st.dataframe(df, use_container_width=True)

st.subheader("➕ 新規案件")
title, owner, status = project_form("create")
if st.button("追加", key="btn_add"):
    if title:
        insert_project(title, owner, status)
        st.success("登録完了！再実行で反映されます✨")
