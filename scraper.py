import json
import re
import time
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright


BASE = "https://me-i.jp"

# 過去の取得開始
START_YEAR = 2024
START_MONTH = 4

# 未来何か月先まで取得するか
MONTHS_AHEAD = 12

JST = timezone(timedelta(hours=9))

CATEGORY_KEYWORDS = [
    "LIVE／EVENT",
    "WEB MEDIA",
    "RELEASE",
    "TV",
    "RADIO",
    "MAGAZINE",
    "BIRTHDAY",
    "OTHER",
]

WEEKDAYS = {
    "Mon": "Mon",
    "Tue": "Tue",
    "Wed": "Wed",
    "Thu": "Thu",
    "Fri": "Fri",
    "Sat": "Sat",
    "Sun": "Sun",
}


def get_months():
    """
    2024年4月から現在+12か月までの
    (year, month) を作る
    """

    now = datetime.now(JST)

    end_year = now.year
    end_month = now.month + MONTHS_AHEAD

    while end_month > 12:
        end_year += 1
        end_month -= 12

    months = []

    year = START_YEAR
    month = START_MONTH

    while True:
        months.append((year, month))

        if year == end_year and month == end_month:
            break

        month += 1

        if month > 12:
            month = 1
            year += 1

    return months


def parse_events_from_page(page, year, month):
    """
    ページ上のイベント詳細リンクを直接取得する。
    """

    events = []

    # /schedule/detail/1234 のリンクを全部取得
    links = page.locator('a[href*="/schedule/detail/"]')

    count = links.count()

    print(f"  detail links: {count}")

    seen_ids = set()

    for i in range(count):

        try:
            link = links.nth(i)

            href = link.get_attribute("href")

            if not href:
                continue

            match = re.search(r"/schedule/detail/(\d+)", href)

            if not match:
                continue

            event_id = int(match.group(1))

            if event_id in seen_ids:
                continue

            seen_ids.add(event_id)

            text = link.inner_text().strip()

            # 親要素のテキストも取得
            parent_text = ""

            try:
                parent_text = link.locator("xpath=..").inner_text().strip()
            except:
                parent_text = ""

            events.append({
                "id": event_id,
                "year": year,
                "month": month,
                "raw_text": text,
                "parent_text": parent_text,
                "url": f"{BASE}/schedule/detail/{event_id}"
            })

        except Exception as e:
            print(f"    link error: {e}")

    return events


def parse_detail_page(page, event):

    """
    詳細ページからタイトル・カテゴリ・時間などを取得する
    """

    try:

        page.goto(
            event["url"],
            wait_until="domcontentloaded",
            timeout=30000
        )

        time.sleep(0.5)

        body = page.locator("body").inner_text()

    except Exception as e:

        print(f"    detail failed: {event['url']}")

        return None

    lines = [
        line.strip()
        for line in body.splitlines()
        if line.strip()
    ]

    title = ""
    category = ""
    event_date = ""

    # カテゴリを探す
    for line in lines:

        if line in CATEGORY_KEYWORDS:

            category = line
            break

    # 詳細ページの上の方からタイトル候補を探す
    if lines:

        title = lines[0]

    # 日付を探す
    date_match = re.search(
        r"(20\d{2})[./年](\d{1,2})[./月](\d{1,2})",
        body
    )

    if date_match:

        event["year"] = int(date_match.group(1))
        event["month"] = int(date_match.group(2))
        event["day"] = int(date_match.group(3))

    else:

        # 一覧ページの月を利用
        event["day"] = None

    # 時刻を探す
    time_matches = re.findall(
        r"\d{1,2}:\d{2}(?:\s*[-〜～]\s*\d{1,2}:\d{2})?",
        body
    )

    event_time = ""

    if time_matches:
        event_time = time_matches[0]

    return {
        "id": event["id"],
        "year": event["year"],
        "month": event["month"],
        "day": event["day"],
        "cat": category,
        "title": title,
        "time": event_time,
        "members": "ALL",
        "note": "",
        "url": event["url"]
    }


def scrape():

    all_events = []
    seen_ids = set()

    months = get_months()

    print(f"months to check: {len(months)}")

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            locale="ja-JP"
        )

        for year, month in months:

            if (
                year == datetime.now(JST).year
                and month == datetime.now(JST).month
            ):
                url = f"{BASE}/schedule/list/"
            else:
                url = f"{BASE}/schedule/list/{year}/{month}/"

            print()
            print(f"[{year}-{month:02d}] {url}")

            try:

                page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=30000
                )

                time.sleep(1)

            except Exception as e:

                print(f"  page load failed: {e}")

                continue

            events = parse_events_from_page(
                page,
                year,
                month
            )

            print(f"  events found: {len(events)}")

            for event in events:

                if event["id"] in seen_ids:
                    continue

                seen_ids.add(event["id"])

                detail = parse_detail_page(
                    page,
                    event
                )

                if detail:
                    all_events.append(detail)


    return all_events


def main():

    events = scrape()

    # 日付順に並び替え
    events.sort(
        key=lambda e: (
            e["year"],
            e["month"],
            e["day"] if e["day"] else 99,
            e["id"]
        )
    )

    output = {
        "generated_at": datetime.now(JST).isoformat(),
        "events": events
    }

    with open(
        "schedule.json",
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )

    print()
    print("=" * 40)
    print(f"TOTAL EVENTS: {len(events)}")
    print("=" * 40)


if __name__ == "__main__":
    main()
