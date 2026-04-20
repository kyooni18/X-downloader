# X Media Downloader API

X(Twitter) 게시물의 이미지·동영상·GIF를 **서버에 저장하지 않고** 클라이언트로 직접 스트리밍하는 중계 API 서버입니다.

## 기술 스택

- **Python 3.11+**
- **FastAPI** — REST API 프레임워크
- **yt-dlp** — X/Twitter 미디어 URL 추출
- **httpx** — 미디어 스트리밍 프록시
- **uvicorn** — ASGI 서버

## 설치 및 실행

```bash
pip install -r requirements.txt
python main.py  # 기본 포트: 8000
```

## API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/health` | 서버 상태 확인 |
| `POST` | `/api/info` | 게시물의 미디어 목록 및 메타데이터 조회 |
| `GET` | `/api/stream?url=...&index=0` | 미디어 스트리밍 다운로드 (서버 저장 없음) |

### 1단계 — 미디어 정보 조회

```bash
curl -X POST http://localhost:8000/api/info \
  -H "Content-Type: application/json" \
  -d '{"url": "https://x.com/username/status/1234567890"}'
```

```json
{
  "tweet_url": "https://x.com/username/status/1234567890",
  "media_count": 2,
  "media": [
    {
      "index": 0,
      "tweet_id": "1234567890",
      "uploader": "username",
      "filename": "1234567890_1.mp4",
      "media_type": "video",
      "width": 1280,
      "height": 720,
      "duration": 30.5,
      "filesize": 4194304,
      "stream_url": "/api/stream?url=https://x.com/...&index=0"
    }
  ]
}
```

### 2단계 — 스트리밍 다운로드

```bash
# 브라우저에서 직접 열거나 curl로 저장
curl -OJ "http://localhost:8000/api/stream?url=https://x.com/username/status/1234567890&index=0"
```

서버는 X CDN에서 받은 데이터를 **메모리 버퍼(64KB chunk)로만 경유**하며 디스크에 기록하지 않습니다.  
추출된 미디어 URL 정보는 5분간 메모리 캐시됩니다.

## 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `PORT` | `8000` | 서버 포트 |
| `COOKIES_FILE` | (없음) | yt-dlp 쿠키 파일 경로 (로그인 필요 콘텐츠용) |

## Swagger 문서

`http://localhost:8000/docs`
