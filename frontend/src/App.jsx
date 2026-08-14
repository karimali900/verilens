import React, { useMemo, useRef, useState } from "react";
import { verifyImage, verifyNews, verifyVideo, verifyVideoUrl } from "./api";
import { LangProvider, useLang } from "./i18n.jsx";

const VERDICT_COLORS = { likely_real: "#34d399", unverified: "#fbbf24", likely_fake: "#fb7185" };

function ScoreBar({ score }) {
  const color = score >= 60 ? "#34d399" : score >= 40 ? "#fbbf24" : "#fb7185";
  return (
    <div className="score-bar">
      <div className="score-fill" style={{ width: `${score}%`, background: color }} />
    </div>
  );
}

function VerdictCard({ verdict }) {
  const { t } = useLang();
  const color = VERDICT_COLORS[verdict.verdict] || "#7f8c8d";
  const label = verdict.verdict ? t(`verdict_${verdict.verdict}`, null, verdict.label) : verdict.label;
  return (
    <div className="verdict-card" style={{ borderColor: color }}>
      <div className="verdict-label" style={{ color }}>
        {label}
      </div>
      <ScoreBar score={verdict.score} />
      <div className="score-text">{t("confidence", { n: verdict.score })}</div>
      <ul className="reasons">{verdict.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
    </div>
  );
}

/* ------------------------------ IMAGE ------------------------------ */

function ImageVerifier() {
  const { t } = useLang();
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [err, setErr] = useState(null);
  const [result, setResult] = useState(null);
  const [showEla, setShowEla] = useState(false);
  const [showExif, setShowExif] = useState(false);
  const inputRef = useRef(null);

  const onFile = (f) => {
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
    setResult(null);
    setErr(null);
  };

  const run = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    setShowEla(false);
    setShowExif(false);
    try {
      const { data } = await verifyImage(file, setProgress);
      setResult(data);
    } catch (e) {
      setErr(e.response?.data?.detail || e.message || t("verify_failed"));
    } finally {
      setBusy(false);
    }
  };

  const exif = result?.exif;
  const ela = result?.ela;
  const reverse = result?.reverse;

  return (
    <div>
      <div
        className="dropzone"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); onFile(e.dataTransfer.files[0]); }}
      >
        <input ref={inputRef} type="file" accept="image/*" hidden onChange={(e) => onFile(e.target.files[0])} />
        {preview ? (
          <div className="dz-preview">
            <img src={preview} alt="upload preview" />
            <span>{t("click_change", { name: file.name })}</span>
          </div>
        ) : (
          <p><span className="dz-icon">🖼</span> {t("drop_image")}</p>
        )}
      </div>

      <button className="run" onClick={run} disabled={!file || busy}>
        {busy ? t("analyzing", { n: progress }) : t("verify_image")}
      </button>
      {err && <p className="err">{err}</p>}

      {result && (
        <div className="results">
          <div className="result-strip">
            <VerdictCard verdict={result.verdict} />

            <div className="panel">
              <h4>{t("img_forensics")}</h4>
              <div className="stats-grid">
                <div><label>{t("dims")}</label><strong>{result.stats.width}×{result.stats.height}</strong></div>
                <div><label>{t("format")}</label><strong>{result.stats.format}</strong></div>
                <div><label>{t("exif_tags")}</label><strong>{exif?.count ?? 0}</strong></div>
                <div><label>{t("ela_max")}</label><strong>{ela?.max_ela ?? "—"}</strong></div>
              </div>
              <label className="toggle-row">
                <input type="checkbox" checked={showEla} onChange={(e) => setShowEla(e.target.checked)} disabled={!ela?.heatmap_b64} />
                {t("show_ela")}
              </label>
              <label className="toggle-row">
                <input type="checkbox" checked={showExif} onChange={(e) => setShowExif(e.target.checked)} disabled={!exif?.ok} />
                {t("show_exif")}
              </label>
              {ela?.flags?.map((f, i) => <p key={i} className="flag">⚠ {f}</p>)}
            </div>
          </div>

          {result.ocr?.ok && result.ocr.chars > 0 && (
            <div className="panel">
              <h4>{t("ocr_title")} <span className="subnote">{t("ocr_langs", { n: result.ocr.chars })}</span></h4>
              <pre className="ocr-text">{result.ocr.text}</pre>
            </div>
          )}
          {result.ocr?.ok && result.ocr.chars === 0 && (
            <p className="subnote">{t("ocr_none")}</p>
          )}

          {result.text_check && (
            <div className="panel">
              <h4>📄 {t("text_check_title")}</h4>
              <p className="subnote">{t("text_check_sub")}</p>
              <div style={{ maxWidth: 360 }}>
                <VerdictCard verdict={result.text_check.verdict} />
              </div>
              {result.text_check.fact_checks?.length > 0 && (
                <h5 style={{ marginTop: "1rem" }}>{t("factcheck_watch", { n: result.text_check.fact_check_count })}</h5>
              )}
              {result.text_check.fact_checks?.slice(0, 4).map((fc, i) => (
                <div key={i} className="fc-row">
                  <a href={fc.url} target="_blank" rel="noreferrer">{fc.title}</a>
                  <span className={`fc-src${fc.source === "Factually" ? " fc-src-factually" : ""}`}>
                    {fc.source === "Factually" ? "Factually ✓" : fc.domain}
                  </span>
                </div>
              ))}
              {result.text_check.articles?.length > 0 && (
                <h5 style={{ marginTop: "1rem" }}>{t("text_check_sources")}</h5>
              )}
              {result.text_check.articles?.slice(0, 5).map((a, i) => (
                <div key={i} className="fc-row">
                  <a href={a.url} target="_blank" rel="noreferrer">{a.title}</a>
                  <span className="fc-src">
                    {a.source === "Google News" ? (a.publisher || a.domain) : a.domain}
                    {a.date ? ` · ${new Date(a.date).toISOString().slice(0, 10)}` : ""}
                  </span>
                </div>
              ))}
            </div>
          )}

          {showEla && ela?.heatmap_b64 && (
            <div className="panel">
              <h4>{t("ela_title")}</h4>
              <img src={ela.heatmap_b64} alt="ELA heatmap" className="ela-img" />
            </div>
          )}

          {showExif && exif?.ok && (
            <div className="panel">
              <h4>{t("exif_title")}</h4>
              <div className="exif-grid">
                {Object.entries(exif.tags).map(([k, v]) => (
                  <div key={k}><code>{k}</code><span>{v}</span></div>
                ))}
              </div>
            </div>
          )}

          <div className="panel">
            <h4>{t("similar_images", { n: reverse?.match_count ?? 0 })}</h4>
            {reverse?.engines && (
              <div className="engine-row">
                {Object.entries(reverse.engines).map(([name, e]) => (
                  <span key={name} className={`engine engine-${e.status}`}>
                    {name === "bing" ? "Bing" : "Google Lens"} · {e.status === "link" ? t("eng_ready") : e.status === "ok" ? t("eng_ok") : e.status === "failed" ? t("eng_failed") : e.status}
                    {e.status === "ok" ? ` (${e.matches})` : ""}
                    {e.error ? ` — ${e.error}` : ""}
                  </span>
                ))}
              </div>
            )}
            {reverse?.hosted_url && (
              <p className="subnote">{t("hosted_at_pre")}<a href={reverse.hosted_url} target="_blank" rel="noreferrer">{reverse.hosted_url}</a></p>
            )}
            <div className="link-row">
              {reverse?.lens_url && (
                <a className="link-btn" href={reverse.lens_url} target="_blank" rel="noreferrer">{t("open_lens")}</a>
              )}
              {reverse?.yandex_url && (
                <a className="link-btn" href={reverse.yandex_url} target="_blank" rel="noreferrer">{t("open_yandex")}</a>
              )}
            </div>
            <div className="match-grid">
              {reverse?.matches?.map((m, i) => (
                <a key={i} className="match" href={m.page_url || m.image_url} target="_blank" rel="noreferrer">
                  {m.thumb_url || m.image_url ? <img src={m.thumb_url || m.image_url} alt="" /> : <div className="thumb-off" />}
                  <div className="match-meta">
                    <span className="match-domain">{m.domain}</span>
                    {m.similarity != null && (
                    <span className="sim" style={{ color: m.similarity >= 70 ? "#34d399" : m.similarity >= 40 ? "#fbbf24" : "#6b7394" }}>
                      {t("pct_similar", { n: m.similarity })}
                    </span>
                  )}
                </div>
              </a>
            ))}
          </div>
          {!reverse?.matches?.length && <p className="empty">{t("no_similar_img")}</p>}
          {reverse?.domains && Object.keys(reverse.domains).length > 0 && (
            <p className="subnote">{t("found_on", { list: Object.entries(reverse.domains).map(([d, n]) => `${d} (${n})`).join(", ") })}</p>
          )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------- NEWS ------------------------------- */

function NewsVerifier() {
  const { t } = useLang();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [result, setResult] = useState(null);

  const run = async () => {
    if (!query.trim()) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const { data } = await verifyNews(query);
      setResult(data);
    } catch (e) {
      setErr(e.response?.data?.detail || e.message || t("verify_failed"));
    } finally {
      setBusy(false);
    }
  };

  const fp = result?.first_publisher;
  const v = result?.verdict;

  return (
    <div>
      <div className="news-input">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("news_placeholder")}
          rows={3}
        />
        <button className="run" onClick={run} disabled={!query.trim() || busy}>
          {busy ? t("scanning") : t("verify_news")}
        </button>
      </div>
      {err && <p className="err">{err}</p>}

      {result && (
        <div className="results">
          <div className="result-strip">
            <VerdictCard verdict={v} />

            <div className="panel">
              <h4>{t("first_publisher")}</h4>
              {fp ? (
                <div className="first-pub">
                  <div className="fp-domain">{fp.publisher || fp.domain}</div>
                  <div className="fp-date">{fp.date ? new Date(fp.date).toUTCString() : t("unknown")}</div>
                  <a href={fp.url} target="_blank" rel="noreferrer">{t("read_first_trace")}</a>
                </div>
              ) : (
                <p className="empty">{t("no_traces")}</p>
              )}
              <h4 style={{ marginTop: "1rem" }}>{t("coverage")}</h4>
              <p className="subnote">{t("coverage_sub", { a: result.article_count, d: v.independent_domains?.length ?? 0 })}</p>
            </div>
          </div>

          {result.fact_checks?.length > 0 && (
            <div className="panel factcheck">
              <h4>{t("factcheck_watch", { n: result.fact_check_count })}</h4>
              {result.fact_checks.map((fc, i) => (
                <div key={i} className="fc-row">
                  <a href={fc.url} target="_blank" rel="noreferrer">{fc.title}</a>
                  <span className={`fc-src${fc.source === "Factually" ? " fc-src-factually" : ""}`}>
                    {fc.source === "Factually" ? "Factually ✓" : fc.domain}
                  </span>
                </div>
              ))}
            </div>
          )}

          <div className="panel">
            <h4>{t("timeline")}</h4>
            <div className="timeline">
              {result.articles.map((a, i) => (
                <div key={i} className="tl-row">
                  <span className="tl-date">{a.date ? new Date(a.date).toLocaleString() : t("unknown")}</span>
                  <span className={`tl-src src-${a.source.replace(/\s+/g, "").toLowerCase()}`}>{a.source}</span>
                  <a href={a.url} target="_blank" rel="noreferrer" className="tl-title">{a.title}</a>
                  <span className="tl-pub">{a.publisher || a.domain}</span>
                </div>
              ))}
              {!result.articles.length && <p className="empty">{t("no_articles")}</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------- VIDEO ------------------------------- */

function VideoVerifier() {
  const { t } = useLang();
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [err, setErr] = useState(null);
  const [result, setResult] = useState(null);
  const [frameIdx, setFrameIdx] = useState(0);
  const inputRef = useRef(null);

  const onFile = (f) => {
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
    setResult(null);
    setErr(null);
    setFrameIdx(0);
  };

  const run = async () => {
    if (!file && !url.trim()) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    setFrameIdx(0);
    try {
      const { data } = url.trim()
        ? await verifyVideoUrl(url.trim())
        : await verifyVideo(file, setProgress);
      setResult(data);
    } catch (e) {
      setErr(e.response?.data?.detail || e.message || t("verify_failed"));
    } finally {
      setBusy(false);
    }
  };

  const frames = result?.frames || [];
  const frame = frames[frameIdx] || null;
  const reverse = frame?.reverse || {};
  const bestIdx = useMemo(() => {
    if (!frames.length) return 0;
    let bi = 0;
    frames.forEach((f, i) => {
      if ((f.reverse?.match_count || 0) > (frames[bi].reverse?.match_count || 0)) bi = i;
    });
    return bi;
  }, [frames]);

  return (
    <div>
      <div className="video-source">
        <input
          className="url-input"
          type="text"
          placeholder={t("video_url_ph")}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
        />
        <div
          className="dropzone dz-video"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); onFile(e.dataTransfer.files[0]); }}
        >
          <input ref={inputRef} type="file" accept="video/*" hidden onChange={(e) => onFile(e.target.files[0])} />
          {preview ? (
            <div className="dz-preview">
              <video src={preview} controls muted />
              <span>{t("click_change", { name: file.name })}</span>
            </div>
          ) : (
            <p><span className="dz-icon">🎬</span> {t("drop_video")}</p>
          )}
        </div>
      </div>

      <button className="run" onClick={run} disabled={(!file && !url.trim()) || busy}>
        {busy ? (progress > 0 ? t("uploading", { n: progress }) : t("downloading")) : t("verify_video")}
      </button>
      {err && <p className="err">{err}</p>}

      {result && (
        <div className="results">
          <div className="result-strip">
            <VerdictCard verdict={result.verdict} />

            <div className="panel">
              <h4>{t("video_meta")}</h4>
              <div className="stats-grid">
                <div><label>{t("duration")}</label><strong>{result.meta?.duration ? `${result.meta.duration}s` : "—"}</strong></div>
                <div><label>{t("resolution")}</label><strong>{result.meta?.width ? `${result.meta.width}×${result.meta.height}` : "—"}</strong></div>
                <div><label>{t("codec")}</label><strong>{result.meta?.codec || "—"}</strong></div>
                <div><label>{t("frames_checked")}</label><strong>{frames.length}</strong></div>
              </div>
              {result.meta?.video_title && (
                <div className="video-about">
                  <strong>{result.meta.video_title}</strong>
                  {result.meta.uploader && <span>{t("by_uploader", { name: result.meta.uploader })}</span>}
                  {result.meta.view_count != null && <span className="views">{t("views", { n: result.meta.view_count.toLocaleString() })}</span>}
                </div>
              )}
              <p className="subnote">{t("frames_sampled")}</p>
            </div>
          </div>

          <div className="panel">
            <h4>{t("key_frames")}</h4>
            <div className="frame-grid">
              {frames.map((f, i) => (
                <button
                  key={f.index}
                  className={`frame-card ${i === frameIdx ? "active" : ""} fc-${f.verdict.verdict}`}
                  onClick={() => setFrameIdx(i)}
                >
                  <img src={`/api/v1/frame/${f.file}`} alt={`frame ${f.index}`} />
                  <span className="frame-verdict">{t(`verdict_${f.verdict.verdict}`, null, f.verdict.label)} · {f.verdict.score}</span>
                  <span className="frame-matches">{t("web_matches", { n: f.reverse?.match_count ?? 0 })}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="panel">
            <h4>
              {t("frame_matches_title", { i: frame?.index })}
              {bestIdx !== frameIdx && frames[bestIdx] && (
                <span className="best-hint"> {t("best_frame", { i: frames[bestIdx].index, n: frames[bestIdx].reverse?.match_count ?? 0 })}</span>
              )}
            </h4>
            {reverse?.engines && (
              <div className="engine-row">
                {Object.entries(reverse.engines).map(([name, e]) => (
                  <span key={name} className={`engine engine-${e.status}`}>
                    {name === "bing" ? "Bing" : "Google Lens"} · {e.status === "link" ? t("eng_ready") : e.status === "ok" ? t("eng_ok") : e.status === "failed" ? t("eng_failed") : e.status}
                    {e.status === "ok" ? ` (${e.matches})` : ""}
                    {e.error ? ` — ${e.error}` : ""}
                  </span>
                ))}
              </div>
            )}
            <div className="link-row">
              {reverse?.lens_url && (
                <a className="link-btn" href={reverse.lens_url} target="_blank" rel="noreferrer">{t("open_lens")}</a>
              )}
              {reverse?.yandex_url && (
                <a className="link-btn" href={reverse.yandex_url} target="_blank" rel="noreferrer">{t("open_yandex")}</a>
              )}
            </div>
            <div className="match-grid">
              {reverse?.matches?.map((m, i) => (
                <a key={i} className="match" href={m.page_url || m.image_url} target="_blank" rel="noreferrer">
                  {m.thumb_url || m.image_url ? <img src={m.thumb_url || m.image_url} alt="" /> : <div className="thumb-off" />}
                  <div className="match-meta">
                    <span className="match-domain">{m.domain}</span>
                    {m.similarity != null && (
                      <span className="sim" style={{ color: m.similarity >= 70 ? "#34d399" : m.similarity >= 40 ? "#fbbf24" : "#6b7394" }}>
                        {t("pct_similar", { n: m.similarity })}
                      </span>
                    )}
                  </div>
                </a>
              ))}
            </div>
            {!reverse?.matches?.length && <p className="empty">{t("no_similar_frame")}</p>}
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------- APP ------------------------------- */

export default function App() {
  return (
    <LangProvider>
      <Shell />
    </LangProvider>
  );
}

function Shell() {
  const { t, lang, setLang } = useLang();
  const [tab, setTab] = useState("image");
  return (
    <div className="page">
      <header>
        <button className="lang-toggle" onClick={() => setLang(lang === "en" ? "ar" : "en")}>
          {lang === "en" ? "عربي" : "English"}
        </button>
        <h1><span className="grad">{t("brand")}</span></h1>
        {lang === "en" && <p className="latin-name">VeriLens</p>}
        <p className="subtitle">{t("subtitle")}</p>
      </header>

      <div className="tabs">
        <button className={tab === "image" ? "tab active" : "tab"} onClick={() => setTab("image")}>{t("tab_image")}</button>
        <button className={tab === "news" ? "tab active" : "tab"} onClick={() => setTab("news")}>{t("tab_news")}</button>
        <button className={tab === "video" ? "tab active" : "tab"} onClick={() => setTab("video")}>{t("tab_video")}</button>
      </div>

      {tab === "image" ? <ImageVerifier /> : tab === "news" ? <NewsVerifier /> : <VideoVerifier />}

      <footer>
        <div>{t("footer")}</div>
        <div className="signature">✍ {t("signature")}</div>
      </footer>
    </div>
  );
}