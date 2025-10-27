# 🗂️ 案件カルテ v2 — Drive/URL/画像リンク & アイディアボード

病院カルテっぽい進捗管理に **資料リンク管理** と **アイディアボード** を追加。  
- Google Drive/Notion/任意URLを保存.
- ローカルファイルを `uploads/` にアップロード
- 参考URLや画像をPinterest的に集約、ピン留め可能
- 自然文っぽい横断検索（projects/notes/resources/ideas を一括）

## 使い方（ローカル）
```bash
pip install -r requirements.txt
streamlit run app.py
```

## デプロイ（Streamlit Community Cloud）
1. このディレクトリをGitHubにpush
2. StreamlitでNew app → リポジトリを選択 → `app.py` を指定

## 運用のコツ（通知を使わない前提）
- 「ダッシュボード」で期限近い案件&進行中が一目で分かる
- 「資料」ページでリンク&ファイルを一元管理（Driveリンク推奨）
- 「アイディア」ページに参考URLや画像をクリップ、ピン留めで固定
- 検索ボックスで自然文っぽく横断検索（例: *来週 期限*、*A社 最新 資料*）

## 将来の拡張（任意）
- Google Drive APIでフォルダ自動作成＆アップロード
- Notion/Slack連携（通知は控えめに）
- カレンダー（期限のみ書き込み）
- ガント/カンバン表示
