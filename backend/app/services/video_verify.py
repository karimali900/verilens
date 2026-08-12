import json
import os
import shutil
import subprocess

from app.config import settings

FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"
YTDLP_BIN = os.environ.get("VERILENS_YTDLP_BIN", "yt-dlp")
YTDLP_FALLBACK = "/home/karim/miniconda3/bin/yt-dlp"
MAX_URL_SECONDS = 120


def _which(binary: str, fallback: str = "") -> str:
    found = shutil.which(binary)
    return found or fallback


def probe(path: str) -> dict:
    r = subprocess.run(
        [
            _which(FFPROBE),
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,codec_name,r_frame_rate",
            "-show_entries", "format=duration,size,format_name",
            "-of", "json",
            path,
        ],
        capture_output=True, text=True, timeout=120,
    )
    meta = {"duration": None, "width": None, "height": None, "codec": None, "fps": None, "size": None}
    try:
        info = json.loads(r.stdout)
        stream = (info.get("streams") or [{}])[0]
        fmt = info.get("format") or {}
        meta["width"] = stream.get("width")
        meta["height"] = stream.get("height")
        meta["codec"] = stream.get("codec_name")
        meta["fps"] = stream.get("r_frame_rate")
        meta["duration"] = round(float(fmt.get("duration", 0) or 0), 2) or None
        meta["size"] = int(fmt.get("size", 0) or 0) or None
    except Exception:
        pass
    return meta


def extract_frames(path: str, out_dir: str, n: int = 6) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    meta = probe(path)
    duration = meta.get("duration") or 1
    if duration <= 0:
        duration = 1
    fps = min(n, max(1, int(duration))) / duration
    prefix = os.path.join(out_dir, "frame_%03d.jpg")
    r = subprocess.run(
        [_which(FFMPEG), "-y", "-v", "error", "-i", path, "-vf", f"fps={fps:.4f}", "-q:v", "3", prefix],
        capture_output=True, text=True, timeout=300,
    )
    frames = sorted(
        os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.startswith("frame_") and f.endswith(".jpg")
    )
    frames = frames[:n]
    if not frames and r.stderr:
        raise RuntimeError(f"Frame extraction failed: {r.stderr[:300]}")
    return frames


def resolve_video_url(url: str, workdir: str) -> tuple[str, dict]:
    """Download a video from a URL (YouTube etc.) via yt-dlp. Returns (path, info)."""
    ytdlp = _which(YTDLP_BIN, YTDLP_FALLBACK)
    if not ytdlp or not os.path.exists(ytdlp):
        raise RuntimeError("yt-dlp is not installed on the server — video URL verification unavailable")

    info_r = subprocess.run(
        [ytdlp, "--no-warnings", "--skip-download", "-J", url],
        capture_output=True, text=True, timeout=90,
    )
    if info_r.returncode != 0:
        raise RuntimeError(f"Could not read video info: {info_r.stderr[:300]}")
    info = json.loads(info_r.stdout or "{}")

    out = os.path.join(workdir, "video.%(ext)s")
    cmd = [
        ytdlp, "--no-warnings", "--no-playlist",
        "-f", "best[height<=720]/best",
        "--max-filesize", "400M",
        "--output", out,
        url,
    ]
    duration = info.get("duration") or 0
    if duration > MAX_URL_SECONDS:
        cmd = cmd[:1] + ["--download-sections", f"*0-{MAX_URL_SECONDS}"] + cmd[1:]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=420)
    if r.returncode != 0 and "--download-sections" in cmd:
        cmd.remove("--download-sections")
        cmd.remove(f"*0-{MAX_URL_SECONDS}")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=420)
    if r.returncode != 0:
        raise RuntimeError(f"Video download failed: {r.stderr[-400:]}")

    files = [f for f in os.listdir(workdir) if f.startswith("video.") and not f.endswith((".part", ".ytdl"))]
    if not files:
        raise RuntimeError("Video downloaded but no media file found")
    path = os.path.join(workdir, files[0])

    meta = probe(path)
    return path, {
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "url": url,
        **meta,
    }
