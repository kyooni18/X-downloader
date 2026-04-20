# X Media Downloader API

X(Twitter) 게시물에 첨부된 이미지, 동영상, GIF를 다운로드하는 REST API 서버입니다.

## 기술 스택

- **Python 3.11+**
- **FastAPI** — REST API 프레임워크
- **yt-dlp** — X/Twitter 미디어 다운로드 엔진
- **uvicorn** — ASGI 서버

## 설치 및 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 서버 실행 (기본 포트: 8000)
python main.py

# 또는 직접 uvicorn 실행
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/health` | 서버 상태 확인 |
| `POST` | `/api/download` | 미디어 동기 다운로드 |
| `POST` | `/api/download/async` | 미디어 비동기 다운로드 (job 반환) |
| `GET` | `/api/jobs/{job_id}` | 비동기 작업 상태 조회 |
| `GET` | `/media/{filename}` | 다운로드된 파일 직접 수신 |
| `GET` | `/api/files` | 저장된 파일 목록 조회 |
| `DELETE` | `/api/files/{filename}` | 파일 삭제 |

### 동기 다운로드 예시

```bash
curl -X POST http://localhost:8000/api/download \
  -H "Content-Type: application/json" \
  -d '{"url": "https://x.com/username/status/1234567890"}'
```

**응답:**
```json
{
  "success": true,
  "tweet_url": "https://x.com/username/status/1234567890",
  "media_count": 2,
  "media": [
    {
      "tweet_id": "1234567890",
      "uploader": "username",
      "title": "...",
      "upload_date": "20240101",
      "filename": "1234567890_1.mp4",
      "size_bytes": 1048576,
      "media_type": "video",
      "download_url": "/media/1234567890_1.mp4"
    }
  ]
}
```

### 비동기 다운로드 예시

```bash
# 1. 다운로드 작업 시작
curl -X POST http://localhost:8000/api/download/async \
  -H "Content-Type: application/json" \
  -d '{"url": "https://x.com/username/status/1234567890"}'
# → {"job_id": "uuid", "status": "pending"}

# 2. 작업 상태 조회
curl http://localhost:8000/api/jobs/{job_id}
# → {"job_id": "...", "status": "done", "result": {...}}
```

### 파일 다운로드

```bash
curl -O http://localhost:8000/media/1234567890_1.mp4
```

## Swagger 문서

서버 실행 후 http://localhost:8000/docs 에서 인터랙티브 API 문서를 확인할 수 있습니다.

## 쿠키 설정 (선택사항)

로그인이 필요한 콘텐츠를 다운로드하려면 브라우저 쿠키를 내보내서 사용합니다:

```bash
# .env.example을 .env로 복사 후 COOKIES_FILE 경로 설정
cp .env.example .env
```
