import os
import re
import asyncio
from pathlib import Path
from typing import Optional
import yt_dlp

COOKIES_FILE = os.getenv("COOKIES_FILE", "")

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

X_URL_PATTERN = re.compile(
    r"https?://(www\.)?(twitter\.com|x\.com)/\w+/status/(\d+)"
)


def is_valid_x_url(url: str) -> bool:
    return bool(X_URL_PATTERN.match(url))


def normalize_url(url: str) -> str:
    return re.sub(r"https?://(www\.)?twitter\.com", "https://x.com", url)


def _download_media(url: str, output_dir: Path) -> list[dict]:
    """Download all media from a tweet and return metadata list."""
    downloaded = []

    ydl_opts = {
        "outtmpl": str(output_dir / "%(id)s_%(autonumber)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "writeinfojson": False,
        "writethumbnail": False,
        "noplaylist": True,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    }
    if COOKIES_FILE and Path(COOKIES_FILE).exists():
        ydl_opts["cookiefile"] = COOKIES_FILE

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    tweet_id = info.get("id", "unknown")
    uploader = info.get("uploader", "unknown")
    title = info.get("title", "")
    upload_date = info.get("upload_date", "")

    entries = info.get("entries") or [info]
    for entry in entries:
        if not entry:
            continue
        filepath_str = entry.get("requested_downloads", [{}])[0].get("filepath")
        if not filepath_str:
            continue
        filepath = Path(filepath_str)
        if filepath.exists():
            downloaded.append({
                "tweet_id": tweet_id,
                "uploader": uploader,
                "title": title,
                "upload_date": upload_date,
                "filename": filepath.name,
                "size_bytes": filepath.stat().st_size,
                "media_type": _detect_media_type(filepath.suffix),
                "url": entry.get("url", ""),
            })

    # Also handle photos (yt-dlp downloads them as a single entry)
    if not downloaded:
        for f in output_dir.glob(f"{tweet_id}_*"):
            downloaded.append({
                "tweet_id": tweet_id,
                "uploader": uploader,
                "title": title,
                "upload_date": upload_date,
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "media_type": _detect_media_type(f.suffix),
                "url": "",
            })

    return downloaded


def _detect_media_type(suffix: str) -> str:
    suffix = suffix.lower()
    if suffix in {".mp4", ".webm", ".mov", ".avi", ".mkv"}:
        return "video"
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return "image"
    return "other"


async def download_tweet_media(url: str, tweet_dir: Optional[Path] = None) -> list[dict]:
    """Async wrapper around blocking yt-dlp download."""
    url = normalize_url(url)
    if not is_valid_x_url(url):
        raise ValueError(f"Invalid X/Twitter URL: {url}")

    match = X_URL_PATTERN.match(url)
    tweet_id = match.group(3) if match else "unknown"
    output_dir = tweet_dir or (DOWNLOADS_DIR / tweet_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_media, url, output_dir)
