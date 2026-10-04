import os
import json
import requests
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

API_KEY = os.environ["YOUTUBE_API_KEY"]

CHANNEL_ID = "UCvTsv4KmVuBdECI08_HR87Q"
X_USERNAME = "official__ME_I_"
INSTAGRAM_USERNAME = "official_me_i_"

# まずRSSHubを試し、失敗した場合は代替の公開RSS経路へフォールバック。
RSSHUB_BASE_URL = os.environ.get(
    "RSSHUB_BASE_URL",
    "https://rsshub.cmyr.dev",
).rstrip("/")

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/120 Safari/537.36"
    )
}

# X: Nitter系はインスタンスごとに停止する可能性があるため複数候補。
# X: RSS-BridgeのTwitter Bridgeも追加。Nitterより安定する公開インスタンスがある場合はこちらを先に試す。
X_RSS_BRIDGE_BASE_URLS = [
    value.rstrip("/")
    for value in os.environ.get(
        "X_RSS_BRIDGE_BASE_URLS",
        ",".join([
            "https://rssbridge.sciunto.org",
            "https://rss-bridge.org/bridge01",
            "https://www.rssbridge.wdavery.com",
            "https://www.bridge.mergis.net",
        ]),
    ).split(",")
    if value.strip()
]

X_NITTER_BASE_URLS = [
    value.rstrip("/")
    for value in os.environ.get(
        "X_NITTER_BASE_URLS",
        ",".join(
            [
                "https://nitter.jaydenha.uk",
                "https://nitter.meowing.monster",
                "https://nitter.tiekoetter.com",
                "https://nitter.netbub.com",
            ]
        ),
    ).split(",")
    if value.strip()
]

# Instagram: RSSHubに加えてRSS-Bridgeをフォールバック。
INSTAGRAM_RSS_BRIDGE_BASE_URLS = [
    value.rstrip("/")
    for value in os.environ.get(
        "INSTAGRAM_RSS_BRIDGE_BASE_URLS",
        ",".join(
            [
                "https://rss-bridge.org/bridge01",
                "https://rssbridge.flossboxin.org.in",
                "https://rss-bridge.sans-nuage.fr",
                "https://rb.ash.fail",
            ]
        ),
    ).split(",")
    if value.strip()
]


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


def _parse_feed(url, timeout=30):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    return ET.fromstring(response.content)


def _image_urls_from_item(item, ns):
    image_urls = []

    # RSS-Bridge may nest media:content and may omit the MIME type.
    for element in item.findall(".//media:content", ns):
        media_type = (element.attrib.get("type") or "").lower()
        medium = (element.attrib.get("medium") or "").lower()
        media_url = element.attrib.get("url", "")

        if media_url and (
            media_type.startswith("image/")
            or medium == "image"
            or "pbs.twimg.com/media/" in media_url.lower()
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

    for element in item.findall(".//enclosure"):
        media_type = (element.attrib.get("type") or "").lower()
        medium = (element.attrib.get("medium") or "").lower()
        media_url = element.attrib.get("url", "")

        if media_url and (
            media_type.startswith("image/")
            or medium == "image"
            or "pbs.twimg.com/media/" in media_url.lower()
            or any(
                media_url.lower().split("?")[0].endswith(ext)
                for ext in (".jpg", ".jpeg", ".png", ".webp")
            )
        ):
            image_urls.append(media_url)

    # Atomの <link rel="enclosure" href="..."> にも対応。
    # X/RSS-Bridgeでは画像でもtypeがapplication/octet-streamになる場合がある。
    for element in item:
        if element.tag.endswith("link"):
            rel = (element.attrib.get("rel") or "").lower()
            media_type = (element.attrib.get("type") or "").lower()
            medium = (element.attrib.get("medium") or "").lower()
            href = element.attrib.get("href", "")
            if href and rel == "enclosure" and (
                media_type.startswith("image/")
                or medium == "image"
                or "pbs.twimg.com/media/" in href.lower()
                or any(
                    href.lower().split("?")[0].endswith(ext)
                    for ext in (".jpg", ".jpeg", ".png", ".webp")
                )
            ):
                image_urls.append(href)

    # RSS-Bridge/NitterがHTML内に画像を置く場合にも対応。
    html_parts = [
        _xml_text(item.find("description")),
        _xml_text(
            item.find(
                "content:encoded",
                {
                    "content": "http://purl.org/rss/1.0/modules/content/",
                },
            )
        ),
        _xml_text(item.find("{http://www.w3.org/2005/Atom}content")),
    ]

    for html in html_parts:
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

            for attribute in ("src", "data-src", "data-original", "href"):
                marker = f"{attribute}="
                attr_pos = lowered.find(marker)

                if attr_pos == -1:
                    continue

                quote = tag[attr_pos + len(marker):attr_pos + len(marker) + 1]

                if quote in {'"', "'"}:
                    value_start = attr_pos + len(marker) + 1
                    value_end = tag.find(quote, value_start)

                    if value_end != -1:
                        image_urls.append(tag[value_start:value_end])

            srcset_pos = lowered.find("srcset=")
            if srcset_pos != -1:
                quote = tag[srcset_pos + 7:srcset_pos + 8]

                if quote in {'"', "'"}:
                    value_start = srcset_pos + 8
                    value_end = tag.find(quote, value_start)

                    if value_end != -1:
                        for candidate in tag[value_start:value_end].split(","):
                            image_urls.append(candidate.strip().split(" ")[0])

            pos = end_tag + 1

        # Instagramの画像+動画投稿では、画像が <video poster>、
        # <source>、または og:image の meta に入る場合がある。
        # これらも画像付き投稿として拾う。
        for tag_match in re.finditer(
            r"<(?:video|source|meta)\\b[^>]*>",
            html,
            flags=re.IGNORECASE,
        ):
            tag = tag_match.group(0)
            for attribute in ("poster", "src", "content"):
                match = re.search(
                    rf"\\b{attribute}\\s*=\\s*([\\\"'])(.*?)\\1",
                    tag,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if not match:
                    continue
                value = match.group(2).strip()
                lowered = value.lower()
                if attribute in {"poster", "content"} and not (
                    any(lowered.split("?")[0].endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp"))
                    or "cdninstagram" in lowered
                    or "fbcdn" in lowered
                    or "instagram" in lowered
                ):
                    continue
                image_urls.append(value)

    # Instagram混合投稿では、画像URLが media:thumbnail / enclosure / video poster
    # のいずれかに入り、拡張子が見えないCDN URLになる場合がある。
    # 投稿内の全属性を最後の安全網として走査する。
    for element in item.iter():
        for key, value in element.attrib.items():
            lowered = value.lower()
            if (
                "pbs.twimg.com/media/" in lowered
                or "cdninstagram.com" in lowered
                or "scontent" in lowered
                or "fbcdn.net" in lowered
                or (
                    any(lowered.split("?")[0].endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp"))
                    and lowered.startswith(("http://", "https://"))
                )
            ):
                image_urls.append(value)

    # media:thumbnail がネストされているケースも拾う。
    for element in item.findall(".//media:thumbnail", ns):
        value = element.attrib.get("url", "")
        if value:
            image_urls.append(value)

    return list(dict.fromkeys(
        url for url in image_urls
        if url and url.startswith(("http://", "https://"))
    ))


def _feed_items(root):
    # RSS
    items = root.findall(".//item")
    if items:
        return items

    # Atom
    atom_ns = {"atom": "http://www.w3.org/2005/Atom"}
    return root.findall(".//atom:entry", atom_ns)


def _feed_value(item, names):
    for name in names:
        element = item.find(name)

        if element is not None:
            value = _xml_text(element)

            if value:
                return value

    # Atom <link href="...">
    for name in names:
        element = item.find(name)

        if element is not None and element.attrib.get("href"):
            return element.attrib["href"]

    return ""


def _get_rss_bridge_json(url, timeout=20):
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.json()


def get_x_posts(limit=15):
    # FxTwitter API: 公開プロフィールの「メディア投稿」を取得。
    # /media は画像・動画などのメディア投稿だけを返すため、
    # media.photos がある投稿だけ採用すれば「画像あり」の条件を
    # そのまま満たせる。画像+動画も photos が存在すれば採用する。
    fxtwitter_url = (
        f"https://api.fxtwitter.com/2/profile/{X_USERNAME}/media"
        f"?count={min(max(limit * 3, 20), 100)}"
    )

    try:
        print(f"X FxTwitter feed trying: {fxtwitter_url}")
        response = requests.get(
            fxtwitter_url,
            headers={"User-Agent": "MEI-Link-SNS-Updater/1.0"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results", []) if isinstance(data, dict) else []
        print(f"X FxTwitter feed succeeded: {len(results)} items")

        posts = []
        for item in results:
            if not isinstance(item, dict):
                continue

            media = item.get("media") or {}
            photos = media.get("photos") or []
            if not photos:
                continue

            image_urls = [
                str(photo.get("url") or "")
                for photo in photos
                if isinstance(photo, dict) and photo.get("url")
            ]
            image_urls = list(dict.fromkeys(image_urls))
            if not image_urls:
                continue

            published_at = item.get("created_at") or ""
            post_id = item.get("id") or item.get("url") or (
                f"x_{published_at}_{image_urls[0]}"
            )

            posts.append(
                {
                    "id": f"x_{post_id}",
                    "platform": "x",
                    "platform_label": "X",
                    "title": item.get("text") or "",
                    "published_at": published_at,
                    "thumbnail": image_urls[0],
                    "url": item.get("url") or f"https://x.com/{X_USERNAME}",
                }
            )

            if len(posts) >= limit:
                break

        print(f"X image posts: {len(posts)}")
        if posts:
            return posts

    except (requests.RequestException, ValueError) as e:
        print(f"X FxTwitter feed failed: {e}")

    # FxTwitterが利用できない場合はRSS-Bridge/Nitterへフォールバック。
    # RSS-BridgeのJSON形式は、Twitter Bridgeが生成した
    # enclosures を attachments[].url として保持するため、
    # Atomよりも画像抽出が安定する。
    json_feed_urls = []
    for base in X_RSS_BRIDGE_BASE_URLS:
        json_feed_urls.extend([
            (
                f"{base}/?action=display&bridge=Twitter"
                f"&context=Username&u={X_USERNAME}"
                f"&format=Json&norep=on&noretweet=on"
            ),
            (
                f"{base}/?action=display&bridge=Twitter"
                f"&context=Username&u={X_USERNAME}"
                f"&format=Json"
            ),
        ])

    for url in json_feed_urls:
        try:
            print(f"X JSON feed trying: {url}")
            data = _get_rss_bridge_json(url, timeout=20)
            items = data.get("items", []) if isinstance(data, dict) else []
            print(f"X JSON feed succeeded: {url} ({len(items)} items)")

            posts = []
            for item_index, item in enumerate(items[:limit * 3]):
                attachments = item.get("attachments", []) or []
                image_urls = []

                for attachment in attachments:
                    if not isinstance(attachment, dict):
                        continue
                    image_url = str(attachment.get("url") or "")
                    lowered = image_url.lower()
                    if (
                        "pbs.twimg.com/media/" in lowered
                        or "pbs.twimg.com/media" in lowered
                        or any(
                            lowered.split("?")[0].endswith(ext)
                            for ext in (".jpg", ".jpeg", ".png", ".webp")
                        )
                    ):
                        image_urls.append(image_url)

                # 公開RSS-BridgeのJSONでは、attachmentsが空でも
                # content_htmlや他のフィールド内にpbs.twimg.comのURLが
                # 直接残っていることがある。HTMLをXMLとしてparseすると
                # X側の不正な文字列でParseErrorになるため、ここでは
                # JSON化したitem全体から画像URLだけを安全に拾う。
                if not image_urls:
                    serialized_item = json.dumps(item, ensure_ascii=False)
                    image_urls.extend(
                        re.findall(
                            r"https?://pbs\\.twimg\\.com/media/[^\\s\\\"'<>\\\\]+",
                            serialized_item,
                        )
                    )

                if not image_urls:
                    # pbs.twimg.com以外の一般的な画像URLも拾う。
                    serialized_item = json.dumps(item, ensure_ascii=False)
                    image_urls.extend(
                        re.findall(
                            r"https?://[^\\s\\\"'<>\\\\]+\\.(?:jpg|jpeg|png|webp)(?:\\?[^\\s\\\"'<>\\\\]*)?",
                            serialized_item,
                            flags=re.IGNORECASE,
                        )
                    )

                image_urls = list(dict.fromkeys(image_urls))

                if not image_urls:
                    continue

                thumbnail = image_urls[0]
                published_at = (
                    item.get("date_modified")
                    or item.get("date_published")
                    or ""
                )
                post_id = item.get("id") or item.get("url") or (
                    f"x_{published_at}_{thumbnail}"
                )

                posts.append(
                    {
                        "id": f"x_{post_id}",
                        "platform": "x",
                        "platform_label": "X",
                        "title": item.get("title") or "",
                        "published_at": published_at,
                        "thumbnail": thumbnail,
                        "url": item.get("url") or f"https://x.com/{X_USERNAME}",
                    }
                )

                if len(posts) >= limit:
                    break

            print(f"X image posts: {len(posts)}")
            return posts

        except (requests.RequestException, ValueError, ET.ParseError) as e:
            print(f"X JSON feed failed: {e}")

    # JSON形式が使えない公開インスタンスでは従来のAtom/Nitterへフォールバック。
    feed_urls = [
        f"{RSSHUB_BASE_URL}/twitter/media/{X_USERNAME}",
    ]

    for base in X_RSS_BRIDGE_BASE_URLS:
        feed_urls.extend([
            (
                f"{base}/?action=display&bridge=Twitter"
                f"&context=Username&u={X_USERNAME}"
                f"&format=Atom&norep=on&noretweet=on"
            ),
            (
                f"{base}/?action=display&bridge=Twitter"
                f"&context=Username&u={X_USERNAME}"
                f"&format=Atom"
            ),
        ])

    feed_urls.extend(
        f"{base}/{X_USERNAME}/media/rss"
        for base in X_NITTER_BASE_URLS
    )

    root = None

    for url in feed_urls:
        try:
            print(f"X feed trying: {url}")
            root = _parse_feed(url, timeout=20)
            print(f"X feed succeeded: {url}")
            break
        except (requests.RequestException, ET.ParseError) as e:
            print(f"X feed failed: {e}")

    if root is None:
        print("X feed: all sources failed")
        print("X image posts: 0")
        return []

    ns = {
        "media": "http://search.yahoo.com/mrss/",
    }

    posts = []

    for item in _feed_items(root)[:limit * 3]:
        link = _feed_value(item, ["link", "{http://www.w3.org/2005/Atom}link"])
        guid = _feed_value(item, ["guid", "id"])
        title = _feed_value(item, ["title"])
        description = _feed_value(item, ["description", "summary"])
        published_at = _feed_value(
            item,
            ["pubDate", "published", "updated"],
        )

        image_urls = _image_urls_from_item(item, ns)

        x_image_urls = []
        for image_url in image_urls:
            lowered = image_url.lower()
            if (
                "pbs.twimg.com/media/" in lowered
                or "pbs.twimg.com/media" in lowered
                or any(
                    lowered.split("?")[0].endswith(ext)
                    for ext in (".jpg", ".jpeg", ".png", ".webp")
                )
            ):
                x_image_urls.append(image_url)

        if not x_image_urls:
            continue

        thumbnail = x_image_urls[0]
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

def _instagram_page_image(url, timeout=15):
    """Instagram投稿ページのOG画像を取得する最後のフォールバック。"""
    if not url or "instagram.com" not in url:
        return ""

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        html = response.text

        for pattern in (
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        ):
            match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
            if match:
                image_url = match.group(1).strip()
                if image_url.startswith(("http://", "https://")):
                    return image_url

    except requests.RequestException as e:
        print(f"Instagram page image failed: {url}: {e}")

    return ""


def get_instagram_posts(limit=15):
    feed_urls = [
        f"{RSSHUB_BASE_URL}/instagram/2/user/{INSTAGRAM_USERNAME}",
    ]

    feed_urls.extend(
        (
            f"{base}/?action=display&bridge=InstagramBridge"
            f"&context=Username&u={INSTAGRAM_USERNAME}"
            f"&media_type=all&direct_links=on&format=Atom"
        )
        for base in INSTAGRAM_RSS_BRIDGE_BASE_URLS
    )

    root = None

    for url in feed_urls:
        try:
            print(f"Instagram feed trying: {url}")
            root = _parse_feed(url, timeout=25)
            print(f"Instagram feed succeeded: {url}")
            break
        except (requests.RequestException, ET.ParseError) as e:
            print(f"Instagram feed failed: {e}")

    if root is None:
        print("Instagram feed: all sources failed")
        print("Instagram image posts: 0")
        return []

    ns = {
        "media": "http://search.yahoo.com/mrss/",
        "content": "http://purl.org/rss/1.0/modules/content/",
        "dc": "http://purl.org/dc/elements/1.1/",
    }

    posts = []

    for item in _feed_items(root)[:limit * 3]:
        link = _feed_value(
            item,
            ["link", "{http://www.w3.org/2005/Atom}link"],
        )
        guid = _feed_value(item, ["guid", "id"])
        title = _feed_value(item, ["title"])
        description = _feed_value(item, ["description", "summary"])
        published_at = _feed_value(
            item,
            ["pubDate", "dc:date", "published", "updated"],
        )

        image_urls = _image_urls_from_item(item, ns)

        # RSS側が混合投稿を「動画」としてしか返さない場合でも、
        # 投稿ページ自身のog:image/twitter:imageから代表画像を取得する。
        if not image_urls and link:
            page_image = _instagram_page_image(link)
            if page_image:
                image_urls.append(page_image)

        # 画像付き投稿を採用。画像+動画の混合投稿もここに含まれる。
        # 画像なしの動画専用投稿だけは除外。
        if not image_urls:
            continue

        thumbnail = image_urls[0]
        post_id = guid or link or (
            f"instagram_{published_at}_{thumbnail}"
        )

        posts.append(
            {
                "id": f"instagram_{post_id}",
                "platform": "instagram",
                "platform_label": "Instagram",
                "title": title or "Instagram新着投稿",
                "published_at": published_at,
                "thumbnail": thumbnail,
                "url": link or (
                    "https://www.instagram.com/official_me_i_/"
                ),
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

        if not value:
            return datetime.min.replace(tzinfo=timezone.utc)

        # YouTubeはISO 8601、FxTwitter/RSS-Bridgeは
        # RFC 2822系の日時を返すことがある。両方を正しく比較する。
        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return datetime.min.replace(tzinfo=timezone.utc)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

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
