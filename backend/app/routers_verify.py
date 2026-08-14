import asyncio
import json
import os
import re
import shutil
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import VerifyJob, get_db
from app.services.image_forensics import ela_analysis, exif_analysis, image_stats, ocr_text
from app.services.news_verify import verify_news
from app.services.reverse_search import reverse_search
from app.services.video_verify import extract_frames, probe, resolve_video_url

router = APIRouter(prefix="/api/v1", tags=["verify"])


class NewsQuery(BaseModel):
    query: str


class VideoUrlQuery(BaseModel):
    url: str


def _claim_query(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= 4]
    best = max(lines, key=len, default="")
    if len(best) < 30:
        best = re.sub(r"\s+", " ", text)
    best = re.sub(r"\s+", " ", best)
    return best[:220]


def _image_verdict(ela: dict, exif: dict, reverse: dict, text_check: dict | None = None) -> dict:
    score = 50
    reasons = []

    # EXIF: only positive evidence counts. Missing metadata is NORMAL
    # (screenshots, WhatsApp/Telegram, social re-uploads strip it) - not a penalty.
    if exif.get("ok"):
        if exif.get("date_taken"):
            score += 12
            reasons.append("EXIF capture date present — original-camera signal.")
        if exif.get("has_gps"):
            score += 5
        if exif.get("device"):
            score += 5
        for anomaly in exif.get("anomalies", []):
            if "editing software" in anomaly.lower():
                score -= 12
                reasons.append(anomaly)
    else:
        reasons.append("No EXIF metadata — normal for screenshots and photos shared via WhatsApp/social media (they strip it).")

    # ELA: re-compression is NORMAL for shared photos, so high ELA is not evidence
    # of a fake - only a note. Low ELA is a weak positive.
    analysis = ela.get("analysis")
    if analysis == "single":
        score += 5
        reasons.append("Low ELA error — consistent with a single original compression.")
    elif analysis == "edited":
        reasons.append("High ELA error — typical after social-media re-compression; verify via source search.")

    # Reverse search: the strongest signal. Absence of matches is NEUTRAL
    # (fresh, private, or AI-generated images all have none) - not a penalty.
    # But if an engine failed or was blocked, say so: 0 may be a search failure.
    matches = reverse.get("match_count", 0)
    engines = reverse.get("engines", {})
    engine_failures = [name for name, e in engines.items() if e.get("status") == "error"]
    engine_ok = [name for name, e in engines.items() if e.get("status") == "ok" and e.get("matches", 0) > 0]

    if engine_failures:
        reasons.append(
            f"Search engine(s) failed/blocked ({', '.join(engine_failures)}) — 0 matches may be an engine failure, not absence."
        )
    if not engine_failures and not matches:
        reasons.append("No similar images found on any search engine — may be new, private, or generated.")

    best_sim = max((m.get("similarity") or 0 for m in reverse.get("matches", [])), default=0)
    if matches >= 5:
        score += 18
        reasons.append(f"{matches} similar images found via {', '.join(engine_ok) or 'search engines'} — widely circulated/re-posted.")
        if best_sim >= 80:
            score += 7
            reasons.append("Near-duplicate matches found — this image circulates publicly.")
    elif matches >= 1:
        score += 8
        reasons.append(f"{matches} similar image(s) found via {', '.join(engine_ok) or 'search engines'}.")
        if best_sim >= 80:
            score += 4

    if text_check:
        tc_v = text_check.get("verdict", {})
        n_ind = len(tc_v.get("independent_domains") or [])
        quote = (text_check.get("query") or "")[:80]
        if n_ind >= 2 and tc_v.get("score", 0) >= 60:
            score += 10
            reasons.append(f"Text embedded in the image (“{quote}”) is reported by {n_ind} independent publications.")
        elif n_ind >= 2:
            score += 5
            reasons.append(f"Embedded text (“{quote}”) found in {n_ind} publications — coverage is limited.")
        if tc_v.get("verdict") == "likely_fake" and any("question this claim" in r for r in tc_v.get("reasons", [])):
            score -= 20
            reasons.append("The text embedded in this image is disputed or questioned by fact-checking sources.")
        elif tc_v.get("verdict") == "likely_fake":
            reasons.append("Embedded text matches no public news record — absence of coverage is not evidence it is false.")

    score = max(0, min(100, score))
    if score >= 65:
        verdict, label = "likely_real", "likely real"
    elif score >= 40:
        verdict, label = "unverified", "unverified"
    else:
        verdict, label = "likely_fake", "likely fake"
    return {"verdict": verdict, "label": label, "score": score, "reasons": reasons}


async def _reverse_wrapped(data: bytes, name: str) -> dict:
    try:
        return await reverse_search(data, name)
    except Exception as e:
        return {"error": str(e), "matches": [], "match_count": 0, "domains": {}}


@router.post("/verify/image")
async def verify_image(file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Image larger than {settings.MAX_UPLOAD_MB}MB")

    safe_name = uuid.uuid4().hex + "_" + os.path.basename(file.filename or "image.jpg")
    path = os.path.join(settings.UPLOAD_DIR, safe_name)
    with open(path, "wb") as f:
        f.write(data)

    stats = image_stats(data)
    exif = exif_analysis(data)
    ela = ela_analysis(data)

    reverse, ocr = await asyncio.gather(
        _reverse_wrapped(data, safe_name),
        asyncio.to_thread(ocr_text, data),
    )

    text_check = None
    if ocr.get("ok") and ocr.get("chars", 0) >= 30:
        query = _claim_query(ocr["text"])
        if query:
            try:
                text_check = await verify_news(query)
            except Exception:
                text_check = None

    verdict = _image_verdict(ela, exif, reverse, text_check)

    result = {"stats": stats, "exif": exif, "ela": ela, "reverse": reverse, "ocr": ocr,
              "text_check": text_check, "verdict": verdict}

    job = VerifyJob(kind="image", raw_before=file.filename or "", result=json.dumps(result, default=str))
    db.add(job)
    db.commit()

    return JSONResponse(result)


@router.post("/verify/news")
async def verify_news_endpoint(payload: NewsQuery, db: Session = Depends(get_db)):
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Empty query")
    result = await verify_news(payload.query)
    job = VerifyJob(kind="news", raw_before=payload.query, result=json.dumps(result, default=str))
    db.add(job)
    db.commit()
    return JSONResponse(result)


def _video_verdict(frames: list[dict], meta: dict) -> dict:
    scores = [f["verdict"]["score"] for f in frames]
    score = round(sum(scores) / len(scores)) if scores else 50
    matched = sum(1 for f in frames if f["reverse"].get("match_count", 0) > 0)
    reasons = [f"{len(frames)} frames analyzed across the clip"]
    reasons.append(f"{matched}/{len(frames)} frames matched images already on the web")
    engine_failures = set()
    for f in frames:
        for name, e in (f["reverse"].get("engines") or {}).items():
            if e.get("status") == "error":
                engine_failures.add(name)
    if engine_failures:
        reasons.append(f"Search engine(s) blocked/failed ({', '.join(sorted(engine_failures))}) on some frames — low matches may be a search failure.")
    elif matched == 0:
        reasons.append("No frame matched anything on the web — footage may be fresh, private, or AI-generated.")
    elif matched == len(frames):
        reasons.append("Every frame matched existing footage — this clip circulates publicly.")

    if score >= 65:
        verdict, label = "likely_real", "likely real"
    elif score >= 40:
        verdict, label = "unverified", "unverified"
    else:
        verdict, label = "likely_fake", "likely fake"
    return {"verdict": verdict, "label": label, "score": score, "reasons": reasons}


async def _verify_video_workflow(path: str, source_name: str) -> dict:
    os.makedirs(settings.FRAME_DIR, exist_ok=True)
    job_id = uuid.uuid4().hex[:10]
    job_dir = os.path.join(settings.FRAME_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    meta = probe(path)
    frame_paths = extract_frames(path, job_dir, n=6)

    frames = []
    for i, fp in enumerate(frame_paths, start=1):
        with open(fp, "rb") as fh:
            data = fh.read()
        exif = exif_analysis(data)
        ela = ela_analysis(data)
        try:
            reverse = await reverse_search(data, f"frame_{i}.jpg")
        except Exception as e:
            reverse = {"error": str(e), "matches": [], "match_count": 0, "domains": {}}
        fverdict = _image_verdict(ela, exif, reverse)
        frames.append({
            "index": i,
            "file": os.path.join(job_id, os.path.basename(fp)),
            "exif": exif,
            "ela": ela,
            "reverse": reverse,
            "verdict": fverdict,
        })

    verdict = _video_verdict(frames, meta)
    return {"source": source_name, "meta": meta, "frames": frames, "verdict": verdict}


@router.post("/verify/video")
async def verify_video(file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.MAX_VIDEO_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Video larger than {settings.MAX_VIDEO_MB}MB")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    safe_name = uuid.uuid4().hex + "_" + os.path.basename(file.filename or "video.mp4")
    path = os.path.join(settings.UPLOAD_DIR, safe_name)
    with open(path, "wb") as f:
        f.write(data)

    try:
        result = await _verify_video_workflow(path, file.filename or "uploaded video")
    finally:
        if os.path.exists(path):
            os.remove(path)

    job = VerifyJob(kind="video", raw_before=file.filename or "", result=json.dumps(result, default=str))
    db.add(job)
    db.commit()
    return JSONResponse(result)


@router.post("/verify/video_url")
async def verify_video_url(payload: VideoUrlQuery, db: Session = Depends(get_db)):
    if not payload.url.strip():
        raise HTTPException(status_code=400, detail="Empty URL")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    job_id = uuid.uuid4().hex[:10]
    workdir = os.path.join(settings.UPLOAD_DIR, "url_" + job_id)
    os.makedirs(workdir, exist_ok=True)

    try:
        path, info = await _verify_video_url_download(payload.url, workdir)
        try:
            result = await _verify_video_workflow(path, info.get("title") or payload.url)
        finally:
            if os.path.exists(path):
                os.remove(path)
        result["meta"]["video_title"] = info.get("title")
        result["meta"]["uploader"] = info.get("uploader")
        result["meta"]["view_count"] = info.get("view_count")
        result["meta"]["duration"] = info.get("duration") or result["meta"].get("duration")
        result["source"] = payload.url
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    job = VerifyJob(kind="video", raw_before=payload.url, result=json.dumps(result, default=str))
    db.add(job)
    db.commit()
    return JSONResponse(result)


async def _verify_video_url_download(url: str, workdir: str):
    return await _run_in_thread(resolve_video_url, url, workdir)


async def _run_in_thread(fn, *args):
    import asyncio
    return await asyncio.to_thread(fn, *args)


@router.get("/frame/{job_dir}/{name}")
def frame(job_dir: str, name: str):
    path = os.path.join(settings.FRAME_DIR, job_dir, name)
    if not os.path.exists(path) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/history")
def history(limit: int = 10, db: Session = Depends(get_db)):
    jobs = db.query(VerifyJob).order_by(VerifyJob.id.desc()).limit(limit).all()
    out = []
    for j in jobs:
        try:
            r = json.loads(j.result)
            label = r.get("verdict", {}).get("label", "")
        except Exception:
            label = ""
        out.append({"id": j.id, "kind": j.kind, "input": j.raw_before, "verdict": label, "created_at": j.created_at.isoformat()})
    return {"items": out}