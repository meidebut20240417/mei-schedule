import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

API_KEY = os.environ["YOUTUBE_API_KEY"]

CHANNEL_ID = "UCvTsv4KmVuBdECI08_HR87Q"
X_USERNAME = "official__ME_I_"
RSSHUB_BASE_URL = os.environ.get("RSSHUB_BASE_URL", "").rstrip("/")
INSTAGRAM_RSSHUB_PATH = os.environ.get(
    "INSTAGRAM_RSSHUB_PATH",
    "/instagram/2/user/official_me_i_",
).strip()

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
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=timezone.utc)

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
    main()def get_instagram_posts(limit=15):
    if not RSSHUB_BASE_URL:
        print("Instagram skipped: RSSHUB_BASE_URL is not configured.")
        return []

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
        has_video = False

        for element in item.findall("media:content", ns):
            media_type = (element.attrib.get("type") or "").lower()
            media_url = element.attrib.get("url", "")

            if media_type.startswith("video/"):
                has_video = True
            elif media_url and (
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

            if media_type.startswith("video/"):
                has_video = True
            elif media_url and media_type.startswith("image/"):
                image_urls.append(media_url)

        # RSSHub may place the image in HTML inside the description.
        for html in (description, _xml_text(item.find("content:encoded", ns))):
            for marker in ('<img', '<IMG'):
                pos = 0
                while True:
                    pos = html.find(marker, pos)
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

        # Instagram動画/リールだけの投稿は取得しない。
        # 画像が存在する投稿（通常投稿・複数画像投稿）は採用する。
        if not image_urls:
            continue

        if has_video and not image_urls:
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
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=timezone.utc)

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
