import os
import re
import sys
import time
import asyncio
from pathlib import Path
from typing import Optional, AsyncGenerator
import yt_dlp

COOKIES_FILE = os.getenv("COOKIES_FILE", "")
CHUNK_SIZE = 64 * 1024

# Pre-merged MP4 preferred — no ffmpeg merge needed, single direct URL
FORMAT = "best[ext=mp4]/best"

X_URL_PATTERN = re.compile(
    r"https?://(www\.)?(twitter\.com|x\.com)/\w+/status/(\d+)"
)

_cache: dict[str, tuple[float, list[dict]]] = {}
CACHE_TTL = 300


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
        "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "gif": "image/gif", "webp": "image/webp",
    }
    return mapping.get(ext.lower().lstrip("."), "application/octet-stream")


def _build_ydl_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,
        "format": FORMAT,
    }
    if COOKIES_FILE and Path(COOKIES_FILE).exists():
        opts["cookiefile"] = COOKIES_FILE
    return opts


def _extract(url: str) -> list[dict]:
    """Extract media metadata without downloading."""
    with yt_dlp.YoutubeDL(_build_ydl_opts()) as ydl:
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

        # yt-dlp puts the selected format's URL at the top level after processing
        direct_url = entry.get("url", "")
        ext = entry.get("ext", "mp4")
        width = entry.get("width")
        height = entry.get("height")
        filesize = entry.get("filesize") or entry.get("filesize_approx")

        # requested_formats present means separate video+audio streams (needs merge)
        requested = entry.get("requested_formats") or []
        if requested:
            # Use first stream URL as placeholder; streaming will use subprocess
            direct_url = requested[0].get("url", "")
            ext = requested[0].get("ext", ext)
            width = width or requested[0].get("width")
            height = height or requested[0].get("height")
            filesize = filesize or requested[0].get("filesize")

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
            "width": width,
            "height": height,
            "duration": entry.get("duration"),
            "filesize": filesize,
        })

    return results


async def extract_media_info(url: str) -> list[dict]:
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


async def stream_via_ytdlp(url: str, index: int) -> AsyncGenerator[bytes, None]:
    """Stream media directly from X CDN via yt-dlp subprocess — no temp files."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--format", FORMAT,
        "--playlist-items", str(index + 1),  # 1-based
        "-o", "-",  # pipe to stdout
        "--quiet",
        "--no-warnings",
    ]
    if COOKIES_FILE and Path(COOKIES_FILE).exists():
        cmd += ["--cookies", COOKIES_FILE]
    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        # DEVNULL prevents stderr pipe-buffer deadlock:
        # if yt-dlp writes to stderr faster than we read it, the 64KB kernel
        # pipe buffer fills up and blocks stdout writes too.
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        while True:
            chunk = await proc.stdout.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        proc.stdout.close()
        rc = await proc.wait()
        if rc != 0:
            raise RuntimeError(f"yt-dlp exited with code {rc}")
