import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright


BASE = "https://me-i.jp"
START_YEAR = 2024
START_MONTH = 4
MONTHS_AHEAD = 12
JST = timezone(timedelta(hours=9))
CACHE_FILE = "schedule.json"
REFRESH_PAST_DAYS = 7
MIN_EVENT_RATIO = 0.30

CATEGORIES = [
    "LIVE／EVENT", "WEB MEDIA", "RELEASE", "TV", "RADIO",
    "MAGAZINE", "BIRTHDAY", "OTHER",
]

MEMBERS = {
    "MOMONA": "momona", "RAN": "ran", "COCORO": "cocoro",
    "MIU": "miu", "SUZU": "suzu", "SHIZUKU": "shizuku",
    "AYANE": "ayane", "KEIKO": "keiko", "KOKONA": "kokona",
    "RINON": "rinon", "TSUZUMI": "tsuzumi",
}


def get_months():
    now = datetime.now(JST)
    end_year = now.year
    end_month = now.month + MONTHS_AHEAD
    while end_month > 12:
        end_month -= 12
        end_year += 1

    months = []
    year, month = START_YEAR, START_MONTH
    while True:
        months.append((year, month))
        if (year, month) == (end_year, end_month):
            return months
        month += 1
        if month > 12:
            month = 1
            year += 1


def close_cookie(page):
    for selector in [
        "#onetrust-accept-btn-handler",
        'button:has-text("同意")',
        'button:has-text("Accept")',
    ]:
        try:
            button = page.locator(selector)
            if button.count() > 0:
                button.first.click(timeout=2000)
                page.wait_for_timeout(300)
                return
        except Exception:
            pass


def clean_text(text):
    return re.sub(r"\s+", " ", str(text or "").strip())


def remove_schedule_suffix(text):
    """『番組名』後の「9/3(木)深夜」等の放送日注記だけを削除。"""
    return re.sub(
        r"(?<=[』」])\s*"
        r"\d{1,2}(?:/|月)\d{1,2}(?:日)?"
        r"\s*[（(]?[月火水木金土日][)）]?"
        r"\s*(?:深夜|午前|午後)?"
        r"(?:\s*\d{1,2}(?::\d{2}|時)(?:\d{1,2}分?)?)?"
        r"\s*$",
        "",
        clean_text(text),
    ).strip()


def extract_time(text):
    matches = re.findall(
        r"\d{1,2}:\d{2}(?:\s*[-〜～‐]\s*\d{1,2}:\d{2})?",
        text,
    )
    return matches[-1] if matches else ""


def remove_time_from_title(text):
    text = re.sub(
        r"\s*\d{1,2}:\d{2}(?:\s*[-〜～‐]\s*\d{1,2}:\d{2})?",
        "",
        text,
    )
    return remove_schedule_suffix(clean_text(text))


def normalize_event_datetime(event):
    """
    開始が24:00以上なら翌日に移し、時刻から24時間を引く。
    23:59-24:54は日付を動かさず、23:59-0:54にする。
    """
    normalized = dict(event)
    normalized["title"] = remove_schedule_suffix(normalized.get("title", ""))
    raw_time = str(normalized.get("time", "") or "").strip()
    start = re.search(r"(?<!\d)(\d{1,2}):\d{2}", raw_time)

    if start and int(start.group(1)) >= 24:
        date = datetime(
            int(normalized["year"]),
            int(normalized["month"]),
            int(normalized["day"]),
            tzinfo=JST,
        ) + timedelta(days=1)
        normalized.update(year=date.year, month=date.month, day=date.day)

    def replace_time(match):
        hour = int(match.group(1))
        if hour >= 24:
            hour -= 24
        return f"{hour}:{match.group(2)}"

    normalized["time"] = re.sub(
        r"(?<!\d)(\d{1,2}):(\d{2})",
        replace_time,
        raw_time,
    )
    return normalized


def event_sort_key(event):
    start = re.search(
        r"(?<!\d)(\d{1,2}):(\d{2})",
        event.get("time", "") or "",
    )
    time_key = (
        (0, int(start.group(1)), int(start.group(2)))
        if start else (1, 0, 0)
    )
    return (
        int(event["year"]), int(event["month"]), int(event["day"]),
        *time_key, event.get("title", ""),
    )


def normalize_url(href):
    if not href:
        return ""
    if href.startswith(("http://", "https://")):
        return href
    return BASE + (href if href.startswith("/") else "/" + href)


def load_existing_data():
    if not os.path.exists(CACHE_FILE):
        print("No existing schedule.json found.")
        return {"events": []}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        print(f"Loaded existing data: {len(data.get('events', []))} events")
        return data
    except Exception as error:
        print(f"Existing JSON load error: {error}")
        return {"events": []}


def build_cache(existing_data):
    cache = {
        event.get("url"): event
        for event in existing_data.get("events", [])
        if event.get("url")
    }
    print(f"Loaded cache: {len(cache)} events")
    return cache


def extract_detail_links(page):
    result = []
    links = page.locator('a[href*="/schedule/detail/"]')
    for index in range(links.count()):
        try:
            link = links.nth(index)
            href = link.get_attribute("href")
            if href:
                result.append({
                    "text": clean_text(link.inner_text()),
                    "url": normalize_url(href),
                })
        except Exception:
            pass
    return result


def find_best_detail_url(title, link_data):
    if not title:
        return ""
    normalized_title = re.sub(r"\s+", "", title)
    best_url, best_score = "", 0

    for item in link_data:
        normalized_link = re.sub(r"\s+", "", item["text"] or "")
        if not normalized_link:
            continue
        if normalized_title in normalized_link:
            score = len(normalized_title)
        elif normalized_link in normalized_title:
            score = len(normalized_link)
        else:
            score = 0
            for left, right in zip(normalized_title, normalized_link):
                if left != right:
                    break
                score += 1
        if score > best_score:
            best_url, best_score = item["url"], score

    return best_url if best_score >= 4 else ""


def make_event(year, month, day, category, title_with_time, link_data):
    event_time = extract_time(title_with_time)
    title = remove_time_from_title(title_with_time)
    if len(title) < 2:
        return None
    event = {
        "year": year,
        "month": month,
        "day": day,
        "cat": category,
        "title": title,
        "time": event_time,
        "members": "ALL",
        "note": "",
        "url": find_best_detail_url(title_with_time, link_data),
    }
    return normalize_event_datetime(event)


def parse_month(page, year, month):
    lines = [
        clean_text(line)
        for line in page.locator("body").inner_text().splitlines()
        if clean_text(line)
    ]
    link_data = extract_detail_links(page)
    events, seen = [], set()
    current_day = None
    current_category = None

    def append_event(event):
        if not event:
            return
        key = (
            event["year"], event["month"], event["day"],
            event["cat"], event["title"], event["time"],
        )
        if key not in seen:
            seen.add(key)
            events.append(event)

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

        found_category = next(
            (cat for cat in CATEGORIES if line.startswith(cat + " ")),
            None,
        )
        if found_category:
            if current_day is not None:
                title_with_time = line[len(found_category):].strip()
                append_event(make_event(
                    year, month, current_day, found_category,
                    title_with_time, link_data,
                ))
            current_category = None
            continue

        if current_category and current_day is not None:
            ignored = {
                "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun",
                "SCHEDULE", "PREV MONTH", "NEXT MONTH", "ALL",
            }
            if line not in ignored:
                append_event(make_event(
                    year, month, current_day, current_category,
                    line, link_data,
                ))
            current_category = None

    return events


def member_pattern(member_name):
    return rf"(?<![A-Z]){re.escape(member_name)}(?![A-Z])"


def detect_members(detail_text, category=""):
    upper_text = detail_text.upper()

    if category == "MAGAZINE":
        keywords = (
            "インタビュー", "掲載", "登場", "表紙", "特集",
            "モデル", "撮り下ろし", "撮りおろし",
        )
        lines = [
            line.strip() for line in upper_text.splitlines()
            if any(keyword in line for keyword in keywords)
        ]
        found = [
            slug for name, slug in MEMBERS.items()
            if any(re.search(member_pattern(name), line) for line in lines)
        ]
        if found:
            return found

    if category in ("LIVE／EVENT", "LIVE/EVENT"):
        keywords = (
            "出演", "登壇", "登場", "ゲスト", "パフォーマンス",
            "ランウェイ", "モデル", "始球式", "セレモニアルピッチ", "トーク",
        )
        raw_lines = [line.strip() for line in upper_text.splitlines() if line.strip()]
        candidates = []
        for index, line in enumerate(raw_lines):
            if any(keyword in line for keyword in keywords):
                candidates.extend(raw_lines[max(0, index - 2):index + 3])
        found = [
            slug for name, slug in MEMBERS.items()
            if any(re.search(member_pattern(name), line) for line in candidates)
        ]
        if found:
            return found

    blocks = re.findall(
        r"([A-Z、,\s]{2,100})(?:が|は).{0,20}出演",
        upper_text,
    )
    found = [
        slug for name, slug in MEMBERS.items()
        if any(re.search(member_pattern(name), block) for block in blocks)
    ]
    return found or "ALL"


def event_date(event):
    try:
        return datetime(
            int(event["year"]), int(event["month"]), int(event["day"]),
            tzinfo=JST,
        ).date()
    except Exception:
        return None


def should_refresh_detail(event):
    if event.get("cat") in ("MAGAZINE", "LIVE／EVENT", "LIVE/EVENT"):
        return True
    date = event_date(event)
    if not date:
        return True
    return date >= datetime.now(JST).date() - timedelta(days=REFRESH_PAST_DAYS)


def enrich_members(page, events, cache):
    cache_hits = new_fetches = refresh_fetches = detail_errors = 0
    for index, event in enumerate(events, start=1):
        print(f"  detail {index}/{len(events)}: {event['title']}")
        url = event.get("url", "")
        if not url:
            print("    no detail url")
            continue

        cached = cache.get(url)
        if cached and not should_refresh_detail(event):
            event["members"] = cached.get("members", "ALL")
            event["note"] = cached.get("note", "")
            cache_hits += 1
            print(f"    CACHE HIT: {event['members']}")
            continue

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(400)
            close_cookie(page)
            members = detect_members(
                page.locator("body").inner_text(),
                event.get("cat", ""),
            )
            event["members"] = members
            if cached:
                refresh_fetches += 1
                print(f"    REFRESH FETCH: {members}")
            else:
                new_fetches += 1
                print(f"    NEW FETCH: {members}")
        except Exception as error:
            detail_errors += 1
            print(f"    detail error: {error}")
            if cached:
                event["members"] = cached.get("members", "ALL")
                event["note"] = cached.get("note", "")
                print("    FALLBACK TO CACHE")

    print(f"\nCACHE HITS: {cache_hits}")
    print(f"NEW DETAIL FETCHES: {new_fetches}")
    print(f"REFRESH DETAIL FETCHES: {refresh_fetches}")
    print(f"DETAIL ERRORS: {detail_errors}")
    return events


def scrape(existing_data):
    all_events = []
    cache = build_cache(existing_data)
    months = get_months()
    list_errors = 0
    print(f"Months to check: {len(months)}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(locale="ja-JP")

        for year, month in months:
            now = datetime.now(JST)
            url = (
                f"{BASE}/schedule/list/"
                if (year, month) == (now.year, now.month)
                else f"{BASE}/schedule/list/{year}/{month}/"
            )
            print(f"\n[{year}-{month:02d}] {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(800)
                close_cookie(page)
                events = parse_month(page, year, month)
                print(f"  events found: {len(events)}")
                all_events.extend(events)
            except Exception as error:
                list_errors += 1
                print(f"  LIST ERROR: {error}")

        unique_events, seen = [], set()
        for event in all_events:
            key = (
                event["year"], event["month"], event["day"],
                event["cat"], event["title"], event["time"],
            )
            if key not in seen:
                seen.add(key)
                unique_events.append(event)

        print(f"\nUnique events: {len(unique_events)}")
        unique_events = enrich_members(page, unique_events, cache)
        browser.close()

    return unique_events, list_errors


def validate_new_data(new_events, existing_events):
    new_count = len(new_events)
    old_count = len(existing_events)
    print(f"\nVALIDATION\n  previous events: {old_count}\n  new events: {new_count}")
    if new_count == 0:
        print("  ERROR: new event count is 0.")
        return False
    if old_count == 0:
        print("  No previous data. Validation passed.")
        return True
    minimum_allowed = int(old_count * MIN_EVENT_RATIO)
    if new_count < minimum_allowed:
        print(f"  ERROR: event count dropped too much.\n  Minimum allowed: {minimum_allowed}")
        return False
    print("  Validation passed.")
    return True


def main():
    existing_data = load_existing_data()
    existing_events = existing_data.get("events", [])
    events, list_errors = scrape(existing_data)
    events.sort(key=event_sort_key)

    if not validate_new_data(events, existing_events):
        print("\n" + "=" * 50)
        print("SAFETY STOP:\nschedule.json was NOT overwritten.")
        print("=" * 50)
        sys.exit(1)

    output = {
        "generated_at": datetime.now(JST).isoformat(),
        "events": events,
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)
        file.write("\n")

    specific = [event for event in events if event["members"] != "ALL"]
    print("\n" + "=" * 50)
    print(f"TOTAL EVENTS: {len(events)}")
    print(f"EVENTS WITH SPECIFIC MEMBERS: {len(specific)}")
    print(f"LIST PAGE ERRORS: {list_errors}")
    print("schedule.json updated safely.")
    print("=" * 50)


if __name__ == "__main__":
    main()
