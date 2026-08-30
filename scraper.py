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

# 直近何日前まで詳細ページを再確認するか
REFRESH_PAST_DAYS = 7

# 前回件数の何割未満なら異常とみなすか
MIN_EVENT_RATIO = 0.30


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


def load_existing_data():
    """
    既存 schedule.json を読み込む。
    キャッシュ利用と安全装置の両方に使う。
    """

    if not os.path.exists(CACHE_FILE):
        print("No existing schedule.json found.")
        return {
            "events": []
        }

    try:
        with open(
            CACHE_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        events = data.get("events", [])

        print(
            f"Loaded existing data: {len(events)} events"
        )

        return data

    except Exception as e:
        print(
            f"Existing JSON load error: {e}"
        )

        return {
            "events": []
        }


def build_cache(existing_data):
    """
    URLをキーに既存イベントを引けるようにする。
    """

    cache = {}

    for event in existing_data.get(
        "events",
        []
    ):
        url = event.get("url", "")

        if url:
            cache[url] = event

    print(
        f"Loaded cache: {len(cache)} events"
    )

    return cache


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


def find_best_detail_url(
    title,
    link_data
):
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


def parse_month(
    page,
    year,
    month
):
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

        if re.fullmatch(
            r"\d{1,2}",
            line
        ):
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
            if line.startswith(
                cat + " "
            ):
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


def detect_members(
    detail_text,
    category=""
):
    upper_text = detail_text.upper()

    found = []

    # ---------------------------------
    # MAGAZINE
    # ---------------------------------
    # 雑誌ページでは「○○が出演」ではなく
    # 「MIU インタビュー」「MIU、KEIKO 掲載」などの
    # 表記になることがあるため、雑誌系キーワードを含む行だけを調べる。
    if category == "MAGAZINE":
        magazine_keywords = (
            "インタビュー",
            "掲載",
            "登場",
            "表紙",
            "特集",
            "モデル",
            "撮り下ろし",
            "撮りおろし",
        )

        magazine_lines = [
            line.strip()
            for line in upper_text.splitlines()
            if any(
                keyword in line
                for keyword in magazine_keywords
            )
        ]

        for member_name, slug in MEMBERS.items():
            member_pattern = (
                rf"(?<![A-Z])"
                rf"{re.escape(member_name)}"
                rf"(?![A-Z])"
            )

            if any(
                re.search(
                    member_pattern,
                    line
                )
                for line in magazine_lines
            ):
                found.append(slug)

        if found:
            return found

    # ---------------------------------
    # LIVE／EVENT
    # ---------------------------------
    # ライブ／イベント詳細では「○○が出演」以外にも、
    # 「○○ 登壇」「出演：○○」「○○ ゲスト出演」などの
    # 書き方があるため、イベント出演に関係する行を追加で確認する。
    if category in ("LIVE／EVENT", "LIVE/EVENT"):
        event_keywords = (
            "出演",
            "登壇",
            "登場",
            "ゲスト",
            "パフォーマンス",
            "ランウェイ",
            "モデル",
            "始球式",
            "セレモニアルピッチ",
            "トーク",
        )

        # 「◾︎登壇者」の次の行に実際の名前が載るケースがあるため、
        # キーワード行そのものだけでなく前後2行もまとめて確認する。
        raw_lines = [
            line.strip()
            for line in upper_text.splitlines()
            if line.strip()
        ]

        event_candidate_lines = []

        for i, line in enumerate(raw_lines):
            if any(
                keyword in line
                for keyword in event_keywords
            ):
                start = max(0, i - 2)
                end = min(
                    len(raw_lines),
                    i + 3
                )

                event_candidate_lines.extend(
                    raw_lines[start:end]
                )

        event_found = []

        for member_name, slug in MEMBERS.items():
            member_pattern = (
                rf"(?<![A-Z])"
                rf"{re.escape(member_name)}"
                rf"(?![A-Z])"
            )

            if any(
                re.search(
                    member_pattern,
                    line
                )
                for line in event_candidate_lines
            ):
                event_found.append(slug)

        if event_found:
            return event_found

    # ---------------------------------
    # TV / RADIO / WEB など従来の出演判定
    # ---------------------------------
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

    # 部分一致ではなく「英字名としての完全一致」で判定する。
    # 例: TSUZUMI の中に SUZU という並びが含まれていても、
    #     SUZU 出演とは判定しない。
    for member_name, slug in MEMBERS.items():

        member_pattern = (
            rf"(?<![A-Z])"
            rf"{re.escape(member_name)}"
            rf"(?![A-Z])"
        )

        for block in matches:
            if re.search(
                member_pattern,
                block
            ):
                found.append(slug)
                break

    if found:
        return found

    return "ALL"


def event_date(event):
    """
    eventをdatetime.dateに変換。
    """

    try:
        return datetime(
            int(event["year"]),
            int(event["month"]),
            int(event["day"]),
            tzinfo=JST
        ).date()

    except Exception:
        return None


def should_refresh_detail(event):
    """
    直近7日〜未来の予定は
    キャッシュがあっても詳細を再取得する。

    MAGAZINE は出演メンバー表記が「出演」以外の形になることがあるため、
    過去分も含めて詳細を再確認する。
    """

    if event.get("cat") in ("MAGAZINE", "LIVE／EVENT", "LIVE/EVENT"):
        return True

    date = event_date(event)

    if not date:
        return True

    today = datetime.now(
        JST
    ).date()

    refresh_from = (
        today
        - timedelta(
            days=REFRESH_PAST_DAYS
        )
    )

    return date >= refresh_from


def enrich_members(
    page,
    events,
    cache
):
    total = len(events)

    cache_hits = 0
    new_fetches = 0
    refresh_fetches = 0
    detail_errors = 0

    for index, event in enumerate(
        events,
        start=1
    ):
        url = event.get(
            "url",
            ""
        )

        print(
            f"  detail {index}/{total}: "
            f"{event['title']}"
        )

        if not url:
            print(
                "    no detail url"
            )
            continue


        cached = cache.get(url)

        refresh_required = (
            should_refresh_detail(
                event
            )
        )


        # -------------------------
        # 古いイベント
        # → キャッシュをそのまま使用
        # -------------------------
        if (
            cached
            and not refresh_required
        ):

            event["members"] = (
                cached.get(
                    "members",
                    "ALL"
                )
            )

            event["note"] = (
                cached.get(
                    "note",
                    ""
                )
            )

            cache_hits += 1

            print(
                f"    CACHE HIT: "
                f"{event['members']}"
            )

            continue


        # -------------------------
        # 新規 or 直近/未来イベント
        # → 詳細ページを再取得
        # -------------------------
        try:
            page.goto(
                url,
                wait_until=(
                    "domcontentloaded"
                ),
                timeout=30000
            )

            page.wait_for_timeout(
                400
            )

            close_cookie(page)

            detail_text = (
                page.locator(
                    "body"
                ).inner_text()
            )

            members = detect_members(
                detail_text,
                event.get("cat", "")
            )

            event["members"] = (
                members
            )

            # 既存イベントの再確認
            if cached:
                refresh_fetches += 1

                print(
                    "    REFRESH FETCH: "
                    f"{members}"
                )

            # 完全新規
            else:
                new_fetches += 1

                print(
                    "    NEW FETCH: "
                    f"{members}"
                )

        except Exception as e:

            detail_errors += 1

            print(
                f"    detail error: {e}"
            )

            # 詳細取得失敗時、
            # キャッシュがあれば古い情報を残す
            if cached:
                event["members"] = (
                    cached.get(
                        "members",
                        "ALL"
                    )
                )

                event["note"] = (
                    cached.get(
                        "note",
                        ""
                    )
                )

                print(
                    "    FALLBACK TO CACHE"
                )

    print()
    print(
        f"CACHE HITS: "
        f"{cache_hits}"
    )
    print(
        f"NEW DETAIL FETCHES: "
        f"{new_fetches}"
    )
    print(
        f"REFRESH DETAIL FETCHES: "
        f"{refresh_fetches}"
    )
    print(
        f"DETAIL ERRORS: "
        f"{detail_errors}"
    )

    return events


def scrape(
    existing_data
):
    all_events = []

    cache = build_cache(
        existing_data
    )

    months = get_months()

    print(
        f"Months to check: "
        f"{len(months)}"
    )

    list_errors = 0

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
                f"[{year}-{month:02d}] "
                f"{url}"
            )

            try:
                page.goto(
                    url,
                    wait_until=(
                        "domcontentloaded"
                    ),
                    timeout=30000
                )

                page.wait_for_timeout(
                    800
                )

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

                all_events.extend(
                    events
                )

            except Exception as e:
                list_errors += 1

                print(
                    f"  LIST ERROR: {e}"
                )


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

            unique_events.append(
                event
            )


        print()
        print(
            f"Unique events: "
            f"{len(unique_events)}"
        )


        unique_events = enrich_members(
            page,
            unique_events,
            cache
        )

        browser.close()

    return (
        unique_events,
        list_errors
    )


def validate_new_data(
    new_events,
    existing_events
):
    """
    空データや異常減少を検出する。
    """

    new_count = len(
        new_events
    )

    old_count = len(
        existing_events
    )

    print()
    print(
        "VALIDATION"
    )

    print(
        f"  previous events: "
        f"{old_count}"
    )

    print(
        f"  new events: "
        f"{new_count}"
    )


    # 完全0件は絶対保存しない
    if new_count == 0:

        print(
            "  ERROR: "
            "new event count is 0."
        )

        return False


    # 前回データがまだない初回はOK
    if old_count == 0:

        print(
            "  No previous data. "
            "Validation passed."
        )

        return True


    minimum_allowed = int(
        old_count
        * MIN_EVENT_RATIO
    )


    if new_count < minimum_allowed:

        print(
            "  ERROR: "
            "event count dropped "
            "too much."
        )

        print(
            f"  Minimum allowed: "
            f"{minimum_allowed}"
        )

        return False


    print(
        "  Validation passed."
    )

    return True


def main():

    existing_data = (
        load_existing_data()
    )

    existing_events = (
        existing_data.get(
            "events",
            []
        )
    )

    events, list_errors = scrape(
        existing_data
    )


    events.sort(
        key=lambda event: (
            event["year"],
            event["month"],
            event["day"],
            event["title"]
        )
    )


    valid = validate_new_data(
        events,
        existing_events
    )


    # -------------------------
    # 異常時は schedule.json を
    # 絶対に上書きしない
    # -------------------------
    if not valid:

        print()
        print(
            "=" * 50
        )

        print(
            "SAFETY STOP:"
        )

        print(
            "schedule.json was NOT "
            "overwritten."
        )

        print(
            "=" * 50
        )

        sys.exit(1)


    output = {
        "generated_at":
            datetime.now(
                JST
            ).isoformat(),

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


    specific = [
        event
        for event in events
        if event["members"]
        != "ALL"
    ]


    print()
    print(
        "=" * 50
    )

    print(
        f"TOTAL EVENTS: "
        f"{len(events)}"
    )

    print(
        "EVENTS WITH SPECIFIC MEMBERS: "
        f"{len(specific)}"
    )

    print(
        f"LIST PAGE ERRORS: "
        f"{list_errors}"
    )

    print(
        "schedule.json updated safely."
    )

    print(
        "=" * 50
    )


if __name__ == "__main__":
    main()
