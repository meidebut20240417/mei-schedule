import json
import re
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright


BASE = "https://me-i.jp"

START_YEAR = 2024
START_MONTH = 4

MONTHS_AHEAD = 12

JST = timezone(timedelta(hours=9))


def get_months():

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


def close_cookie(page):

    selectors = [
        'button:has-text("同意")',
        'button:has-text("許可")',
        'button:has-text("Accept")',
        '#onetrust-accept-btn-handler',
    ]

    for selector in selectors:

        try:
            button = page.locator(selector)

            if button.count() > 0:
                button.first.click(timeout=2000)
                page.wait_for_timeout(500)
                print("  cookie banner closed")
                return

        except:
            pass


def get_clean_text(locator):

    try:
        text = locator.inner_text().strip()

        text = re.sub(r"\s+", " ", text)

        return text

    except:
        return ""


def get_title(page):

    selectors = [
        "main h1",
        "article h1",
        "h1",
        ".p-schedule-detail__title",
        ".schedule-detail__title",
        ".c-heading",
    ]

    for selector in selectors:

        try:

            elements = page.locator(selector)

            if elements.count() > 0:

                for i in range(elements.count()):

                    text = get_clean_text(elements.nth(i))

                    if not text:
                        continue

                    if "アクセス履歴" in text:
                        continue

                    if "クッキー" in text:
                        continue

                    if len(text) < 2:
                        continue

                    return text

        except:
            pass

    return ""


def get_category(page):

    categories = [
        "LIVE／EVENT",
        "WEB MEDIA",
        "RELEASE",
        "TV",
        "RADIO",
        "MAGAZINE",
        "BIRTHDAY",
        "OTHER",
    ]

    body = get_clean_text(page.locator("body"))

    for category in categories:

        if category in body:
            return category

    return ""


def get_event_date(page, fallback_year, fallback_month):

    body = get_clean_text(page.locator("body"))

    patterns = [
        r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日",
        r"(20\d{2})/(\d{1,2})/(\d{1,2})",
        r"(20\d{2})\.(\d{1,2})\.(\d{1,2})",
    ]

    for pattern in patterns:

        match = re.search(pattern, body)

        if match:

            return (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3))
            )

    return (
        fallback_year,
        fallback_month,
        None
    )


def get_time(page):

    body = get_clean_text(page.locator("body"))

    matches = re.findall(
        r"\b\d{1,2}:\d{2}\b",
        body
    )

    if matches:
        return matches[0]

    return ""


def get_events_from_list(page, year, month):

    events = []

    links = page.locator('a[href*="/schedule/detail/"]')

    count = links.count()

    print(f"  detail links: {count}")

    seen = set()

    for i in range(count):

        try:

            link = links.nth(i)

            href = link.get_attribute("href")

            if not href:
                continue

            match = re.search(
                r"/schedule/detail/(\d+)",
                href
            )

            if not match:
                continue

            event_id = int(match.group(1))

            if event_id in seen:
                continue

            seen.add(event_id)

            if href.startswith("http"):
                url = href
            else:
                url = BASE + href

            events.append({
                "id": event_id,
                "url": url,
                "year": year,
                "month": month
            })

        except Exception as e:

            print(f"  link error: {e}")

    return events


def get_event_detail(page, event):

    try:

        page.goto(
            event["url"],
            wait_until="domcontentloaded",
            timeout=30000
        )

        page.wait_for_timeout(1000)

        close_cookie(page)

        title = get_title(page)

        category = get_category(page)

        year, month, day = get_event_date(
            page,
            event["year"],
            event["month"]
        )

        event_time = get_time(page)

        if not title:

            print(
                f"    WARNING: title not found: {event['url']}"
            )

            return None

        print(
            f"    OK: {year}/{month}/{day} {title}"
        )

        return {
            "id": event["id"],
            "year": year,
            "month": month,
            "day": day,
            "cat": category,
            "title": title,
            "time": event_time,
            "members": "ALL",
            "note": "",
            "url": event["url"]
        }

    except Exception as e:

        print(
            f"    DETAIL ERROR: {event['url']} {e}"
        )

        return None


def scrape():

    all_events = []

    seen_ids = set()

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

                page.wait_for_timeout(1000)

                close_cookie(page)

            except Exception as e:

                print(
                    f"  PAGE ERROR: {e}"
                )

                continue

            events = get_events_from_list(
                page,
                year,
                month
            )

            print(
                f"  events found: {len(events)}"
            )

            for event in events:

                if event["id"] in seen_ids:
                    continue

                seen_ids.add(event["id"])

                detail = get_event_detail(
                    page,
                    event
                )

                if detail:
                    all_events.append(detail)


    return all_events


def main():

    events = scrape()

    events.sort(
        key=lambda event: (
            event["year"],
            event["month"],
            event["day"]
            if event["day"] is not None
            else 99,
            event["id"]
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
