"""
KAWAII LAB. YouTube動画取得スクリプト

5グループの公式YouTubeチャンネルから最新動画を取得し、youtube.json に保存します。

【事前準備】
1. YouTube Data API v3 のAPIキーを取得する（READMEの手順を参照）
2. 下のどちらかの方法でAPIキーをスクリプトに渡す
   A) 環境変数 YOUTUBE_API_KEY に設定する（おすすめ、GitHubにも安全）
   B) 下の API_KEY 変数に直接貼り付ける（お試し用。GitHubにアップロードしないこと）

【使い方】
python fetch_youtube.py
"""

import json
import os
import requests
from pathlib import Path

# ここに直接貼り付けてもOK。ただしGitHubにアップロードする場合は
# 必ず環境変数 or GitHub Secrets を使うこと（キーが世界中に公開されてしまうため）
API_KEY = os.environ.get("YOUTUBE_API_KEY", "ここにAPIキーを貼り付け")

OUTPUT_PATH = Path(__file__).resolve().parent / "youtube.json"

# 5グループの公式YouTubeチャンネルID
# チャンネルIDはハンドル（@〜）と違って変更されないので、これを使うのが安全
GROUPS = [
    {"id": "fruitszipper", "name": "FRUITS ZIPPER", "channel_id": "UCQG8tNnV4hKetLhMb4MopHQ"},
    {"id": "candytune",    "name": "CANDY TUNE",    "channel_id": "UCU0PgOXf0lxzVxN2TLzMJkw"},
    {"id": "sweetsteady",  "name": "SWEET STEADY",  "channel_id": "UC5s_kUbxX3P1q6lmDgygD-w"},
    {"id": "cutiestreet",  "name": "CUTIE STREET",  "channel_id": "UCEz-AFAg3EUKsxraad1puQA"},
    {"id": "morestar",     "name": "MORE STAR",     "channel_id": "UCBkLxz038AbxBA8CMw6o9oA"},
]

MAX_VIDEOS = 5


def get_uploads_playlist_id(channel_id):
    """チャンネルIDから「アップロード動画一覧」プレイリストIDを取得する"""
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        "part": "contentDetails",
        "id": channel_id,
        "key": API_KEY,
    }
    res = requests.get(url, params=params, timeout=15)
    res.raise_for_status()
    data = res.json()
    items = data.get("items", [])
    if not items:
        raise ValueError(f"チャンネルが見つかりません: {channel_id}")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_latest_videos(playlist_id, max_results=MAX_VIDEOS):
    """アップロードプレイリストから最新動画を取得する"""
    url = "https://www.googleapis.com/youtube/v3/playlistItems"
    params = {
        "part": "snippet",
        "playlistId": playlist_id,
        "maxResults": max_results,
        "key": API_KEY,
    }
    res = requests.get(url, params=params, timeout=15)
    res.raise_for_status()
    data = res.json()

    videos = []
    for item in data.get("items", []):
        snippet = item["snippet"]
        video_id = snippet["resourceId"]["videoId"]
        thumbnails = snippet.get("thumbnails", {})
        thumbnail_url = (
            thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
        )
        videos.append({
            "title": snippet["title"],
            "published_at": snippet["publishedAt"],
            "thumbnail_url": thumbnail_url,
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
        })
    return videos


def main():
    if not API_KEY or API_KEY == "ここにAPIキーを貼り付け":
        print("エラー: APIキーが設定されていません。")
        print("fetch_youtube.py 内の API_KEY を書き換えるか、")
        print("環境変数 YOUTUBE_API_KEY を設定してください。")
        return

    results = {}
    for group in GROUPS:
        print(f"=== {group['name']} を取得中 ===")
        try:
            uploads_id = get_uploads_playlist_id(group["channel_id"])
            videos = get_latest_videos(uploads_id)
            results[group["id"]] = {"name": group["name"], "videos": videos}
            print(f"  → {len(videos)}件 取得")
        except Exception as e:
            print(f"  エラー: {e}")
            results[group["id"]] = {"name": group["name"], "videos": []}

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n完了！ 保存先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
