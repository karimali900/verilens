import base64
import io
import os
import re

import exifread
import pytesseract
from PIL import Image, ImageChops, ImageOps

os.environ.setdefault("PIL_SIMD_OPTIMIZE", "0")

TESSDATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "tessdata"
)


def load_bytes(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def ocr_text(data: bytes) -> dict:
    try:
        img = load_bytes(data).convert("RGB")
    except Exception as e:
        return {"ok": False, "error": f"decode failed: {e}"}
    config = f"--tessdata-dir {TESSDATA_DIR}" if os.path.isdir(TESSDATA_DIR) else ""
    langs = "eng+ara"
    try:
        raw = pytesseract.image_to_string(img, lang=langs, config=config)
    except Exception:
        try:
            raw = pytesseract.image_to_string(img, lang="eng", config=config)
            langs = "eng"
        except Exception as e:
            return {"ok": False, "error": str(e)}
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in raw.splitlines() if ln.strip()]
    text = "\n".join(lines)[:3000]
    if len(text) < 8:
        return {"ok": True, "text": "", "chars": 0, "words": 0, "langs": langs}
    return {"ok": True, "text": text, "chars": len(text), "words": len(text.split()), "langs": langs}


def _safe_value(v):
    if isinstance(v, str):
        return v[:120]
    return str(v)[:120]


def exif_analysis(data: bytes) -> dict:
    try:
        tags = exifread.process_file(io.BytesIO(data), details=False)
    except Exception as e:
        return {"ok": False, "error": str(e), "tags": {}}

    out = {}
    for key in tags:
        out[str(key)] = _safe_value(tags[key])

    datetaken = out.get("EXIF DateTimeOriginal") or out.get("Image DateTime")
    gps = any(k.startswith("GPS") for k in out)
    make = out.get("Image Make") or out.get("Image Model")
    software = out.get("Image Software")
    comments = out.get("Image JPEGThumbnail") or out.get("EXIF UserComment")

    anomalies = []
    if not out:
        anomalies.append("No EXIF metadata — metadata is often stripped on screenshots, re-uploads, and AI generations.")
    elif not datetaken:
        anomalies.append("No capture date recorded.")
    if software and re.search(r"photo[^ ]* (editor|shop)|gimp|sketch|adobe|edited", software, re.I):
        anomalies.append(f"Editing software signature found in metadata: {software}")
    if comments and "draft" in str(comments).lower():
        anomalies.append("Editor 'draft' flag present in comment tags.")

    return {
        "ok": True,
        "tags": out,
        "count": len(out),
        "date_taken": str(datetaken) if datetaken else None,
        "has_gps": gps,
        "device": f"{make} {out.get('Image Model', '')}".strip() if make else None,
        "software": software,
        "anomalies": anomalies,
    }


def ela_analysis(data: bytes, scale: int = 10, quality: int = 85) -> dict:
    """Error Level Analysis: highlight regions re-saved at different quality."""
    try:
        img = load_bytes(data)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    img = img.convert("RGB")
    w, h = img.size
    img = img.resize((max(1, w // scale), max(1, h // scale)))

    tmp = io.BytesIO()
    img.save(tmp, format="JPEG", quality=quality)
    tmp.seek(0)

    try:
        recomp = Image.open(tmp).convert("RGB")
    except Exception as e:
        return {"ok": False, "error": f"recompression failed: {e}"}

    diff = ImageChops.difference(img, recomp)

    extrema = diff.getextrema()
    max_diff = max(e[1] for e in extrema)

    # Boost differences for visualization
    boosted = diff.point(lambda p: min(255, p * 12))

    ela_img_b64 = base64.b64encode(_jpeg_bytes(boosted)).decode()

    # Statistical profile
    red, green, blue = diff.split()
    hist_red = red.histogram()
    mean = sum(i * c for i, c in enumerate(hist_red)) / sum(hist_red) if sum(hist_red) else 0

    # Heuristics
    flags = []
    if max_diff < 2:
        flags.append("Very low error — image is likely a native single-compression file (weak signal for 'real').")
    elif max_diff > 60:
        flags.append("High error level — possible re-compression or synthetic origin. Verify via source search.")

    return {
        "ok": True,
        "max_ela": round(max_diff, 2),
        "mean_ela": round(mean, 2),
        "heatmap_b64": ea_heatmap_uri(ela_img_b64),
        "flags": flags,
        "analysis": "single" if max_diff < 2 else ("edited" if max_diff > 60 else "inconclusive"),
    }


def _jpeg_bytes(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def ea_heatmap_uri(b64: str) -> str:
    return f"data:image/jpeg;base64,{b64}"


def dhash(img: Image.Image, size: int = 8) -> int:
    img = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = list(img.getdata())
    h = 0
    for row in range(size):
        for col in range(size):
            left = px[row * (size + 1) + col]
            right = px[row * (size + 1) + col + 1]
            h = (h << 1) | (0 if left >= right else 1)
    return h


def dhash_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def image_stats(data: bytes) -> dict:
    img = load_bytes(data)
    return {
        "width": img.size[0],
        "height": img.size[1],
        "mode": img.mode,
        "format": img.format,
        "size_bytes": len(data),
        "dhash": hex(dhash(img)),
    }