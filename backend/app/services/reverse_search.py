import asyncio
import re
import urllib.parse

import httpx
from PIL import Image

from app.config import settings
from app.services.image_forensics import dhash, dhash_distance, load_bytes

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
_HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

_BAD_DOMAINS = {"lens.google.com", "www.google.com", "google.com", "www.gstatic.com", "encrypted-tbn0.gstatic.com",
                "lh3.googleusercontent.com", "googleusercontent.com", "bing.com", "www.bing.com", "bing.net",
                "catbox.moe", "files.catbox.moe", "0x0.st", "wikipedia.org", "upload.wikimedia.org"}


async def host_image(data: bytes, filename: str = "image.jpg") -> str:
    """Upload the image to a public host so search engines can fetch it."""
    async with httpx.AsyncClient(timeout=settings.TIMEOUT, headers=_HEADERS) as client:
        for host, url in (("catbox.moe", "https://catbox.moe/user/api.php"), ("0x0.st", "https://0x0.st")):
            try:
                if host == "catbox.moe":
                    files = {"fileToUpload": (filename, data, "image/jpeg")}
                    resp = await client.post(url, data={"reqtype": "fileupload"}, files=files)
                    text = resp.text.strip()
                    if resp.status_code == 200 and text.startswith("http"):
                        return text
                else:
                    resp = await client.post(url, files={"file": (filename, data, "image/jpeg")})
                    text = resp.text.strip()
                    if resp.status_code == 200 and text.startswith("http"):
                        return text
            except Exception:
                continue
    raise RuntimeError("Could not host the image on any public host (catbox/0x0.st).")


def _parse_bing_html(html: str) -> list[dict]:
    """Bing embeds result data as m="{...}" JSON blobs in the search page."""
    out = []
    seen = set()
    for m in re.finditer(r'm="{([^"]+)}"', html):
        try:
            s = m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("\\u003d", "=")
            murls = re.findall(r'"murl":"([^"]+)"', s)
            titles = re.findall(r'"t":"([^"]+)"', s)
            pages = re.findall(r'"purl":"([^"]+)"', s)
            thumbs = re.findall(r'"turl":"([^"]+)"', s)
            for i, murl in enumerate(murls[:8]):
                page = pages[i] if i < len(pages) else ""
                title = titles[i] if i < len(titles) else ""
                thumb = thumbs[i] if i < len(thumbs) else ""
                domain = urllib.parse.urlparse(page or murl).netloc
                if page and page not in seen:
                    seen.add(page)
                    out.append({"page_url": page, "image_url": murl, "thumb_url": thumb, "title": title, "domain": domain})
        except Exception:
            continue
    return out


async def _bing_page(client: httpx.AsyncClient, url: str) -> list[dict]:
    resp = await client.get(url)
    if resp.status_code != 200:
        return []
    return _parse_bing_html(resp.text)


async def bing_html_reverse(image_url: str) -> dict:
    """Query Bing: URL-paste reverse lookup first (content matching), and only fall back
    to plain imgurl: search when the first yields nothing."""
    q = urllib.parse.quote(image_url)
    urls = [
        f"https://www.bing.com/images/search?view=detailv2&iss=sbi&form=SBIVSP&sbisrc=UrlPaste&q=imgurl%3A{q}&url={q}",
    ]
    merged, seen = [], set()
    errors = []
    async with httpx.AsyncClient(timeout=settings.TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
        try:
            for item in await _bing_page(client, urls[0]):
                if item["page_url"] not in seen:
                    seen.add(item["page_url"])
                    merged.append(item)
        except Exception as e:
            errors.append(str(e)[:80])
        if len(merged) < 5:
            try:
                for item in await _bing_page(client, f"https://www.bing.com/images/search?q=imgurl%3A{q}"):
                    if item["page_url"] not in seen:
                        seen.add(item["page_url"])
                        merged.append(item)
            except Exception as e:
                errors.append(str(e)[:80])
    return {"matches": merged, "status": "ok" if merged else ("error" if errors else "empty")}


async def bing_api_reverse(image_url: str) -> dict:
    async with httpx.AsyncClient(timeout=settings.TIMEOUT) as client:
        resp = await client.post(
            "https://api.bing.microsoft.com/v7.0/images/visualsearch",
            headers={"Ocp-Apim-Subscription-Key": settings.BING_API_KEY, "Content-Type": "multipart/form-data"},
            params={"imgUrl": image_url},
            content=b"",
        )
        resp.raise_for_status()
        data = resp.json()
        out = []
        for tag in data.get("tags", []):
            for action in tag.get("actions", []):
                if action.get("actionType") in ("PageSearch", "MoreSizes"):
                    for v in action.get("data", {}).get("value", []):
                        page = v.get("hostPageUrl", "")
                        domain = urllib.parse.urlparse(page).netloc
                        if domain in _BAD_DOMAINS:
                            continue
                        out.append({
                            "page_url": page,
                            "image_url": v.get("contentUrl", ""),
                            "thumb_url": v.get("thumbnailUrl", ""),
                            "title": v.get("name", ""),
                            "domain": domain,
                        })
        return {"matches": out[:25], "status": "ok"}


def _scan_protobuf_urls(raw: bytes) -> list[str]:
    """The Lens v3 response is protobuf; result URLs are stored as UTF-8 strings.
    Scan the raw bytes for http(s) URLs and clean protobuf framing noise."""
    found = set()
    for m in re.finditer(rb"https?://[^\x00-\x20\x7f\x22\x27<>\\\[\]]+", raw):
        try:
            u = m.group(0).decode("utf-8", errors="ignore")
        except Exception:
            continue
        # strip trailing protobuf length bytes that snuck into the string
        u = re.sub(r"[\x00-\x1f]+.*$", "", u)
        if "lens.google" in u or "gstatic" in u or "ggpht" in u:
            if u.startswith("http"):
                found.add(u)
    return sorted(found)


def _clean_lens_url(u: str) -> str:
    """Lens urls come as www.google.com/imgres?imgurl=...&imgrefurl=..."""
    if "/imgres?" in u or "imgurl=" in u:
        q = urllib.parse.urlparse(u).query
        params = urllib.parse.parse_qs(q)
        return params.get("imgrefurl", [u])[0]
    if "/search?" in u and "tbm=isch" in u:
        return u
    return u


async def lens_v3_reverse(image_url: str) -> dict:
    """Google Lens v3 upload endpoint (the one the Google app uses) - no API key.
    File-mode upload: fetch the hosted image, POST it as multipart; Google answers
    with a 303 redirect to the vision-search URL (JS-only page). We return the URL as
    a deep link for the user's browser, and mark matches as machine-unavailable rather
    than silently reporting 0."""
    try:
        async with httpx.AsyncClient(timeout=settings.TIMEOUT, headers=_HEADERS, follow_redirects=False) as client:
            await client.get("https://lens.google.com/")
            img = await client.get(image_url)
            if img.status_code != 200 or not img.content:
                return {"matches": [], "status": "error", "error": "could not fetch hosted image"}
            resp = await client.post(
                "https://lens.google.com/v3/upload?ep=ccm&s=&st=&hl=en&vpw=1600&vph=1000",
                files={"encoded_image": ("image.jpg", img.content, "image/jpeg")},
            )
            if resp.status_code in (200, 201):
                urls = _scan_protobuf_urls(resp.content)
                out, seen = [], set()
                for u in urls:
                    page = _clean_lens_url(u)
                    try:
                        domain = urllib.parse.urlparse(page).netloc
                    except Exception:
                        domain = ""
                    if not page or domain in _BAD_DOMAINS or page in seen:
                        continue
                    seen.add(page)
                    out.append({"page_url": page, "image_url": u, "thumb_url": "", "title": "", "domain": domain})
                    if len(out) >= 20:
                        break
                return {"matches": out, "status": "ok" if out else "empty"}
            if resp.status_code == 303:
                location = resp.headers.get("location", "")
                return {"matches": [], "status": "link", "link": location}
            return {"matches": [], "status": "error", "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"matches": [], "status": "error", "error": str(e)[:120]}


def _is_noise(m: dict, hosted: str) -> bool:
    """Drop matches that are really about the temp-host URL (AV scanners, host trackers)."""
    hay = " ".join(str(m.get(k, "")) for k in ("page_url", "image_url", "domain")).lower()
    return any(s in hay for s in ("catbox", "bytesbin", "gridinsoft", "sensorstech", "0x0.st"))


async def score_similarity(uploaded: bytes, matches: list[dict], limit: int = 8) -> list[dict]:
    """Fetch each match thumbnail and compute perceptual-hash distance to the upload."""
    try:
        ref = dhash(load_bytes(uploaded))
    except Exception:
        return matches

    async def one(m: dict):
        url = m.get("thumb_url") or m.get("image_url")
        if not url:
            return {**m, "similarity": None}
        try:
            async with httpx.AsyncClient(timeout=12, headers=_HEADERS, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code != 200 or not resp.content:
                    return {**m, "similarity": None}
                try:
                    dist = dhash_distance(ref, dhash(load_bytes(resp.content)))
                    return {**m, "similarity": max(0, round(100 - (dist / 64) * 100, 1))}
                except Exception:
                    return {**m, "similarity": None}
        except Exception:
            return {**m, "similarity": None}

    scored = await asyncio.gather(*(one(m) for m in matches[:limit]))
    scored.sort(key=lambda m: (m.get("similarity") or -1), reverse=True)
    return scored


async def reverse_search(data: bytes, filename: str = "image.jpg") -> dict:
    """Full pipeline: host image -> Bing + Google Lens in parallel -> similarity ranking.
    Every engine reports its own status so a blocked/failed engine is visible, not silent."""
    public_url = await host_image(data, filename)

    bing, lens = await asyncio.gather(
        (bing_api_reverse(public_url) if settings.BING_API_KEY else bing_html_reverse(public_url)),
        lens_v3_reverse(public_url),
    )

    # merge, dedupe by page URL, drop temp-host noise
    merged, seen = [], set()
    for engine, block in (("bing", bing), ("google", lens)):
        for m in block.get("matches", []):
            key = m.get("page_url") or m.get("image_url")
            if key and key not in seen and not _is_noise(m, public_url):
                seen.add(key)
                m["engine"] = engine
                merged.append(m)

    scored = await score_similarity(data, merged)

    domains = {}
    for m in merged:
        d = m.get("domain")
        if d:
            domains[d] = domains.get(d, 0) + 1

    google_link = lens.get("link") or f"https://lens.google.com/uploadbyurl?url={urllib.parse.quote(public_url)}"
    engines = {}
    for engine, block in (("bing", bing), ("google", lens)):
        engines[engine] = {
            "status": block.get("status", "error"),
            "matches": len(block.get("matches", [])),
            "error": block.get("error", ""),
            "link": google_link if engine == "google" else "",
        }

    return {
        "hosted_url": public_url,
        "lens_url": google_link,
        "yandex_url": f"https://yandex.com/images/search?rpt=imageview&url={urllib.parse.quote(public_url)}",
        "engines": engines,
        "matches": scored,
        "match_count": len(merged),
        "domains": domains,
    }