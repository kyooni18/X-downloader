import os
from typing import Optional
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from downloader import extract_media_info, is_valid_x_url

CHUNK_SIZE = 64 * 1024  # 64 KB


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="X Media Downloader API",
    description="X(Twitter) 게시물의 미디어를 서버에 저장하지 않고 클라이언트로 직접 중계합니다.",
    version="2.0.0",
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
    """
    게시물 URL의 모든 미디어 메타데이터와 스트림 URL을 반환합니다.
    파일은 서버에 저장되지 않습니다.
    """
    try:
        items = await extract_media_info(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"미디어 추출 실패: {exc}")

    if not items:
        raise HTTPException(status_code=404, detail="미디어를 찾을 수 없습니다.")

    media = [
        MediaItem(
            **{k: v for k, v in item.items() if k not in ("direct_url", "http_headers", "ext", "content_type", "title")},
            stream_url=f"/api/stream?url={req.url}&index={item['index']}",
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
    지정한 미디어를 서버에 저장하지 않고 클라이언트로 직접 스트리밍합니다.
    """
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
    direct_url: str = item["direct_url"]
    headers: dict = item["http_headers"]
    content_type: str = item["content_type"]
    filename: str = item["filename"]
    filesize: Optional[int] = item.get("filesize")

    async def proxy_stream():
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            async with client.stream("GET", direct_url, headers=headers) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                    yield chunk

    response_headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    if filesize:
        response_headers["Content-Length"] = str(filesize)

    return StreamingResponse(
        proxy_stream(),
        media_type=content_type,
        headers=response_headers,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
