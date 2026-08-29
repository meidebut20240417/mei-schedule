import json
import re
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright


BASE = "https://me-i.jp"

START_YEAR = 2024
START_MONTH = 4

MONTHS_AHEAD = 12

JST = timezone(timedelta(hours=9))

CATEGORIES = [
    "LIVE／EVENT",
    "WEB MEDIA",
    "RELEASE",
    "TV",
    "RADIO",
    "MAGAZINE",
    "BIRTHDAY",
    "OTHER",
]


def get_months():

    now = datetime.now(JST)

    end_year = now.year
    end_month = now.month + MONTHS_AHEAD

    while end_month > 12:
        end_month -= 12
        end_year += 1

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


def close_cookie(page):

    selectors = [
        "#onetrust-accept-btn-handler",
        'button:has-text("同意")',
        'button:has-text("Accept")',
    ]

    for selector in selectors:

        try:

            button = page.locator(selector)

            if button.count() > 0:
                button.first.click(timeout=2000)
                page.wait_for_timeout(500)
                return

        except:
            pass


def clean_text(text):

    text = text.strip()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text


def extract_time(text):

    matches = re.findall(
        r"\d{1,2}:\d{2}"
        r"(?:\s*[-〜～‐]\s*\d{1,2}:\d{2})?",
        text
    )

    if matches:
        return matches[-1]

    return ""


def remove_time_from_title(text):

    text = re.sub(
        r"\s*\d{1,2}:\d{2}"
        r"(?:\s*[-〜～‐]\s*\d{1,2}:\d{2})?",
        "",
        text
    )

    return clean_text(text)


def parse_month(page, year, month):

    body = page.locator("body").inner_text()

    lines = []

    for line in body.splitlines():

        line = clean_text(line)

        if line:
            lines.append(line)

    events = []

    current_day = None
    current_category = None

    seen = set()

    for line in lines:

        # -------------------------
        # 日付
        # -------------------------
        if re.fullmatch(r"\d{1,2}", line):

            day = int(line)

            if 1 <= day <= 31:

                current_day = day

                # 日付が変わったらカテゴリ状態をリセット
                current_category = None

            continue


        # -------------------------
        # カテゴリ単独
        #
        # TV
        # ↓
        # 番組タイトル
        #
        # のような形式に対応
        # -------------------------
        if line in CATEGORIES:

            current_category = line

            continue


        # -------------------------
        # カテゴリ＋タイトルが同じ行
        #
        # TV 番組タイトル
        #
        # のような形式に対応
        # -------------------------
        found_category = None

        for cat in CATEGORIES:

            if line.startswith(cat + " "):

                found_category = cat

                break


        if found_category:

            if current_day is None:
                continue

            title = line[len(found_category):].strip()

            if not title:
                continue

            event_time = extract_time(title)

            title = remove_time_from_title(title)

            if len(title) < 2:
                continue

            key = (
                year,
                month,
                current_day,
                found_category,
                title
            )

            if key not in seen:

                seen.add(key)

                events.append({
                    "year": year,
                    "month": month,
                    "day": current_day,
                    "cat": found_category,
                    "title": title,
                    "time": event_time,
                    "members": "ALL",
                    "note": "",
                    "url": ""
                })

            current_category = None

            continue


        # -------------------------
        # 直前の行がカテゴリだった場合
        #
        # TV
        # 番組タイトル
        # -------------------------
        if current_category and current_day is not None:

            # 明らかに関係ない行を除外
            if line in [
                "Mon", "Tue", "Wed",
                "Thu", "Fri", "Sat", "Sun",
                "SCHEDULE",
                "PREV MONTH",
                "NEXT MONTH"
            ]:

                current_category = None

                continue

            title = line

            event_time = extract_time(title)

            title = remove_time_from_title(title)

            if len(title) >= 2:

                key = (
                    year,
                    month,
                    current_day,
                    current_category,
                    title
                )

                if key not in seen:

                    seen.add(key)

                    events.append({
                        "year": year,
                        "month": month,
                        "day": current_day,
                        "cat": current_category,
                        "title": title,
                        "time": event_time,
                        "members": "ALL",
                        "note": "",
                        "url": ""
                    })

            current_category = None


    return events


def scrape():

    all_events = []

    months = get_months()

    print(
        f"Months to check: {len(months)}"
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            locale="ja-JP"
        )

        for year, month in months:

            now = datetime.now(JST)

            # 現在月だけ通常URL
            if (
                year == now.year
                and month == now.month
            ):

                url = f"{BASE}/schedule/list/"

            else:

                url = (
                    f"{BASE}/schedule/list/"
                    f"{year}/{month}/"
                )

            print()
            print(
                f"[{year}-{month:02d}] {url}"
            )

            try:

                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=30000
                )

                page.wait_for_timeout(1500)

                close_cookie(page)

                events = parse_month(
                    page,
                    year,
                    month
                )

                print(
                    f"  events found: {len(events)}"
                )

                for event in events:

                    print(
                        f"  {event['day']} "
                        f"{event['cat']} "
                        f"{event['title']}"
                    )

                all_events.extend(events)

            except Exception as e:

                print(
                    f"  ERROR: {e}"
                )

        browser.close()

    # 全体の重複除去
    unique_events = []

    seen = set()

    for event in all_events:

        key = (
            event["year"],
            event["month"],
            event["day"],
            event["cat"],
            event["title"]
        )

        if key in seen:
            continue

        seen.add(key)

        unique_events.append(event)

    return unique_events


def main():

    events = scrape()

    events.sort(
        key=lambda event: (
            event["year"],
            event["month"],
            event["day"],
            event["title"]
        )
    )

    output = {
        "generated_at":
            datetime.now(JST).isoformat(),

        "events":
            events
    }

    with open(
        "schedule.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2
        )

    print()
    print("=" * 40)
    print(
        f"TOTAL EVENTS: {len(events)}"
    )
    print("=" * 40)


if __name__ == "__main__":
    main()
