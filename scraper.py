#!/usr/bin/env python3
"""
me-i.jp のスケジュールページを定期的に取得し、schedule.json に書き出すスクレイパー。

【注意】
このスクリプトは GitHub Actions 上で実行される前提で書かれています。
作者（Claude）の作業環境からは me-i.jp に直接アクセスできないため、
実際のサイトに対して一度も実行・検証できていません。
初回は必ず手動実行（workflow_dispatch）して schedule.json の中身を
目視で確認してください。サイトの表記が変わると正規表現の調整が必要になります。

出力形式（schedule.json）:
{
  "generated_at": "2026-08-29T12:00:00+09:00",
  "events": [
    {
      "id": 1360,
      "year": 2026, "month": 8, "day": 1, "wd": "Sat",
      "cat": "TV",
      "title": "KBC『#タグるヨル』",
      "time": "24:20-24:50",
      "members": ["tsuzumi"],   // 特定できない場合は "ALL"
      "note": "",
      "url": "https://me-i.jp/schedule/detail/1360"
    },
    ...
  ]
}
"""

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright

BASE = "https://me-i.jp"

# 何ヶ月分を取得するか（現在月を基準に前後何ヶ月）。必要に応じて調整してください。
MONTHS_BEFORE = 1
MONTHS_AFTER = 3

# メンバー名の表記ゆれを吸収するための対応表（詳細ページの「〇〇が出演いたします」を判定する）
MEMBER_NAMES = {
    "MIU": "miu",
    "MOMONA": "momona",
    "AYANE": "ayane",
    "KEIKO": "keiko",
    "RINON": "rinon",
    "SUZU": "suzu",
    "TSUZUMI": "tsuzumi",
}

CATEGORY_KEYWORDS = ["RELEASE", "LIVE", "TV", "RADIO", "MAGAZINE", "WEB", "BIRTHDAY", "OTHER"]

WD_JP2EN = {"日": "Sun", "月": "Mon", "火": "Tue", "水": "Wed", "木": "Thu", "金": "Fri", "土": "Sat"}


def month_range(months_before: int, months_after: int):
    """(year, month) のタプルを、現在月を基準に前後で列挙する。"""
    now = datetime.now(timezone(timedelta(hours=9)))  # JST基準
    y, m = now.year, now.month
    results = []
    for offset in range(-months_before, months_after + 1):
        total = (y * 12 + (m - 1)) + offset
        yy, mm = divmod(total, 12)
        results.append((yy, mm + 1))
    return results


def parse_list_page(text: str, year: int, month: int):
    """
    一覧ページの本文テキストから予定を抽出する。
    サイトの表記が変わった場合はここの正規表現を調整してください。

    想定している行の形（例）:
      "08.15 Sat" のような日付見出しの後に、
      "TV" のような媒体区分、タイトル、時刻、詳細リンクが続く。
    """
    events = []

    # 日付見出し: 08.15 Sat / 08.15 (Sat) など表記ゆれに少し幅を持たせる
    date_pat = re.compile(r"(\d{1,2})\.(\d{1,2})\s*\(?([A-Za-z]{3})\)?")
    # 詳細リンク: /schedule/detail/1234
    link_pat = re.compile(r"/schedule/detail/(\d+)")
    # 時刻: 18:00-18:55 や 24:20-24:50
    time_pat = re.compile(r"\d{1,2}:\d{2}(-\d{1,2}:\d{2})?")

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    current_day = None
    current_wd = None

    i = 0
    while i < len(lines):
        line = lines[i]

        m = date_pat.match(line)
        if m:
            current_day = int(m.group(2))
            current_wd = m.group(3)
            i += 1
            continue

        cat_match = next((c for c in CATEGORY_KEYWORDS if line.startswith(c)), None)
        if cat_match and current_day:
            # このブロックから、次の日付見出しか次のカテゴリ行までを1イベントとみなす
            title = line[len(cat_match):].strip(" 　:：")
            block = [line]
            j = i + 1
            while j < len(lines) and not date_pat.match(lines[j]) and not any(
                lines[j].startswith(c) for c in CATEGORY_KEYWORDS
            ):
                block.append(lines[j])
                j += 1

            block_text = " ".join(block)
            time_m = time_pat.search(block_text)
            link_m = link_pat.search(block_text)

            if not title:
                # タイトルが次の行にある場合
                for b in block[1:]:
                    if not time_pat.fullmatch(b) and not link_pat.search(b):
                        title = b
                        break

            events.append({
                "id": int(link_m.group(1)) if link_m else None,
                "year": year,
                "month": month,
                "day": current_day,
                "wd": current_wd,
                "cat": cat_match,
                "title": title or "(タイトル取得失敗)",
                "time": time_m.group(0) if time_m else "",
                "members": "ALL",
                "note": "",
                "url": f"{BASE}/schedule/detail/{link_m.group(1)}" if link_m else "",
            })
            i = j
            continue

        i += 1

    # id が取れなかったものは detail 追跡できないので除外
    return [e for e in events if e["id"]]


def detect_members(detail_text: str):
    """詳細ページの本文から「〇〇が出演いたします」的な記述を拾ってメンバーを特定する。"""
    found = []
    for name, slug in MEMBER_NAMES.items():
        if name in detail_text.upper():
            found.append(slug)
    return found if found else "ALL"


def scrape():
    all_events = []
    seen_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="ja-JP")

        for year, month in month_range(MONTHS_BEFORE, MONTHS_AFTER):
            url = f"{BASE}/schedule/list/{year}/{month}"
            print(f"[list] {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
                time.sleep(1)  # 念のため描画待ち
                body_text = page.inner_text("body")
            except Exception as ex:
                print(f"  !! failed to load list page: {ex}", file=sys.stderr)
                continue

            month_events = parse_list_page(body_text, year, month)
            print(f"  -> {len(month_events)} events found")

            for ev in month_events:
                if ev["id"] in seen_ids:
                    continue
                seen_ids.add(ev["id"])

                # LIVE/RELEASE は基本フルメンバーなので詳細ページは見に行かない（負荷軽減）
                if ev["cat"] not in ("LIVE", "RELEASE"):
                    try:
                        page.goto(ev["url"], wait_until="networkidle", timeout=30000)
                        time.sleep(0.5)
                        detail_text = page.inner_text("body")
                        ev["members"] = detect_members(detail_text)
                    except Exception as ex:
                        print(f"  !! failed to load detail page {ev['url']}: {ex}", file=sys.stderr)

                all_events.append(ev)

        browser.close()

    return all_events


def main():
    events = scrape()
    events.sort(key=lambda e: (e["year"], e["month"], e["day"], e["id"]))

    output = {
        "generated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "events": events,
    }

    with open("schedule.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(events)} events to schedule.json")


if __name__ == "__main__":
    main()
