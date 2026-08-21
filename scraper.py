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
from datetime import datetime
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


def assign_years(schedule_items):
    """
    月・日しか分からないスケジュール項目のリストに、年を割り当てる。

    サイトの並び順が時系列順（古い→新しい）であることを前提に、
    「前の項目より月が小さくなったら年をまたいだ」とみなして年を繰り上げる。
    例：...11月 → 12月 → 1月... の「1月」で年を+1する。
    """
    if not schedule_items:
        return schedule_items

    current_year = datetime.now().year
    previous_month = None

    for item in schedule_items:
        month = int(item["month"])
        if previous_month is not None and month < previous_month:
            current_year += 1
        item["year"] = str(current_year)
        previous_month = month

    return schedule_items


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
# SCHEDULEは無限スクロール型で件数が多いため、上限を高めに設定
SCHEDULE_MAX_ITEMS = 60
# 無限スクロールの最大試行回数（安全装置。これ以上はスクロールしない）
MAX_SCROLL_ATTEMPTS = 30


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
    """SCHEDULE（スケジュール）一覧を取得する

    このページは無限スクロール型（下までスクロールすると追加で読み込まれる）
    なので、ページ最下部までスクロールを繰り返し、これ以上新しい項目が
    増えなくなるまで読み込みを行う。
    """
    url = f"{group['base']}/live_information/schedule/list"
    print(f"  [SCHEDULE] {url} にアクセス中...")
    await page.goto(url, wait_until="networkidle", timeout=30000)

    previous_count = -1
    same_count_streak = 0

    for attempt in range(MAX_SCROLL_ATTEMPTS):
        # スケジュール項目は /live_information/detail/ か /news/detail/ にリンクしている
        current_count = await page.eval_on_selector_all(
            "a[href*='/live_information/detail/'], a[href*='/news/detail/']",
            "els => els.length"
        )

        if current_count == previous_count:
            same_count_streak += 1
            # 2回連続で件数が増えなければ、読み込むものがもう無いと判断して終了
            if same_count_streak >= 2:
                break
        else:
            same_count_streak = 0

        previous_count = current_count

        # ページ最下部までスクロールして、追加読み込みをトリガーする
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)

        # 十分な件数が集まったら早めに切り上げる
        if current_count >= SCHEDULE_MAX_ITEMS:
            break

    raw_items = await page.eval_on_selector_all(
        "a[href*='/live_information/detail/'], a[href*='/news/detail/']",
        """els => els.map(el => ({
            title: el.textContent.trim(),
            url: el.href
        })).filter(item => item.title.length > 0)"""
    )
    items = [parse_schedule_item(item["title"], item["url"]) for item in raw_items]
    items = assign_years(items)
    print(f"  [SCHEDULE] スクロール{attempt + 1}回、計{len(items)}件読み込み")
    return items[:SCHEDULE_MAX_ITEMS]


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
