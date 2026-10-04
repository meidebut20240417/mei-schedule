import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

API_KEY = os.environ["YOUTUBE_API_KEY"]

CHANNEL_ID = "UCvTsv4KmVuBdECI08_HR87Q"
X_USERNAME = "official__ME_I_"

# GitHub Secretで上書き可能。未設定時は公開RSSHub候補を使用。
RSSHUB_BASE_URL = os.environ.get(
    "RSSHUB_BASE_URL",
    "https://rsshub.cmyr.dev",
).rstrip("/")

INSTAGRAM_RSSHUB_PATH = os.environ.get(
    "INSTAGRAM_RSSHUB_PATH",
    "/instagram/2/user/official_me_i_",
).strip()

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/120 Safari/537.36"
    )
}


def youtube_get(endpoint, params):
    params = {
        **params,
        "key": API_KEY,
    }

    response = requests.get(
        f"https://www.googleapis.com/youtube/v3/{endpoint}",
        params=params,
        timeout=30,
    )

    response.raise_for_status()
    return response.json()


def get_channel():
    data = youtube_get(
        "channels",
        {
            "part": "snippet,contentDetails",
            "id": CHANNEL_ID,
        },
    )

    items = data.get("items", [])

    if not items:
        raise RuntimeError(
            f"YouTube channel not found: {CHANNEL_ID}"
        )

    return items[0]


def is_youtube_short(video_id):
    shorts_url = f"https://www.youtube.com/shorts/{video_id}"

    try:
        response = requests.get(
            shorts_url,
            headers=HEADERS,
            timeout=15,
            allow_redirects=True,
        )

        return "/shorts/" in response.url

    except requests.RequestException as e:
        print(f"Shorts check failed: {video_id}: {e}")
        return False


def get_youtube_posts(
    uploads_playlist_id,
    max_results=30,
    output_limit=15,
):
    data = youtube_get(
        "playlistItems",
        {
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": max_results,
        },
    )

    posts = []

    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        content = item.get("contentDetails", {})
        video_id = content.get("videoId")

        if not video_id:
            continue

        title = snippet.get("title", "")
        print(f"YouTube checking: {title}")

        is_short = is_youtube_short(video_id)
        thumbnails = snippet.get("thumbnails", {})

        thumbnail = (
            thumbnails.get("maxres", {}).get("url")
            or thumbnails.get("standard", {}).get("url")
            or thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
            or ""
        )

        if is_short:
            platform = "youtube-short"
            platform_label = "TikTok / YouTube"
            url = f"https://www.youtube.com/shorts/{video_id}"
        else:
            platform = "youtube"
            platform_label = "YouTube"
            url = f"https://www.youtube.com/watch?v={video_id}"

        posts.append(
            {
                "id": f"youtube_{video_id}",
                "platform": platform,
                "platform_label": platform_label,
                "video_id": video_id,
                "title": title,
                "published_at": content.get(
                    "videoPublishedAt",
                    snippet.get("publishedAt", ""),
                ),
                "thumbnail": thumbnail,
                "url": url,
            }
        )

        if len(posts) >= output_limit:
            break

    return posts


def _xml_text(element):
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def get_x_posts(limit=15):
    url = f"{RSSHUB_BASE_URL}/twitter/media/{X_USERNAME}"

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError) as e:
        print(f"X RSSHub fetch failed: {e}")
        return []

    ns = {
        "media": "http://search.yahoo.com/mrss/",
    }

    posts = []

    for item in root.findall(".//item")[:limit * 2]:
        link = _xml_text(item.find("link"))
        guid = _xml_text(item.find("guid"))
        title = _xml_text(item.find("title"))
        description = _xml_text(item.find("description"))
        published_at = _xml_text(item.find("pubDate"))

        image_urls = []

        for element in item.findall("media:content", ns):
            media_type = (element.attrib.get("type") or "").lower()
            media_url = element.attrib.get("url", "")

            if media_url and (
                media_type.startswith("image/")
                or any(
                    media_url.lower().split("?")[0].endswith(ext)
                    for ext in (".jpg", ".jpeg", ".png", ".webp")
                )
            ):
                image_urls.append(media_url)

        for element in item.findall("media:thumbnail", ns):
            media_url = element.attrib.get("url", "")
            if media_url:
                image_urls.append(media_url)

        for element in item.findall("enclosure"):
            media_type = (element.attrib.get("type") or "").lower()
            media_url = element.attrib.get("url", "")

            if media_url and media_type.startswith("image/"):
                image_urls.append(media_url)

        image_urls = list(dict.fromkeys(image_urls))

        # Xは画像付き投稿だけ採用。動画のみ・テキストのみは除外。
        if not image_urls:
            continue

        thumbnail = image_urls[0]
        post_id = guid or link or f"x_{published_at}_{thumbnail}"

        posts.append(
            {
                "id": f"x_{post_id}",
                "platform": "x",
                "platform_label": "X",
                "title": title or description,
                "published_at": published_at,
                "thumbnail": thumbnail,
                "url": link or f"https://x.com/{X_USERNAME}",
            }
        )

        if len(posts) >= limit:
            break

    print(f"X image posts: {len(posts)}")
    return posts


def get_instagram_posts(limit=15):
    path = INSTAGRAM_RSSHUB_PATH.strip()

    if not path.startswith("/"):
        path = "/" + path

    url = f"{RSSHUB_BASE_URL}{path}"

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError) as e:
        print(f"Instagram RSSHub fetch failed: {e}")
        return []

    ns = {
        "media": "http://search.yahoo.com/mrss/",
        "content": "http://purl.org/rss/1.0/modules/content/",
        "dc": "http://purl.org/dc/elements/1.1/",
    }

    posts = []

    for item in root.findall(".//item")[:limit * 3]:
        link = _xml_text(item.find("link"))
        guid = _xml_text(item.find("guid"))
        title = _xml_text(item.find("title"))
        description = _xml_text(item.find("description"))
        published_at = (
            _xml_text(item.find("pubDate"))
            or _xml_text(item.find("dc:date", ns))
        )

        image_urls = []

        for element in item.findall("media:content", ns):
            media_type = (element.attrib.get("type") or "").lower()
            media_url = element.attrib.get("url", "")

            if media_url and (
                media_type.startswith("image/")
                or any(
                    media_url.lower().split("?")[0].endswith(ext)
                    for ext in (".jpg", ".jpeg", ".png", ".webp")
                )
            ):
                image_urls.append(media_url)

        for element in item.findall("media:thumbnail", ns):
            media_url = element.attrib.get("url", "")
            if media_url:
                image_urls.append(media_url)

        for element in item.findall("enclosure"):
            media_type = (element.attrib.get("type") or "").lower()
            media_url = element.attrib.get("url", "")

            if media_url and media_type.startswith("image/"):
                image_urls.append(media_url)

        # RSSHubがHTML内に画像を置く場合にも対応。
        for html in (
            description,
            _xml_text(item.find("content:encoded", ns)),
        ):
            pos = 0

            while True:
                pos = html.lower().find("<img", pos)

                if pos == -1:
                    break

                end_tag = html.find(">", pos)

                if end_tag == -1:
                    break

                tag = html[pos:end_tag + 1]
                lowered = tag.lower()
                src_pos = lowered.find("src=")

                if src_pos != -1:
                    quote = tag[src_pos + 4:src_pos + 5]

                    if quote in {'"', "'"}:
                        value_start = src_pos + 5
                        value_end = tag.find(quote, value_start)

                        if value_end != -1:
                            image_urls.append(
                                tag[value_start:value_end]
                            )

                pos = end_tag + 1

        image_urls = list(dict.fromkeys(image_urls))

        # Instagramは画像付き投稿だけ採用。
        # 画像なしのリール/動画専用投稿は除外。
        if not image_urls:
            continue

        thumbnail = image_urls[0]
        post_id = guid or link or f"instagram_{published_at}_{thumbnail}"

        posts.append(
            {
                "id": f"instagram_{post_id}",
                "platform": "instagram",
                "platform_label": "Instagram",
                "title": title or "Instagram新着投稿",
                "published_at": published_at,
                "thumbnail": thumbnail,
                "url": link or "https://www.instagram.com/official_me_i_/",
            }
        )

        if len(posts) >= limit:
            break

    print(f"Instagram image posts: {len(posts)}")
    return posts


def main():
    channel = get_channel()

    uploads_playlist_id = (
        channel["contentDetails"]
        ["relatedPlaylists"]
        ["uploads"]
    )

    youtube_posts = get_youtube_posts(
        uploads_playlist_id,
        max_results=30,
        output_limit=15,
    )

    x_posts = get_x_posts(limit=15)
    instagram_posts = get_instagram_posts(limit=15)

    posts = youtube_posts + x_posts + instagram_posts

    def sort_key(post):
        value = post.get("published_at", "")

        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            return datetime.min.replace(
                tzinfo=timezone.utc
            )

    posts.sort(key=sort_key, reverse=True)
    posts = posts[:15]

    output = {
        "generated_at": datetime.now(JST).isoformat(),
        "posts": posts,
    }

    with open("sns.json", "w", encoding="utf-8") as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("=" * 50)
    print("SNS fetch complete")
    print(f"YouTube: {len(youtube_posts)}")
    print(f"X image posts: {len(x_posts)}")
    print(f"Instagram image posts: {len(instagram_posts)}")
    print(f"Final posts: {len(posts)}")
    print("sns.json generated")
    print("=" * 50)


if __name__ == "__main__":
    main()
