import os
import json
import requests
from datetime import datetime, timezone, timedelta

API_KEY = os.environ["YOUTUBE_API_KEY"]

CHANNEL_ID = "UCvTsv4KmVuBdECI08_HR87Q"

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
    shorts_url = (
        f"https://www.youtube.com/shorts/{video_id}"
    )

    try:
        response = requests.get(
            shorts_url,
            headers=HEADERS,
            timeout=15,
            allow_redirects=True,
        )

        return "/shorts/" in response.url

    except requests.RequestException as e:
        print(
            f"Shorts check failed: {video_id}: {e}"
        )

        # 判定できなかった場合は通常動画扱い
        return False


def get_latest_posts(
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

        print(f"Checking: {title}")

        is_short = is_youtube_short(video_id)

        thumbnails = snippet.get(
            "thumbnails",
            {}
        )

        thumbnail = (
            thumbnails.get(
                "maxres",
                {}
            ).get("url")
            or thumbnails.get(
                "standard",
                {}
            ).get("url")
            or thumbnails.get(
                "high",
                {}
            ).get("url")
            or thumbnails.get(
                "medium",
                {}
            ).get("url")
            or thumbnails.get(
                "default",
                {}
            ).get("url")
            or ""
        )

        if is_short:
            platform = "youtube-short"
            platform_label = "TikTok / YouTube"
            url = (
                "https://www.youtube.com/"
                f"shorts/{video_id}"
            )

            print(
                f"  ADD SHORT: {video_id}"
            )

        else:
            platform = "youtube"
            platform_label = "YouTube"
            url = (
                "https://www.youtube.com/"
                f"watch?v={video_id}"
            )

            print(
                f"  ADD NORMAL VIDEO: {video_id}"
            )

        posts.append(
            {
                "id": f"youtube_{video_id}",
                "platform": platform,
                "platform_label": platform_label,
                "video_id": video_id,
                "title": title,
                "published_at": content.get(
                    "videoPublishedAt",
                    snippet.get(
                        "publishedAt",
                        ""
                    ),
                ),
                "thumbnail": thumbnail,
                "url": url,
            }
        )

        if len(posts) >= output_limit:
            break

    return posts


def main():
    channel = get_channel()

    uploads_playlist_id = (
        channel["contentDetails"]
        ["relatedPlaylists"]
        ["uploads"]
    )

    posts = get_latest_posts(
        uploads_playlist_id,
        max_results=30,
        output_limit=15,
    )

    output = {
        "generated_at": datetime.now(
            JST
        ).isoformat(),
        "posts": posts,
    }

    with open(
        "sns.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    normal_count = sum(
        1
        for post in posts
        if post["platform"] == "youtube"
    )

    short_count = sum(
        1
        for post in posts
        if post["platform"] == "youtube-short"
    )

    print("=" * 50)
    print("YouTube SNS fetch complete")
    print(
        f"Channel: "
        f"{channel['snippet']['title']}"
    )
    print(
        f"Normal videos: {normal_count}"
    )
    print(
        f"Shorts: {short_count}"
    )
    print(
        f"Total posts: {len(posts)}"
    )
    print(
        "sns.json generated"
    )
    print("=" * 50)


if __name__ == "__main__":
    main()
