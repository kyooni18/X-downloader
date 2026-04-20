import os
import asyncio
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
import uvicorn

from downloader import download_tweet_media, is_valid_x_url, DOWNLOADS_DIR

# ── In-memory job store ───────────────────────────────────────────────────────
# Maps job_id -> {"status": ..., "result": ..., "error": ...}
_jobs: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    yield


app = FastAPI(
    title="X Media Downloader API",
    description="X(Twitter) 게시물에 첨부된 모든 미디어를 다운로드하는 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not is_valid_x_url(v.replace("twitter.com", "x.com")):
            raise ValueError("유효한 X/Twitter 게시물 URL이 아닙니다.")
        return v


class MediaItem(BaseModel):
    tweet_id: str
    uploader: str
    title: str
    upload_date: str
    filename: str
    size_bytes: int
    media_type: str
    download_url: str


class DownloadResponse(BaseModel):
    success: bool
    tweet_url: str
    media_count: int
    media: list[MediaItem]


class JobStatus(BaseModel):
    job_id: str
    status: str          # pending | running | done | error
    result: Optional[DownloadResponse] = None
    error: Optional[str] = None


# ── Background worker ─────────────────────────────────────────────────────────

async def _run_job(job_id: str, url: str):
    _jobs[job_id]["status"] = "running"
    try:
        items = await download_tweet_media(url)
        media = [
            MediaItem(
                **item,
                download_url=f"/media/{item['filename']}",
            )
            for item in items
        ]
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["result"] = DownloadResponse(
            success=True,
            tweet_url=url,
            media_count=len(media),
            media=media,
        )
    except Exception as exc:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"] = str(exc)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/download", response_model=DownloadResponse, summary="미디어 동기 다운로드")
async def download_sync(req: DownloadRequest):
    """
    X 게시물 URL을 받아 모든 미디어를 즉시 다운로드하고 결과를 반환합니다.
    처리 시간이 길 경우 /api/download/async 를 사용하세요.
    """
    try:
        items = await download_tweet_media(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"다운로드 실패: {exc}")

    if not items:
        raise HTTPException(status_code=404, detail="미디어를 찾을 수 없습니다.")

    media = [
        MediaItem(**item, download_url=f"/media/{item['filename']}")
        for item in items
    ]
    return DownloadResponse(
        success=True,
        tweet_url=req.url,
        media_count=len(media),
        media=media,
    )


@app.post("/api/download/async", response_model=JobStatus, status_code=202, summary="미디어 비동기 다운로드")
async def download_async(req: DownloadRequest, background_tasks: BackgroundTasks):
    """
    비동기로 다운로드를 시작하고 job_id를 즉시 반환합니다.
    /api/jobs/{job_id} 로 진행 상황을 확인하세요.
    """
    import uuid
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "pending", "result": None, "error": None}
    background_tasks.add_task(_run_job, job_id, req.url)
    return JobStatus(job_id=job_id, status="pending")


@app.get("/api/jobs/{job_id}", response_model=JobStatus, summary="비동기 작업 상태 조회")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="존재하지 않는 작업입니다.")
    return JobStatus(job_id=job_id, **job)


@app.get("/media/{filename}", summary="다운로드된 파일 제공")
async def serve_media(filename: str):
    """다운로드된 미디어 파일을 직접 반환합니다."""
    # Prevent path traversal
    safe_name = Path(filename).name
    target = None
    for f in DOWNLOADS_DIR.rglob(safe_name):
        target = f
        break

    if target is None or not target.exists():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    return FileResponse(str(target), filename=safe_name)


@app.get("/api/files", summary="다운로드된 파일 목록 조회")
async def list_files():
    """서버에 저장된 모든 다운로드 파일 목록을 반환합니다."""
    files = []
    for f in DOWNLOADS_DIR.rglob("*"):
        if f.is_file():
            files.append({
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "download_url": f"/media/{f.name}",
            })
    return {"total": len(files), "files": files}


@app.delete("/api/files/{filename}", summary="파일 삭제")
async def delete_file(filename: str):
    safe_name = Path(filename).name
    target = None
    for f in DOWNLOADS_DIR.rglob(safe_name):
        target = f
        break

    if target is None or not target.exists():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    target.unlink()
    return {"deleted": safe_name}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
