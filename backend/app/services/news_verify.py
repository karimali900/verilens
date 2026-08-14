import asyncio
import datetime as dt
import html
import json
import os
import re
import time
import urllib.parse
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from app.config import settings

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
_HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

FACTCHECK_DOMAINS = {"snopes.com", "politifact.com", "factcheck.org", "truthorfiction.com", "hoax-slayer.net",
                     "leadstories.com", "afpfactcheck.com", "reuters.com"}

FACTUALLY_TOPICS = ["politics", "business", "society", "technology", "health", "science", "entertainment"]
FACTUALLY_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "data", "factually_cache.json")
FACTUALLY_TTL_S = 24 * 3600
_FACTUALLY_SECRET = "AVw9GMZ2dF4yES0Yj36aq34tgkdV960AjfiPu5buiHXXtpvx2MHwnEQaUFZ9izJ9"

FAKE_SIGNALS = re.compile(r"\b(hoax|false|debunked|misleading|fabricated|satire|fake news)\b", re.I)


def _gdelt_ts(s: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _clean_domain(url: str) -> str:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    host = re.sub(r"^www\.|^m\.", "", host)
    host = host.replace("news.google.com", "google.com")
    return host


async def _gdelt(query: str, extra: str = "", limit: int = 50) -> list[dict]:
    q = f'"{query}" {extra}'.strip()
    params = {
        "query": q, "mode": "artlist", "format": "json", "maxrecords": limit,
        "timespan": "45d", "sort": "datedesc",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.TIMEOUT, headers=_HEADERS) as client:
            resp = await client.get("https://api.gdeltproject.org/api/v2/doc/doc", params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()
        out = []
        for a in data.get("articles", [])[:limit]:
            ts = _gdelt_ts(a.get("seendate", ""))
            out.append({
                "source": "GDELT",
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "domain": _clean_domain(a.get("url", "")),
                "publisher": a.get("domain", ""),
                "date": ts.isoformat() if ts else None,
                "date_raw": a.get("seendate", ""),
            })
        return out
    except Exception:
        return []


async def _google_news(query: str, limit: int = 30, ar: bool = False) -> list[dict]:
    if ar:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=ar&gl=EG&ceid=EG:ar"
    else:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        async with httpx.AsyncClient(timeout=settings.TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
            feed = feedparser.parse(resp.content)
        out = []
        for e in feed.entries[:limit]:
            published = None
            try:
                published = parsedate_to_datetime(e.get("published", "")).astimezone(dt.timezone.utc).isoformat()
            except Exception:
                pass
            out.append({
                "source": "Google News",
                "title": e.get("title", ""),
                "url": e.get("link", ""),
                "domain": _clean_domain(e.get("link", "")),
                "publisher": e.get("source", {}).get("title", ""),
                "date": published,
                "date_raw": e.get("published", ""),
            })
        return out
    except Exception:
        return []


async def _reddit(query: str, limit: int = 20) -> list[dict]:
    url = f"https://www.reddit.com/search.json?q={urllib.parse.quote(query)}&sort=new&t=month&limit={limit}"
    try:
        async with httpx.AsyncClient(timeout=settings.TIMEOUT, headers={**_HEADERS, "User-Agent": "VeriLens/1.0 by research script"}, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            data = resp.json()
        out = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            created = dt.datetime.fromtimestamp(d.get("created_utc", 0), tz=dt.timezone.utc).isoformat() if d.get("created_utc") else None
            out.append({
                "source": "Reddit",
                "title": d.get("title", ""),
                "url": f"https://www.reddit.com{d.get('permalink', '')}",
                "domain": "reddit.com",
                "publisher": f"r/{d.get('subreddit', '')}",
                "date": created,
                "date_raw": str(d.get("created_utc", "")),
                "score": d.get("score", 0),
                "comments": d.get("num_comments", 0),
            })
        return out
    except Exception:
        return []


async def _factcheck_scan(query: str, ar: bool = False) -> list[dict]:
    if ar:
        extra = "تحقق OR شائعة OR كاذب OR مضلل OR مختلق"
        gn_query = f"{query} تحقق OR شائعة OR كاذب OR مضلل"
    else:
        extra = "fact check OR hoax OR debunked OR false OR misleading"
        gn_query = f"{query} fact check OR hoax OR debunked"
    tasks = [
        _gdelt(query, extra=extra, limit=20),
        _google_news(gn_query, limit=15, ar=ar),
        _factually_scan(query),
    ]
    results = []
    for group in await asyncio.gather(*tasks):
        results.extend(group)
    seen, out = set(), []
    for a in results:
        if a["url"] and a["url"] not in seen:
            seen.add(a["url"])
            a["is_factcheck_domain"] = any(d in a["domain"] for d in FACTCHECK_DOMAINS)
            out.append(a)
    return out[:25]


async def _factually_scan(query: str, limit: int = 8) -> list[dict]:
    """Search factually.co (claim → verdict database) using two complementary channels:
    1. DuckDuckGo site search for the long tail of checks.
    2. A locally cached index of the most recent checks per topic (fetched with a
       browser-like client, since factually.co blocks plain HTTP clients), matched by
       shared keywords — the Mr-Bean-style viral claims usually appear in the recent set.
    """
    results = []
    seen: set[str] = set()

    for item in await _factually_ddg(query):
        if item["url"] not in seen:
            seen.add(item["url"])
            results.append(item)
        if len(results) >= limit:
            return results

    try:
        cache = await asyncio.to_thread(_factually_cache)
    except Exception:
        cache = []

    q_tokens = _tokenize(query)
    scored = []
    for c in cache:
        score = len(set(q_tokens) & set(_tokenize(c["title"])))
        if score >= 2:
            scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    for _, c in scored:
        if c["url"] in seen:
            continue
        seen.add(c["url"])
        results.append({
            "source": "Factually",
            "title": c["title"][:160],
            "url": c["url"],
            "domain": "factually.co",
            "publisher": "Factually",
            "date": c.get("date"),
            "date_raw": "",
            "score": 0,
            "comments": 0,
            "snippet": f"Recent check on factually.co{', ' + c.get('date') if c.get('date') else ''}",
            "is_factcheck_domain": False,
        })
        if len(results) >= limit:
            break
    return results


def _tokenize(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", s.lower()) if w not in _STOPWORDS}


_STOPWORDS = {"the", "and", "for", "with", "was", "did", "are", "you", "that", "this", "from",
              "have", "has", "not", "but", "who", "what", "when", "how", "why", "his", "her",
              "she", "him", "their", "they", "been", "being", "its", "it's", "about", "over"}


async def _factually_ddg(query: str, limit: int = 5) -> list[dict]:
    q = urllib.parse.quote(f'site:factually.co "{query}"')
    url = f"https://html.duckduckgo.com/html/?q={q}"
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=settings.TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return []
                page = resp.text
            if "anomaly" in page.lower() or "result__a" not in page:
                await asyncio.sleep(2.5)
                continue
            out, seen = [], set()
            for block in re.findall(r'<div class="result[^"]*".*?</div>\s*</div>', page, re.S):
                m = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
                if not m:
                    continue
                link = html.unescape(m.group(1))
                title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
                p = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.S)
                snippet = html.unescape(re.sub(r"<[^>]+>", "", p.group(1))).strip() if p else ""
                if link in seen or "factually.co" not in link:
                    continue
                seen.add(link)
                out.append({
                    "source": "Factually",
                    "title": title[:160],
                    "url": link.split("&")[0],
                    "domain": "factually.co",
                    "publisher": "Factually",
                    "date": None,
                    "date_raw": "",
                    "score": 0,
                    "comments": 0,
                    "snippet": snippet[:220],
                    "is_factcheck_domain": False,
                })
                if len(out) >= limit:
                    break
            return out
        except Exception:
            return []
    return []


_FACTUALLY_ITEM_RE = re.compile(
    r'\{\\"id\\":\d+,\\"prompt\\":\\"((?:[^"\\\\]|\\\\.)*)\\",\\"response_preview\\":\\"'
    r'(?:[^"\\\\]|\\\\.)*\\",\\"slug\\":\\"([^"\\\\]+)\\",\\"topic\\":\\"([^"\\\\]+)\\",'
    r'\\"created_at\\":\\"([^"\\\\]+)\\"'
)


def _unescape_rsc(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


def _factually_cache(refresh: bool = False) -> list[dict]:
    """Recent checks per topic (latest ~20 each) + trending, cached locally and
    refreshed at most once a day. Titles/prompts are the claim texts users type,
    so keyword overlap matching works well."""
    try:
        if not refresh and os.path.exists(FACTUALLY_CACHE):
            mtime = os.path.getmtime(FACTUALLY_CACHE)
            if time.time() - mtime < FACTUALLY_TTL_S:
                with open(FACTUALLY_CACHE) as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    return data
    except Exception:
        pass

    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(browser={"browser": "firefox", "platform": "linux", "desktop": True})
    except Exception:
        return []

    items, seen = [], set()

    def add(url: str, title: str, date: str):
        if not url or url in seen:
            return
        seen.add(url)
        items.append({"url": url, "title": title[:160], "date": date or None})

    for topic in FACTUALLY_TOPICS:
        try:
            r = scraper.get(f"https://factually.co/topics/{topic}", timeout=25)
            if r.status_code != 200:
                continue
            for prompt, slug, topic_name, created in _FACTUALLY_ITEM_RE.findall(r.text):
                add(f"https://factually.co/fact-checks/{_unescape_rsc(slug)}",
                    _unescape_rsc(prompt), _unescape_rsc(created)[:10])
        except Exception:
            continue

    try:
        r = scraper.get("https://factually.co/api/trending", timeout=25,
                        headers={"X-App-Secret": _FACTUALLY_SECRET, "X-Client-Type": "factually-web"})
        if r.status_code == 200:
            for it in r.json().get("top_checks", []):
                add(it.get("url") or "", it.get("display_title") or it.get("prompt") or "",
                    (it.get("created_at") or "")[:10])
    except Exception:
        pass

    try:
        os.makedirs(os.path.dirname(FACTUALLY_CACHE), exist_ok=True)
        with open(FACTUALLY_CACHE, "w") as f:
            json.dump(items, f)
    except Exception:
        pass
    return items


async def _youtube_search(query: str, limit: int = 6) -> list[dict]:
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
    try:
        async with httpx.AsyncClient(timeout=settings.TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            page = resp.text
        m = re.search(r"var ytInitialData = (\{.*?\});</script>", page, re.S)
        if not m:
            return []
        data = json.loads(m.group(1))
    except Exception:
        return []
    out = []
    try:
        sections = data["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"] \
                       ["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"]
    except Exception:
        return []
    for it in sections:
        vr = it.get("videoRenderer")
        if not vr:
            continue
        title = ""
        for run in (vr.get("title", {}).get("runs") or []):
            title += run.get("text", "")
        channel = ""
        for run in (vr.get("ownerText", {}).get("runs") or []):
            channel += run.get("text", "")
        video_id = vr.get("videoId")
        if not video_id or not title.strip():
            continue
        out.append({
            "source": "YouTube",
            "title": title.strip()[:200],
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "domain": "youtube.com",
            "publisher": channel.strip() or "YouTube",
            "date": None,
            "date_raw": "",
            "score": 0,
            "comments": 0,
        })
        if len(out) >= limit:
            break
    return out


def _relevant(a: dict, query: str) -> bool:
    """Relevance gate: a result must share at least one content word with the
    query (Arabic or English) or it's noise pulled in by the fact-check extras."""
    q = query.lower()
    ar_tokens = set(re.findall(r"[\u0600-\u06FF]{2,}", q))
    en_tokens = {w for w in re.findall(r"[a-z0-9]{4,}", q) if w not in _STOPWORDS}
    if not ar_tokens and not en_tokens:
        return True
    title = ((a.get("title") or "") + " " + (a.get("snippet") or "")).lower()
    if ar_tokens:
        return any(ar_t in title for ar_t in ar_tokens)
    return any(t in title for t in en_tokens)


def _domain_key(a: dict) -> str:
    """Independence key: real publishing entity. Google News items carry the true publisher
    in `publisher` (their RSS link is a news.google.com redirect)."""
    pub = (a.get("publisher") or "").strip()
    if a.get("source") == "Google News" and pub:
        return f"gn-{pub.lower()}"
    dom = a.get("domain") or ""
    if dom in {"google.com", "reddit.com", "facebook.com", "twitter.com", "x.com"}:
        return dom
    return dom


def _resolve_first(articles: list[dict]) -> dict | None:
    dated = [a for a in articles if a.get("date")]
    if not dated:
        return None
    return min(dated, key=lambda a: a["date"])


def _verdict(articles: list[dict], factchecks: list[dict], first: dict | None, ar: bool = False) -> dict:
    independent = {_domain_key(a) for a in articles if _domain_key(a)}
    independent.discard("google.com")
    independent.discard("reddit.com")
    independent.discard("youtube.com")

    factcheck_flagged = [fc for fc in factchecks if FAKE_SIGNALS.search(fc["title"]) or fc.get("is_factcheck_domain")]

    reasons = []
    video_traces = [a for a in articles if a.get("source") == "YouTube"]
    video_hits = len(video_traces)
    if video_hits:
        sample = f"{video_traces[0].get('publisher') or 'YouTube'}: “{video_traces[0]['title'][:70]}”"
        reasons.append(f"Exact text appears as {video_hits} YouTube video title(s) — e.g. {sample}. Screenshots often come from such videos.")
    if len(independent) >= 4:
        reasons.append(f"Reported by {len(independent)} independent publications.")
    elif len(independent) >= 2:
        reasons.append(f"Reported by {len(independent)} publications — moderate coverage.")
    else:
        reasons.append("Very little independent news coverage found.")

    if first:
        reasons.append(f"Earliest trace found on {first.get('publisher') or first.get('domain')} ({first['date'][:10]}).")

    if factcheck_flagged:
        flagged_texts = [fc["title"][:60] for fc in factcheck_flagged[:3]]
        reasons.append("Fact-checking outlets question this claim: " + " | ".join(flagged_texts))
    elif factchecks:
        reasons.append(f"{len(factchecks)} fact-check-related article(s) found — review them below.")

    social_score = sum(a.get("score", 0) for a in articles if a.get("source") == "Reddit")

    score = 20
    score += min(50, len(independent) * 10)
    if first:
        score += 10
    if video_hits:
        score += 5
    if social_score >= 50:
        score += 5
    if factcheck_flagged:
        score -= 25
    if any(_domain_key(a) == "onion.com" for a in articles):
        score -= 15
        reasons.append("Satire domain detected (theonion.com).")
    score = max(0, min(100, score))

    if factcheck_flagged and score < 55:
        verdict, label = "likely_fake", "likely fake"
    elif score >= 60:
        verdict, label = "likely_real", "likely real"
    elif score >= 40:
        verdict, label = "unverified", "unverified"
    else:
        verdict, label = ("unverified", "unverified") if ar else ("likely_fake", "likely fake")

    return {
        "verdict": verdict,
        "label": label,
        "score": score,
        "independent_domains": sorted(independent),
        "reasons": reasons,
        "social_engagement": social_score,
        "video_hits": video_hits,
    }


async def verify_news(query: str) -> dict:
    query = query.strip().strip('"')
    ar = bool(re.search(r"[\u0600-\u06FF]{2,}", query))
    articles, factchecks = [], []
    gdelt, gnews, reddit, yt, fc = await asyncio.gather(
        _gdelt(query),
        _google_news(query, ar=ar),
        _reddit(query),
        _youtube_search(query),
        _factcheck_scan(query, ar=ar),
    )
    articles = gdelt + gnews + reddit + yt
    factchecks = [fc_ for fc_ in fc if _relevant(fc_, query)]

    seen = set()
    deduped = []
    for a in articles:
        key = (_domain_key(a), a["title"][:80].lower())
        if key not in seen:
            seen.add(key)
            deduped.append(a)

    first = _resolve_first(deduped)
    verdict = _verdict(deduped, factchecks, first, ar=ar)

    return {
        "query": query,
        "verdict": verdict,
        "first_publisher": first,
        "articles": sorted(deduped, key=lambda a: a.get("date") or "", reverse=True)[:60],
        "article_count": len(deduped),
        "fact_checks": factchecks,
        "fact_check_count": len(factchecks),
    }