# المُدقِّق VeriLens

Verify images (real or fake?) and news (true or false? who published it first?) by searching the web.
التحقق من الصور (حقيقية أم مزيفة؟) والأخبار (صحيحة أم لا؟ ومن نشرها أولاً) عبر البحث في الويب.

Bilingual UI — English / العربية. Built by **Karim Abdelaziz** · من تطوير **كريم عبد العزيز**

## What it does

**Image verification** (`/verify/image`):
- **EXIF forensics** — capture date, GPS, device, editing-software signatures. Missing metadata is **neutral** (WhatsApp/social media strip it from every real photo), only present evidence and edit-software signatures move the score
- **Error Level Analysis (ELA)** — highlights re-compression / editing hotspots as a heatmap; re-compression alone is **not** treated as evidence of a fake
- **Reverse image search** — uploads a copy to a public host and queries **two engines in parallel**: Bing (machine-parsed matches, ranked with perceptual-hash similarity) and **Google Lens** (the upload is processed server-side; results need a browser, so the verified vision-search URL is deep-linked for one click). Yandex Images is also deep-linked. Every engine reports its own status (ok / empty / link-only / failed) so a blocked engine is never silently reported as "0 matches".

**News verification** (`/verify/news`):
- Searches **GDELT** (global news index), **Google News**, **Reddit**, and fact-check databases simultaneously
- **First-publisher detection** — earliest dated trace across all sources (e.g. "AP News, 2026-06-23")
- **Fact-check watch** — surfaces articles from fact-check domains and false/hoax/debunked signals
- **Verdict score** (0-100) based on independent publication count, fact-check flags, satire detection, social engagement

**Video verification** (`/verify/video` and `/verify/video_url`):
- Upload a video file **or paste a URL** (YouTube, TikTok, X, Instagram… — downloaded server-side via `yt-dlp`)
- **6 key frames** extracted with ffmpeg at even intervals across the clip
- Every frame independently runs the full image pipeline (ELA + reverse search), and the verdict is a **consensus across all frames** — matching any frame to existing footage proves the clip circulates publicly
- Per-frame verdicts and match counts shown as clickable cards; view web matches per frame, or jump to the best frame
- URL mode also surfaces source metadata: title, uploader, view count

## Stack

- Backend: FastAPI + SQLite (port 8012)
- Frontend: React + Vite (port 3012)
- Video: `ffmpeg`/`ffprobe` for frame extraction, `yt-dlp` for URL downloads (`VERILENS_YTDLP_BIN` to override the binary path)
- No API keys required for the core flow

## Run

```bash
# Docker
docker compose up --build      # frontend http://localhost:3012

# Dev
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/uvicorn app.main:app --port 8012 --reload
cd frontend && npm install && npm run dev   # http://localhost:3012
```

## Optional API keys (env vars)

| Variable | Effect |
|---|---|
| `VERILENS_BING_API_KEY` | Official Bing Visual Search API (free tier) instead of HTML parsing |
| `VERILENS_NEWSAPI_KEY` | Reserved for NewsAPI integration |
| `VERILENS_GOOGLE_FACTCHECK_KEY` | Google Fact Check Tools API |

## Honest limits

- ELA/EXIF/verdict heuristics are **signals, not proof** — always inspect the sources linked in the results.
- Scoring is evidence-based: absence of metadata or web matches is neutral, so a real shared photo returns "unverified", never "fake", unless actual negative signals (edit-software signatures, satire, contradiction by sources) are found.
- Google Lens and Bing HTML endpoints may change without notice; matches may be empty for fresh or AI-generated images.
- Reverse search requires the backend to reach catbox.moe / 0x0.st and the search engines.
- "Who first published" = earliest trace *within the scanned window* (GDELT 45 days + Google News recent), not a universal first.

## API

| Endpoint | Description |
|---|---|
| `POST /api/v1/verify/image` | multipart `file` → forensics + reverse search + verdict |
| `POST /api/v1/verify/news` | `{"query": "..."}` → articles, first publisher, fact checks, verdict |
| `POST /api/v1/verify/video` | multipart video `file` → 6 key frames, per-frame reverse search, consensus verdict |
| `POST /api/v1/verify/video_url` | `{"url": "..."}` → downloads via yt-dlp (≤120s of long videos), frames, verdict |
| `GET /api/v1/frame/{job}/{name}` | Serves extracted key frames to the frontend |
| `GET /api/v1/history` | Recent verification jobs |
| `GET /health` | Health check |
