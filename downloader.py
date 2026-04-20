import os
import re
import time
import asyncio
from pathlib import Path
from typing import Optional
import yt_dlp

COOKIES_FILE = os.getenv("COOKIES_FILE", "")

X_URL_PATTERN = re.compile(
    r"https?://(www\.)?(twitter\.com|x\.com)/\w+/status/(\d+)"
)

# Simple in-memory cache: url -> (timestamp, media_list)
_cache: dict[str, tuple[float, list[dict]]] = {}
CACHE_TTL = 300  # 5 minutes


def is_valid_x_url(url: str) -> bool:
    return bool(X_URL_PATTERN.match(url.replace("twitter.com", "x.com")))


def normalize_url(url: str) -> str:
    return re.sub(r"https?://(www\.)?twitter\.com", "https://x.com", url)


def _detect_media_type(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    if ext in {"mp4", "webm", "mov", "avi", "mkv", "m4v"}:
        return "video"
    if ext in {"jpg", "jpeg", "png", "gif", "webp"}:
        return "image"
    return "other"


def _get_content_type(ext: str) -> str:
    mapping = {
        "mp4": "video/mp4",
        "webm": "video/webm",
        "mov": "video/quicktime",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
        "m4a": "audio/mp4",
    }
    return mapping.get(ext.lower().lstrip("."), "application/octet-stream")


def _extract(url: str) -> list[dict]:
    """Extract media info without downloading (blocking)."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    }
    if COOKIES_FILE and Path(COOKIES_FILE).exists():
        ydl_opts["cookiefile"] = COOKIES_FILE

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    tweet_id = info.get("id", "unknown")
    uploader = info.get("uploader", "unknown")
    upload_date = info.get("upload_date", "")
    title = info.get("title", "")

    entries = info.get("entries") or [info]
    results = []
    for i, entry in enumerate(entries):
        if not entry:
            continue

        formats = entry.get("formats") or []
        if formats:
            # Pick the best available format that has a direct URL
            best = next(
                (f for f in reversed(formats) if f.get("url") and not f.get("manifest_url")),
                formats[-1],
            )
            direct_url = best.get("url", "")
            http_headers = best.get("http_headers", {})
            ext = best.get("ext", "mp4")
            width = best.get("width") or entry.get("width")
            height = best.get("height") or entry.get("height")
            filesize = best.get("filesize") or best.get("filesize_approx") or entry.get("filesize")
        else:
            direct_url = entry.get("url", "")
            http_headers = entry.get("http_headers", {})
            ext = entry.get("ext", "jpg")
            width = entry.get("width")
            height = entry.get("height")
            filesize = entry.get("filesize") or entry.get("filesize_approx")

        if not direct_url:
            continue

        results.append({
            "index": i,
            "tweet_id": tweet_id,
            "uploader": uploader,
            "upload_date": upload_date,
            "title": title,
            "filename": f"{tweet_id}_{i + 1}.{ext}",
            "ext": ext,
            "media_type": _detect_media_type(ext),
            "content_type": _get_content_type(ext),
            "direct_url": direct_url,
            "http_headers": dict(http_headers),
            "width": width,
            "height": height,
            "duration": entry.get("duration"),
            "filesize": filesize,
        })

    return results


async def extract_media_info(url: str) -> list[dict]:
    """Async wrapper with in-memory cache."""
    url = normalize_url(url)
    if not is_valid_x_url(url):
        raise ValueError(f"유효한 X/Twitter URL이 아닙니다: {url}")

    now = time.monotonic()
    if url in _cache:
        ts, data = _cache[url]
        if now - ts < CACHE_TTL:
            return data

    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _extract, url)
    _cache[url] = (now, data)
    return data
