import os
import json
import requests
from datetime import datetime, timezone, timedelta

API_KEY = os.environ["YOUTUBE_API_KEY"]

# ME:I公式YouTube
CHANNEL_ID = "UCvTsv4KmVuBdECI08_HR87Q"

JST = timezone(timedelta(hours=9))


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


def get_latest_videos(uploads_playlist_id, max_results=10):
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

        thumbnails = snippet.get("thumbnails", {})

        thumbnail = (
            thumbnails.get("maxres", {}).get("url")
            or thumbnails.get("standard", {}).get("url")
            or thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
            or ""
        )

        posts.append(
            {
                "id": f"youtube_{video_id}",
                "platform": "youtube",
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "published_at": content.get(
                    "videoPublishedAt",
                    snippet.get("publishedAt", ""),
                ),
                "thumbnail": thumbnail,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )

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
        max_results=10,
    )

    output = {
        "generated_at": datetime.now(JST).isoformat(),
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
    print(f"Channel: {channel['snippet']['title']}")
    print(f"Posts: {len(posts)}")
    print("sns.json generated")
    print("=" * 50)


if __name__ == "__main__":
    main()
