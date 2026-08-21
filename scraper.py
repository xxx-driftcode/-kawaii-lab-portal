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
# SCHEDULEは複数月分を取得するため、上限を高めに設定
SCHEDULE_MAX_ITEMS = 100
# SCHEDULEを何ヶ月先まで取得するか（安全装置。これ以上は取得しない）
SCHEDULE_MONTHS_TO_FETCH = 8


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

    このページは見た目上は無限スクロールだが、実際は月ごとに
    ?year=YYYY&month=MM というURLパラメータでページが分かれている
    （「NEXT MONTH」リンクの参照先から判明）。

    無限スクロールを模倣してJSに追加読み込みさせる方法だと、
    継ぎ足された月の「年見出し」がDOMに反映されないという問題があったため、
    代わりに月ごとのURLに直接1ページずつアクセスする。
    各ページには必ずその月専用の正しい年見出しが表示されているので、
    推測に頼らず確実に年を取得できる。
    """
    base_url = f"{group['base']}/live_information/schedule/list"

    # まず基準ページ（パラメータ無し＝サイトが「今」とみなしている月）にアクセスし、
    # 実際に表示されている年見出しから開始年月を取得する
    await page.goto(base_url, wait_until="networkidle", timeout=30000)

    try:
        header = await page.eval_on_selector(
            ".block--month .tit",
            """el => {
                // <p class="tit">08<span>2026</span></p> のうち、
                // spanの外側にある直接のテキスト（月部分）だけを取り出す
                let monthText = '';
                el.childNodes.forEach(function (node) {
                    if (node.nodeType === Node.TEXT_NODE) {
                        monthText += node.textContent;
                    }
                });
                var yearEl = el.querySelector('span');
                return {
                    month: monthText.trim(),
                    year: yearEl ? yearEl.textContent.trim() : ''
                };
            }"""
        )
        year = int(header["year"])
        month = int(header["month"])
        print(f"  [SCHEDULE] 基準月を検出: {year}年{month}月")
    except Exception as e:
        # 万一、年見出しの取得に失敗した場合は、実行時点の年月を基準にする
        now = datetime.now()
        year, month = now.year, now.month
        print(f"  [SCHEDULE] 年見出しの検出に失敗（{e}）。{year}年{month}月を基準に続行します")

    items = []

    for _ in range(SCHEDULE_MONTHS_TO_FETCH):
        month_url = f"{base_url}/?viewMode=default&year={year}&month={month:02d}"
        print(f"  [SCHEDULE] {month_url} にアクセス中...")
        await page.goto(month_url, wait_until="networkidle", timeout=30000)

        raw_items = await page.eval_on_selector_all(
            "a[href*='/live_information/detail/'], a[href*='/news/detail/']",
            """els => els.map(el => ({
                title: el.textContent.trim(),
                url: el.href
            })).filter(item => item.title.length > 0)"""
        )

        if not raw_items:
            print(f"  [SCHEDULE] {year}年{month}月は0件のため、これ以降の取得を打ち切ります")
            break

        for raw in raw_items:
            parsed = parse_schedule_item(raw["title"], raw["url"])
            parsed["year"] = str(year)
            items.append(parsed)

        # 次の月へ進める（12月の次は翌年の1月）
        month += 1
        if month > 12:
            month = 1
            year += 1

        if len(items) >= SCHEDULE_MAX_ITEMS:
            break

    print(f"  [SCHEDULE] 計{len(items)}件読み込み")
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
