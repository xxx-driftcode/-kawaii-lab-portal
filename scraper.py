"""
KAWAII LAB. 公式サイト スクレイピングスクリプト

5グループ（FRUITS ZIPPER / CANDY TUNE / SWEET STEADY / CUTIE STREET / MORE STAR）
の公式サイトから INFORMATION と SCHEDULE を取得し、output.json に保存します。

【使い方】
1. 必要なパッケージをインストール（README.md 参照）
2. python scraper.py を実行
3. output.json が生成されるので中身を確認する

公式サイトは JavaScript でコンテンツを描画しているため、
単純な HTTP リクエストでは中身が取得できません。
Playwright でブラウザを自動操作し、描画後の HTML から情報を抜き出します。
"""

import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

# scraper.py 自身があるフォルダに output.json を保存する
# （どこのディレクトリから実行しても、常に同じ場所に保存されるようにするため）
OUTPUT_PATH = Path(__file__).resolve().parent / "output.json"

# SCHEDULEのカテゴリ一覧（公式サイトのフィルターボタンと同じ）
SCHEDULE_CATEGORIES = ["LIVE", "EVENT", "TV", "RADIO", "MAGAZINE", "WEB", "OTHER"]
SCHEDULE_PATTERN = re.compile(
    r"^(\d{2})\s+(\d{2})\s+\[(\w+)\]\s+(" + "|".join(SCHEDULE_CATEGORIES) + r")\s+(.+)$"
)


def parse_info_item(raw_title, url):
    """INFOの生テキスト（日付+タイトルが改行で連結されたもの）を分離する"""
    parts = raw_title.split("\n", 1)
    if len(parts) == 2:
        date, title = parts
    else:
        date, title = "", raw_title
    return {"date": date.strip(), "title": title.strip(), "url": url}


def parse_schedule_item(raw_title, url):
    """SCHEDULEの生テキスト（月/日/曜日/カテゴリ/タイトルが空白で連結されたもの）を分離する"""
    normalized = re.sub(r"\s+", " ", raw_title).strip()
    m = SCHEDULE_PATTERN.match(normalized)
    if m:
        month, day, dow, category, title = m.groups()
        return {
            "month": month,
            "day": day,
            "day_of_week": dow,
            "category": category,
            "title": title.strip(),
            "url": url,
        }
    # 想定外のフォーマットの場合は生データをそのまま入れておく（後で気づけるように）
    return {"title": normalized, "url": url, "unparsed": True}

# ここに5グループの情報をまとめる。グループを増減したい場合はこのリストを編集する。
GROUPS = [
    {"id": "fruitszipper", "name": "FRUITS ZIPPER", "base": "https://fruitszipper.asobisystem.com"},
    {"id": "candytune",    "name": "CANDY TUNE",    "base": "https://candytune.asobisystem.com"},
    {"id": "sweetsteady",  "name": "SWEET STEADY",  "base": "https://sweetsteady.asobisystem.com"},
    {"id": "cutiestreet",  "name": "CUTIE STREET",  "base": "https://cutiestreet.asobisystem.com"},
    {"id": "morestar",     "name": "MORE STAR",     "base": "https://morestar.asobisystem.com"},
]

# 各セクションで何件まで取得するか
MAX_ITEMS = 10


async def scrape_info(page, group):
    """INFORMATION（お知らせ）一覧を取得する"""
    url = f"{group['base']}/news/1"
    print(f"  [INFO] {url} にアクセス中...")
    await page.goto(url, wait_until="networkidle", timeout=30000)

    # /news/detail/ を含むリンクを記事とみなして抽出する
    raw_items = await page.eval_on_selector_all(
        "a[href*='/news/detail/']",
        """els => els.map(el => ({
            title: el.textContent.trim(),
            url: el.href
        })).filter(item => item.title.length > 0)"""
    )
    items = [parse_info_item(item["title"], item["url"]) for item in raw_items]
    return items[:MAX_ITEMS]


async def scrape_schedule(page, group):
    """SCHEDULE（スケジュール）一覧を取得する"""
    url = f"{group['base']}/live_information/schedule/list"
    print(f"  [SCHEDULE] {url} にアクセス中...")
    await page.goto(url, wait_until="networkidle", timeout=30000)

    # スケジュール項目は /live_information/detail/ か /news/detail/ にリンクしている
    raw_items = await page.eval_on_selector_all(
        "a[href*='/live_information/detail/'], a[href*='/news/detail/']",
        """els => els.map(el => ({
            title: el.textContent.trim(),
            url: el.href
        })).filter(item => item.title.length > 0)"""
    )
    items = [parse_schedule_item(item["title"], item["url"]) for item in raw_items]
    return items[:MAX_ITEMS]


async def main():
    results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for group in GROUPS:
            print(f"\n=== {group['name']} を取得中 ===")
            try:
                info = await scrape_info(page, group)
            except Exception as e:
                print(f"  INFO取得でエラー: {e}")
                info = []

            try:
                schedule = await scrape_schedule(page, group)
            except Exception as e:
                print(f"  SCHEDULE取得でエラー: {e}")
                schedule = []

            results[group["id"]] = {
                "name": group["name"],
                "info": info,
                "schedule": schedule,
            }
            print(f"  → INFO {len(info)}件 / SCHEDULE {len(schedule)}件 取得")

        await browser.close()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n完了！ 保存先: {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
