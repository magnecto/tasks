import streamlit as st
import pandas as pd
import sqlite3, os, re
from contextlib import closing
from datetime import datetime, date
import altair as alt
from typing import Optional

DB_PATH = "data.db"
UPLOAD_DIR = "uploads"

# ---------- DB Helpers ----------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        # projects / notes (existing)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            client TEXT,
            status TEXT NOT NULL DEFAULT '診察中',
            priority TEXT DEFAULT '中',
            owner TEXT,
            start_date TEXT,
            due_date TEXT,
            description TEXT,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            note_date TEXT NOT NULL,
            author TEXT,
            content TEXT NOT NULL,
            next_action TEXT,
            progress_percent INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );
        """)
        # resources: Drive/Web/Localなどの関連資料
        cur.execute("""
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            title TEXT,
            kind TEXT,            -- Drive/Web/Image/Local/Other
            url TEXT,             -- 外部URL(Drive/Notion/Web等)
            local_path TEXT,      -- ローカル保存した相対パス（uploads配下）
            tags TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );
        """)
        # idea board: 参考URL/画像メモ
        cur.execute("""
        CREATE TABLE IF NOT EXISTS ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            title TEXT,
            url TEXT,
            image_path TEXT,      -- uploads配下
            note TEXT,
            tags TEXT,
            pinned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );
        """)
        conn.commit()

def now_str():
    return datetime.utcnow().isoformat(timespec="seconds")

# ---------- Generic DB helpers ----------
def df_query(sql, params=()):
    with closing(get_conn()) as conn:
        return pd.read_sql_query(sql, conn, params=params)

def exec_sql(sql, params=()):
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid

# ---------- Domain helpers ----------
STATUS_OPTIONS = ["問診待ち", "診察中", "検査中", "処方・納品待ち", "経過観察", "完了", "中止"]
PRIORITY_OPTIONS = ["低", "中", "高", "緊急"]

def status_badge(s: str):
    colors = {"問診待ち":"gray","診察中":"orange","検査中":"blue","処方・納品待ち":"purple","経過観察":"green","完了":"green","中止":"red"}
    c = colors.get(s, "gray")
    return f":{c}[{s}]"

def ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)

def save_uploaded_file(upfile, prefix=""):
    ensure_upload_dir()
    fname = upfile.name
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", fname)
    rel = os.path.join(UPLOAD_DIR, f"{prefix}{stamp}-{safe}")
    with open(rel, "wb") as f:
        f.write(upfile.getbuffer())
    return rel

# ---------- Pages ----------
def page_dashboard():
    st.subheader("ダッシュボード")
    df = df_query("SELECT * FROM projects WHERE archived=0 ORDER BY updated_at DESC")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("総案件", len(df))
    c2.metric("進行中", int(df["status"].isin(["診察中","検査中","処方・納品待ち","経過観察"]).sum()) if not df.empty else 0)
    c3.metric("完了", int(df["status"].eq("完了").sum()) if not df.empty else 0)
    overdue = 0
    if not df.empty:
        today = pd.Timestamp.today().normalize()
        due = pd.to_datetime(df["due_date"], errors="coerce")
        overdue = ((due < today) & (~df["status"].isin(["完了","中止"]))).sum()
    c4.metric("期限超過", int(overdue))

    # Natural language-ish search box
    st.markdown("#### クエリ検索（自然文OK）")
    q = st.text_input("例: 『来週期限の案件』『A社の最新資料』『止まってるやつ』など")
    if q:
        results = run_semanticish_search(q)
        st.write(f"**{len(results)} 件ヒット**")
        st.dataframe(results, use_container_width=True)

    # Charts
    if not df.empty:
        st.markdown("#### ステータス別 件数")
        status_count = df.assign(status=df["status"].fillna("未設定")).groupby("status").size().reset_index(name="count")
        st.altair_chart(alt.Chart(status_count).mark_bar().encode(x="status:N", y="count:Q", tooltip=["status","count"]), use_container_width=True)

        st.markdown("#### 期限の近い案件（上位10）")
        upcoming = df.copy()
        upcoming["due_ts"] = pd.to_datetime(upcoming["due_date"], errors="coerce")
        upcoming = upcoming[(~upcoming["due_ts"].isna()) & (~upcoming["status"].isin(["完了","中止"]))].sort_values("due_ts").head(10)
        st.dataframe(upcoming[["id","title","owner","status","priority","due_date","client"]], use_container_width=True)

def run_semanticish_search(q: str) -> pd.DataFrame:
    # very simple rules + keyword matching across projects/notes/resources/ideas
    q_norm = q.lower()
    dfs = []

    # projects
    pdf = df_query("SELECT id, title, status, priority, owner, due_date, description, updated_at FROM projects")
    if not pdf.empty:
        mask = pdf.apply(lambda r: q_norm in " ".join([str(x).lower() for x in r.values]), axis=1)
        p2 = pdf[mask].copy()
        p2["kind"] = "project"
        dfs.append(p2)

    # notes
    ndf = df_query("""
        SELECT notes.id, notes.project_id, notes.note_date, notes.content, notes.next_action, notes.progress_percent, projects.title AS project_title
        FROM notes LEFT JOIN projects ON projects.id = notes.project_id
    """)
    if not ndf.empty:
        mask = ndf.apply(lambda r: q_norm in " ".join([str(x).lower() for x in r.values]), axis=1)
        n2 = ndf[mask].copy()
        n2["kind"] = "note"
        dfs.append(n2)

    # resources
    rdf = df_query("""
        SELECT resources.id, resources.project_id, resources.title, resources.kind, resources.url, resources.local_path, resources.tags, projects.title AS project_title
        FROM resources LEFT JOIN projects ON projects.id = resources.project_id
    """)
    if not rdf.empty:
        mask = rdf.apply(lambda r: q_norm in " ".join([str(x).lower() for x in r.values]), axis=1)
        r2 = rdf[mask].copy()
        r2["kind"] = "resource"
        dfs.append(r2)

    # ideas
    idf = df_query("""
        SELECT ideas.id, ideas.project_id, ideas.title, ideas.url, ideas.image_path, ideas.note, ideas.tags, projects.title AS project_title, ideas.pinned
        FROM ideas LEFT JOIN projects ON projects.id = ideas.project_id
    """)
    if not idf.empty:
        mask = idf.apply(lambda r: q_norm in " ".join([str(x).lower() for x in r.values]), axis=1)
        i2 = idf[mask].copy()
        i2["kind"] = "idea"
        dfs.append(i2)

    if dfs:
        out = pd.concat(dfs, ignore_index=True, sort=False)
        # very naive time-based boost
        if "updated_at" in out.columns:
            out = out.sort_values(by=[c for c in ["updated_at","note_date"] if c in out.columns], ascending=False, na_position="last")
        return out
    return pd.DataFrame()

# 置き換え：旧) def project_form(existing: Optional[dict]=None):
def project_form(key_prefix: str, existing: Optional[dict]=None):
    col1, col2 = st.columns(2)
    title = col1.text_input("案件名 *",
                            value=(existing.get("title") if existing else ""),
                            key=f"{key_prefix}_title")
    client = col2.text_input("クライアント/関係者",
                             value=(existing.get("client") if existing else ""),
                             key=f"{key_prefix}_client")

    col3, col4, col5 = st.columns(3)
    status = col3.selectbox("ステータス", STATUS_OPTIONS,
                            index=(STATUS_OPTIONS.index(existing["status"]) if existing else 1),
                            key=f"{key_prefix}_status")
    priority = col4.selectbox("優先度", PRIORITY_OPTIONS,
                              index=(PRIORITY_OPTIONS.index(existing["priority"]) if existing else 1),
                              key=f"{key_prefix}_priority")
    owner = col5.text_input("担当",
                            value=(existing.get("owner") if existing else ""),
                            key=f"{key_prefix}_owner")

    col6, col7 = st.columns(2)
    sd = pd.to_datetime(existing["start_date"]).date() if existing and existing.get("start_date") else None
    dd = pd.to_datetime(existing["due_date"]).date() if existing and existing.get("due_date") else None
    start_date = col6.date_input("開始日", value=sd, key=f"{key_prefix}_start")
    due_date   = col7.date_input("期限",   value=dd, key=f"{key_prefix}_due")

    description = st.text_area("概要・メモ",
                               value=(existing.get("description") if existing else ""),
                               height=100, key=f"{key_prefix}_desc")
    archived = st.checkbox("アーカイブ",
                           value=(bool(existing["archived"]) if existing else False),
                           key=f"{key_prefix}_arch")

    return {
        "title": (title or "").strip(),
        "client": (client or "").strip() or None,
        "status": status,
        "priority": priority,
        "owner": (owner or "").strip() or None,
        "start_date": start_date.isoformat() if start_date else None,
        "due_date":   due_date.isoformat()   if due_date   else None,
        "description": (description or "").strip() or None,
        "archived": 1 if archived else 0,
    }


def page_projects():
    st.subheader("案件")
    with st.expander("フィルター", expanded=True):
        colf1, colf2, colf3, colf4 = st.columns(4)
        kw = colf1.text_input("キーワード")
        st_opt = colf2.multiselect("ステータス", STATUS_OPTIONS, default=STATUS_OPTIONS)
        pr_opt = colf3.multiselect("優先度", PRIORITY_OPTIONS, default=PRIORITY_OPTIONS)
        owner = colf4.text_input("担当")
        include_archived = st.checkbox("アーカイブも表示", value=False)

    df = df_query("SELECT * FROM projects ORDER BY updated_at DESC")
    if not include_archived:
        df = df[df["archived"]==0]

    if kw and not df.empty:
        mask = df.apply(lambda r: kw.lower() in (" ".join([str(r.get(c,'')) for c in df.columns])).lower(), axis=1)
        df = df[mask]
    if st_opt and not df.empty:
        df = df[df["status"].isin(st_opt)]
    if pr_opt and not df.empty:
        df = df[df["priority"].isin(pr_opt)]
    if owner and not df.empty:
        df = df[df["owner"].fillna("").str.contains(owner, case=False)]

    st.caption(f"{len(df)} 件表示")
    st.dataframe(df[["id","title","status","priority","owner","due_date","client","updated_at"]], use_container_width=True, height=320)

    st.markdown("---")
    st.markdown("### 新規案件")
    new_rec = project_form()
    colA, colB = st.columns([1,2])
    if colA.button("追加", type="primary", use_container_width=True, disabled=(not new_rec["title"])):
        exec_sql("""
            INSERT INTO projects (title, client, status, priority, owner, start_date, due_date, description, archived, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (new_rec["title"], new_rec["client"], new_rec["status"], new_rec["priority"], new_rec["owner"],
              new_rec["start_date"], new_rec["due_date"], new_rec["description"], new_rec["archived"], now_str(), now_str()))
        st.success("追加しました。左の再実行ボタンで更新されます。")

    st.markdown("---")
    st.markdown("### 案件の編集")
    all_df = df_query("SELECT * FROM projects ORDER BY id DESC")
    if all_df.empty:
        st.info("編集対象の案件がありません。")
        return
    # --- 新規作成ブロック ---
new_rec = project_form("create")  # ← 追加

# --- 編集ブロック ---
pid = st.selectbox("案件IDを選択", all_df["id"].tolist(),
                   index=0, key="edit_pid",
                   format_func=lambda _id: f"{_id}: {all_df.set_index('id').loc[_id, 'title']}")
existing = all_df.set_index("id").loc[pid].to_dict()
edit_rec = project_form(f"edit_{pid}", existing)  # ← 追加

    if st.button("更新", type="secondary"):
        fields = ["title","client","status","priority","owner","start_date","due_date","description","archived"]
        sets = ", ".join([f"{f}=?" for f in fields])
        exec_sql(f"UPDATE projects SET {sets}, updated_at=? WHERE id=?", tuple([edit_rec[f] for f in fields] + [now_str(), pid]))
        st.success("更新しました。左の再実行ボタンで更新されます。")

    # Quick links for resources under selected project
    st.markdown("#### 関連資料（ショートカット）")
    r = df_query("SELECT * FROM resources WHERE project_id=? ORDER BY updated_at DESC", (pid,))
    if r.empty:
        st.caption("関連資料がまだありません。『資料』ページから追加できます。")
    else:
        for _, row in r.iterrows():
            cols = st.columns([3,2,2,6])
            cols[0].markdown(f"**{row['title'] or '(no title)'}**")
            cols[1].markdown(row["kind"] or "-")
            if row["url"]:
                cols[2].markdown(f"[URL]({row['url']})")
            else:
                cols[2].markdown("-")
            if row["local_path"]:
                cols[3].markdown(f"`{row['local_path']}`")
            else:
                cols[3].markdown("-")

def page_notes():
    st.subheader("カルテ（経過記録）")
    pr_all = df_query("SELECT * FROM projects ORDER BY updated_at DESC")
    if pr_all.empty:
        st.info("案件がまだありません。まず『案件』から追加してください。")
        return
    pid = st.selectbox("案件を選択", pr_all["id"].tolist(), format_func=lambda _id: f"{_id}: {pr_all.set_index('id').loc[_id, 'title']}")
    proj = pr_all.set_index("id").loc[pid].to_dict()
    st.markdown(f"**{proj['title']}** — {status_badge(proj['status'])} / {proj['owner'] or '担当未設定'} / 期限: {proj['due_date'] or '-'}")

    st.markdown("#### 新規記録")
    col1, col2, col3 = st.columns(3)
    note_date = col1.date_input("記録日", value=date.today())
    author = col2.text_input("記録者")
    progress = col3.slider("進捗(%)", 0, 100, 0, 5)
    content = st.text_area("経過・所見", height=120)
    next_action = st.text_input("次アクション")
    if st.button("記録を追加", type="primary"):
        if not content.strip():
            st.warning("経過・所見を入力してください。")
        else:
            exec_sql("""
                INSERT INTO notes (project_id, note_date, author, content, next_action, progress_percent, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (pid, note_date.isoformat(), author or None, content.strip(), next_action or None, int(progress), now_str(), now_str()))
            st.success("記録を追加しました。左の再実行ボタンで更新されます。")

    st.markdown("#### 記録一覧")
    notes_df = df_query("SELECT * FROM notes WHERE project_id=? ORDER BY note_date DESC, updated_at DESC", (pid,))
    if notes_df.empty:
        st.info("まだ記録がありません。")
    else:
        st.dataframe(notes_df[["id","note_date","author","progress_percent","content","next_action","updated_at"]], use_container_width=True, height=360)

def page_resources():
    st.subheader("資料（Drive/Web/ローカルアップロード）")
    pr_all = df_query("SELECT * FROM projects ORDER BY updated_at DESC")
    pid = st.selectbox("紐づける案件（任意）", [None] + pr_all["id"].tolist(), format_func=lambda x: "（未紐づけ）" if x is None else f"{x}: {pr_all.set_index('id').loc[x, 'title']}")
    col1, col2 = st.columns(2)
    title = col1.text_input("タイトル")
    kind = col2.selectbox("種別", ["Drive","Web","Image","Local","Other"], index=1)
    url = st.text_input("外部URL（Google Drive/Notion/サイト等）", placeholder="https://...")
    note = st.text_area("メモ")
    tags = st.text_input("タグ（,区切り）")
    up = st.file_uploader("ローカルファイルのアップロード（任意）", accept_multiple_files=True)
    if st.button("登録", type="primary"):
        local_path = None
        if up:
            # 保存は1つ目のみ記録（複数はアイテム分け推奨）
            saved_paths = []
            for f in up:
                p = save_uploaded_file(f, prefix="res-")
                saved_paths.append(p)
            local_path = ";".join(saved_paths)
        exec_sql("""
            INSERT INTO resources (project_id, title, kind, url, local_path, tags, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pid, title or None, kind, url or None, local_path or None, tags or None, note or None, now_str(), now_str()))
        st.success("登録しました。")

    st.markdown("#### 一覧")
    rdf = df_query("""
        SELECT resources.*, projects.title AS project_title
        FROM resources LEFT JOIN projects ON projects.id=resources.project_id
        ORDER BY resources.updated_at DESC
    """)
    if rdf.empty:
        st.info("まだ資料がありません。")
    else:
        st.dataframe(rdf[["id","project_title","title","kind","url","local_path","tags","updated_at"]], use_container_width=True)

def page_ideas():
    st.subheader("アイディアボード（URL/画像メモ）")
    pr_all = df_query("SELECT * FROM projects ORDER BY updated_at DESC")
    pid = st.selectbox("紐づけ案件（任意）", [None] + pr_all["id"].tolist(), format_func=lambda x: "（未紐づけ）" if x is None else f"{x}: {pr_all.set_index('id').loc[x, 'title']}")
    col1, col2 = st.columns(2)
    title = col1.text_input("タイトル")
    url = col2.text_input("参考URL", placeholder="https://...")
    note = st.text_area("メモ")
    tags = st.text_input("タグ（,区切り）")
    pinned = st.checkbox("ピン留め", value=False)
    img = st.file_uploader("画像アップロード（任意）", type=["png","jpg","jpeg","webp"])
    image_path = None
    if img is not None:
        image_path = save_uploaded_file(img, prefix="idea-")
    if st.button("追加", type="primary"):
        exec_sql("""
            INSERT INTO ideas (project_id, title, url, image_path, note, tags, pinned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pid, title or None, url or None, image_path or None, note or None, tags or None, 1 if pinned else 0, now_str(), now_str()))
        st.success("追加しました。")
    st.markdown("#### 一覧 & ピン留め")
    idf = df_query("""
        SELECT ideas.*, projects.title AS project_title
        FROM ideas LEFT JOIN projects ON projects.id=ideas.project_id
        ORDER BY pinned DESC, updated_at DESC
    """)
    if idf.empty:
        st.info("まだアイディアがありません。")
    else:
        for _, row in idf.iterrows():
            with st.container(border=True):
                st.markdown(f"**{row['title'] or '(no title)'}**  {'📌' if row['pinned'] else ''}")
                st.caption(f"{row['project_title'] or '未紐づけ'} | {row['tags'] or ''}")
                cols = st.columns([3,7])
                if row["image_path"] and os.path.exists(row["image_path"]):
                    cols[0].image(row["image_path"], use_column_width=True)
                if row["url"]:
                    cols[1].markdown(f"[{row['url']}]({row['url']})")
                if row["note"]:
                    cols[1].markdown(row["note"])

def page_settings():
    st.subheader("設定 / インポート・エクスポート")
    st.caption("CSVでバックアップできます。DBファイル(data.db)もそのまま持ち出せます。")
    colA, colB = st.columns(2)
    if colA.button("projects.csv エクスポート"):
        df = df_query("SELECT * FROM projects")
        st.download_button("ダウンロード: projects.csv", df.to_csv(index=False).encode("utf-8-sig"), file_name="projects.csv", mime="text/csv")
    if colB.button("notes.csv エクスポート"):
        df = df_query("SELECT * FROM notes")
        st.download_button("ダウンロード: notes.csv", df.to_csv(index=False).encode("utf-8-sig"), file_name="notes.csv", mime="text/csv")
    if st.button("resources.csv エクスポート"):
        df = df_query("SELECT * FROM resources")
        st.download_button("ダウンロード: resources.csv", df.to_csv(index=False).encode("utf-8-sig"), file_name="resources.csv", mime="text/csv")
    if st.button("ideas.csv エクスポート"):
        df = df_query("SELECT * FROM ideas")
        st.download_button("ダウンロード: ideas.csv", df.to_csv(index=False).encode("utf-8-sig"), file_name="ideas.csv", mime="text/csv")

    st.markdown("---")
    st.markdown("##### DBの初期化（注意！）")
    if st.button("空のDBを再作成する（全削除）", type="secondary"):
        with closing(get_conn()) as conn:
            cur = conn.cursor()
            for t in ["notes","projects","resources","ideas"]:
                cur.execute(f"DROP TABLE IF EXISTS {t};")
            conn.commit()
        init_db()
        st.success("データベースを初期化しました。")

# ---------- App ----------
st.set_page_config(page_title="案件カルテ v2", page_icon="🗂️", layout="wide")
st.title("🗂️ 案件カルテ v2 — Drive/URL/画像リンク & アイディアボード")

with st.sidebar:
    st.header("メニュー")
    page = st.radio("ページ", ["ダッシュボード","案件","カルテ","資料","アイディア","設定"], index=0)
    st.divider()
    st.caption("通知の代わりに『見たい時に一発で引けるUI』を重視。")

init_db()

if page == "ダッシュボード":
    page_dashboard()
elif page == "案件":
    page_projects()
elif page == "カルテ":
    page_notes()
elif page == "資料":
    page_resources()
elif page == "アイディア":
    page_ideas()
else:
    page_settings()
