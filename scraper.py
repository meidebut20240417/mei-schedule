import json
import os
import re
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright


BASE = "https://me-i.jp"

START_YEAR = 2024
START_MONTH = 4

MONTHS_AHEAD = 12

JST = timezone(timedelta(hours=9))

CACHE_FILE = "schedule.json"


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


MEMBERS = {
    "MOMONA": "momona",
    "RAN": "ran",
    "COCORO": "cocoro",
    "MIU": "miu",
    "SUZU": "suzu",
    "SHIZUKU": "shizuku",
    "AYANE": "ayane",
    "KEIKO": "keiko",
    "KOKONA": "kokona",
    "RINON": "rinon",
    "TSUZUMI": "tsuzumi",
}


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
                page.wait_for_timeout(300)
                return
        except:
            pass


def clean_text(text):
    text = text.strip()
    return re.sub(r"\s+", " ", text)


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


def normalize_url(href):
    if not href:
        return ""

    if href.startswith("http://") or href.startswith("https://"):
        return href

    if href.startswith("/"):
        return BASE + href

    return BASE + "/" + href


def load_cache():
    """
    既存の schedule.json を読み込み、
    URLをキーにした辞書を作る。
    """

    if not os.path.exists(CACHE_FILE):
        print("No cache file found.")
        return {}

    try:
        with open(
            CACHE_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        events = data.get("events", [])

        cache = {}

        for event in events:
            url = event.get("url", "")

            if url:
                cache[url] = event

        print(
            f"Loaded cache: {len(cache)} events"
        )

        return cache

    except Exception as e:
        print(
            f"Cache load error: {e}"
        )

        return {}


def extract_detail_links(page):
    result = []

    links = page.locator(
        'a[href*="/schedule/detail/"]'
    )

    count = links.count()

    for i in range(count):
        try:
            link = links.nth(i)

            href = link.get_attribute("href")

            if not href:
                continue

            text = clean_text(
                link.inner_text()
            )

            result.append({
                "text": text,
                "url": normalize_url(href)
            })

        except:
            pass

    return result


def find_best_detail_url(title, link_data):
    if not title:
        return ""

    normalized_title = re.sub(
        r"\s+",
        "",
        title
    )

    best_url = ""
    best_score = 0

    for item in link_data:
        link_text = item["text"]

        if not link_text:
            continue

        normalized_link = re.sub(
            r"\s+",
            "",
            link_text
        )

        score = 0

        if normalized_title in normalized_link:
            score = len(normalized_title)

        elif normalized_link in normalized_title:
            score = len(normalized_link)

        else:
            common = 0

            for a, b in zip(
                normalized_title,
                normalized_link
            ):
                if a != b:
                    break

                common += 1

            score = common

        if score > best_score:
            best_score = score
            best_url = item["url"]

    if best_score < 4:
        return ""

    return best_url


def parse_month(page, year, month):
    body = page.locator(
        "body"
    ).inner_text()

    lines = []

    for line in body.splitlines():
        line = clean_text(line)

        if line:
            lines.append(line)

    link_data = extract_detail_links(page)

    events = []

    current_day = None
    current_category = None

    seen = set()

    for line in lines:

        if re.fullmatch(r"\d{1,2}", line):
            day = int(line)

            if 1 <= day <= 31:
                current_day = day
                current_category = None

            continue


        if line in CATEGORIES:
            current_category = line
            continue


        found_category = None

        for cat in CATEGORIES:
            if line.startswith(cat + " "):
                found_category = cat
                break


        if found_category:
            if current_day is None:
                continue

            title_with_time = line[
                len(found_category):
            ].strip()

            if not title_with_time:
                continue

            event_time = extract_time(
                title_with_time
            )

            title = remove_time_from_title(
                title_with_time
            )

            if len(title) < 2:
                continue

            detail_url = find_best_detail_url(
                title_with_time,
                link_data
            )

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
                    "url": detail_url
                })

            current_category = None
            continue


        if (
            current_category
            and current_day is not None
        ):

            ignored_lines = [
                "Mon",
                "Tue",
                "Wed",
                "Thu",
                "Fri",
                "Sat",
                "Sun",
                "SCHEDULE",
                "PREV MONTH",
                "NEXT MONTH",
                "ALL",
            ]

            if line in ignored_lines:
                current_category = None
                continue

            title_with_time = line

            event_time = extract_time(
                title_with_time
            )

            title = remove_time_from_title(
                title_with_time
            )

            if len(title) >= 2:
                detail_url = find_best_detail_url(
                    title_with_time,
                    link_data
                )

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
                        "url": detail_url
                    })

            current_category = None

    return events


def detect_members(detail_text):
    upper_text = detail_text.upper()

    found = []

    pattern = (
        r"([A-Z、,\s]{2,100})"
        r"(?:が|は)"
        r".{0,20}"
        r"出演"
    )

    matches = re.findall(
        pattern,
        upper_text
    )

    for member_name, slug in MEMBERS.items():

        for block in matches:
            if member_name in block:
                found.append(slug)
                break

    if found:
        return found

    return "ALL"


def enrich_members(
    page,
    events,
    cache
):
    """
    キャッシュに存在するイベントは
    詳細ページを再取得しない。
    """

    total = len(events)

    cache_hits = 0
    new_fetches = 0

    for index, event in enumerate(
        events,
        start=1
    ):
        url = event.get("url", "")

        print(
            f"  detail {index}/{total}: "
            f"{event['title']}"
        )

        if not url:
            print("    no detail url")
            continue


        # -------------------------
        # キャッシュ利用
        # -------------------------
        if url in cache:

            old = cache[url]

            event["members"] = old.get(
                "members",
                "ALL"
            )

            # noteを将来使う場合も再利用
            event["note"] = old.get(
                "note",
                ""
            )

            cache_hits += 1

            print(
                f"    CACHE HIT: "
                f"{event['members']}"
            )

            continue


        # -------------------------
        # 新規イベントのみアクセス
        # -------------------------
        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            page.wait_for_timeout(400)

            close_cookie(page)

            detail_text = page.locator(
                "body"
            ).inner_text()

            members = detect_members(
                detail_text
            )

            event["members"] = members

            new_fetches += 1

            print(
                f"    NEW FETCH: {members}"
            )

        except Exception as e:
            print(
                f"    detail error: {e}"
            )

    print()
    print(
        f"CACHE HITS: {cache_hits}"
    )
    print(
        f"NEW DETAIL FETCHES: {new_fetches}"
    )

    return events


def scrape():
    all_events = []

    # 既存JSONをキャッシュとして読み込む
    cache = load_cache()

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


        # -------------------------
        # 一覧ページ取得
        # -------------------------
        for year, month in months:

            now = datetime.now(JST)

            if (
                year == now.year
                and month == now.month
            ):
                url = (
                    f"{BASE}/schedule/list/"
                )

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

                page.wait_for_timeout(800)

                close_cookie(page)

                events = parse_month(
                    page,
                    year,
                    month
                )

                print(
                    f"  events found: "
                    f"{len(events)}"
                )

                all_events.extend(events)

            except Exception as e:
                print(
                    f"  LIST ERROR: {e}"
                )


        # -------------------------
        # 重複除去
        # -------------------------
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


        print()
        print(
            f"Unique events: "
            f"{len(unique_events)}"
        )


        # -------------------------
        # キャッシュ付き詳細取得
        # -------------------------
        unique_events = enrich_members(
            page,
            unique_events,
            cache
        )

        browser.close()

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
        CACHE_FILE,
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
    print("=" * 50)

    print(
        f"TOTAL EVENTS: "
        f"{len(events)}"
    )

    specific = [
        event
        for event in events
        if event["members"] != "ALL"
    ]

    print(
        "EVENTS WITH SPECIFIC MEMBERS: "
        f"{len(specific)}"
    )

    print("=" * 50)


if __name__ == "__main__":
    main()
