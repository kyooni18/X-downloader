import os
import logging
from typing import Optional
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from downloader import (
    CHUNK_SIZE,
    extract_media_info,
    open_direct_media_stream,
    stream_via_ytdlp,
    is_valid_x_url,
    normalize_url,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="X Media Downloader API",
    description="X(Twitter) 게시물의 미디어를 서버에 저장하지 않고 클라이언트로 직접 스트리밍합니다.",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class InfoRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not is_valid_x_url(v):
            raise ValueError("유효한 X/Twitter 게시물 URL이 아닙니다.")
        return v


class MediaItem(BaseModel):
    index: int
    tweet_id: str
    uploader: str
    upload_date: str
    filename: str
    media_type: str
    width: Optional[int]
    height: Optional[int]
    duration: Optional[float]
    filesize: Optional[int]
    stream_url: str


class InfoResponse(BaseModel):
    tweet_url: str
    media_count: int
    media: list[MediaItem]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/info", response_model=InfoResponse, summary="미디어 정보 조회")
async def get_info(req: InfoRequest):
    """게시물 URL의 모든 미디어 메타데이터와 스트림 URL을 반환합니다."""
    try:
        items = await extract_media_info(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"미디어 추출 실패: {exc}")

    if not items:
        raise HTTPException(status_code=404, detail="미디어를 찾을 수 없습니다.")

    encoded_url = quote(req.url, safe="")
    media = [
        MediaItem(
            **{k: v for k, v in item.items()
               if k not in ("ext", "content_type", "title", "direct_url")},
            stream_url=f"/api/stream?url={encoded_url}&index={item['index']}",
        )
        for item in items
    ]
    return InfoResponse(tweet_url=req.url, media_count=len(media), media=media)


@app.get("/api/stream", summary="미디어 스트리밍 다운로드")
async def stream_media(
    url: str = Query(..., description="X 게시물 URL"),
    index: int = Query(0, ge=0, description="미디어 인덱스 (0부터 시작)"),
):
    """
    yt-dlp subprocess를 통해 미디어를 서버 저장 없이 클라이언트로 직접 스트리밍합니다.
    HLS, DASH, MP4, 이미지 모두 지원합니다.
    """
    url = normalize_url(url)
    if not is_valid_x_url(url):
        raise HTTPException(status_code=400, detail="유효한 X/Twitter 게시물 URL이 아닙니다.")

    # Fetch metadata for filename / content-type
    try:
        items = await extract_media_info(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"미디어 추출 실패: {exc}")

    if not items:
        raise HTTPException(status_code=404, detail="미디어를 찾을 수 없습니다.")

    if index >= len(items):
        raise HTTPException(
            status_code=404,
            detail=f"인덱스 {index}가 범위를 초과합니다. 총 {len(items)}개의 미디어가 있습니다.",
        )

    item = items[index]
    response_headers = {
        "Content-Disposition": f'attachment; filename="{item["filename"]}"',
    }
    media_type = item["content_type"]
    direct_client = None
    direct_response = None

    direct_url = item.get("direct_url")
    if direct_url:
        try:
            direct_client, direct_response = await open_direct_media_stream(direct_url)
            upstream_length = direct_response.headers.get("Content-Length")
            if upstream_length and upstream_length.isdigit():
                response_headers["Content-Length"] = upstream_length
            media_type = direct_response.headers.get("Content-Type", media_type)
        except Exception as exc:
            logging.warning("direct stream failed, falling back to yt-dlp: %s", exc)
            direct_client = None
            direct_response = None

    if direct_response is not None:
        async def generator():
            try:
                async for chunk in direct_response.aiter_bytes(CHUNK_SIZE):
                    yield chunk
            finally:
                await direct_response.aclose()
                await direct_client.aclose()

        return StreamingResponse(
            generator(),
            media_type=media_type,
            headers=response_headers,
        )

    async def fallback_generator():
        try:
            async for chunk in stream_via_ytdlp(url, index):
                yield chunk
        except RuntimeError as exc:
            logging.error("yt-dlp stream error: %s", exc)

    return StreamingResponse(
        fallback_generator(),
        media_type=media_type,
        headers=response_headers,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
