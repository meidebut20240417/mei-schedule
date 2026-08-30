import os
import json
import requests
from datetime import datetime, timezone, timedelta

API_KEY = os.environ["YOUTUBE_API_KEY"]

# ME:I 公式YouTubeチャンネル
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
    """
    YouTube の /shorts/{video_id} を確認して
    Shorts として扱われている動画を判定する。
    """

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

        final_url = response.url

        # Shorts のURLのままならShorts
        if "/shorts/" in final_url:
            return True

        return False

    except requests.RequestException as e:
        print(
            f"Shorts check failed: {video_id}: {e}"
        )

        # 判定に失敗した場合は
        # 誤って通常動画を消さないため残す
        return False


def get_latest_videos(
    uploads_playlist_id,
    max_results=30,
    output_limit=10,
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

        print(
            f"Checking: {snippet.get('title', '')}"
        )

        if is_youtube_short(video_id):
            print(
                f"  SKIP SHORTS: {video_id}"
            )
            continue

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

        posts.append(
            {
                "id": f"youtube_{video_id}",
                "platform": "youtube",
                "video_id": video_id,
                "title": snippet.get(
                    "title",
                    ""
                ),
                "published_at": content.get(
                    "videoPublishedAt",
                    snippet.get(
                        "publishedAt",
                        ""
                    ),
                ),
                "thumbnail": thumbnail,
                "url": (
                    "https://www.youtube.com/"
                    f"watch?v={video_id}"
                ),
            }
        )

        print(
            f"  ADD NORMAL VIDEO: {video_id}"
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

    posts = get_latest_videos(
        uploads_playlist_id,
        max_results=30,
        output_limit=10,
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

    print("=" * 50)
    print("YouTube SNS fetch complete")
    print(
        f"Channel: "
        f"{channel['snippet']['title']}"
    )
    print(
        f"Normal videos: {len(posts)}"
    )
    print(
        "Shorts were excluded."
    )
    print(
        "sns.json generated"
    )
    print("=" * 50)


if __name__ == "__main__":
    main()
