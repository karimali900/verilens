import React, { createContext, useContext, useEffect, useState } from "react";

const en = {
  brand: "🔍 المُدقِّق VeriLens",
  subtitle: "Is this image real or fake? Is this news true, and who broke it first? Search the whole web to find out.",
  tab_image: "🖼 Verify an image",
  tab_news: "📰 Verify news",
  tab_video: "🎬 Verify a video",
  footer: "VeriLens (المُدقِّق) · reverse-image search (Bing + Google Lens) · news across GDELT, Google News, Reddit & fact-check databases · forensic signals are heuristic, not proof.",
  signature: "Built by Karim Abdelaziz",

  verdict_likely_real: "Likely real",
  verdict_unverified: "Unverified",
  verdict_likely_fake: "Likely fake",
  confidence: "{n}/100 confidence",

  click_change: "Click to change · {name}",
  drop_image: "🖼 Drop an image here or click to browse",
  analyzing: "Analyzing… {n}%",
  verify_image: "Verify image",
  verify_failed: "Verification failed",

  img_forensics: "Image forensics",
  dims: "Dimensions",
  format: "Format",
  exif_tags: "EXIF tags",
  ela_max: "ELA max",
  show_ela: "Show ELA heatmap (editing hotspots)",
  show_exif: "Show EXIF metadata",
  ela_title: "Error Level Analysis",
  exif_title: "EXIF metadata",

  similar_images: "Similar images on the web ({n} matches)",
  eng_ready: "ready — open in your browser",
  eng_ok: "ready",
  eng_failed: "failed",
  eng_error: "error",
  hosted_at_pre: "Analyzed copy hosted at ",
  open_lens: "Open in Google Lens ↗",
  open_yandex: "Open in Yandex Images ↗",
  pct_similar: "{n}% similar",
  no_similar_img: "No similar images located. This is common for fresh or AI-generated images.",
  found_on: "Found on: {list}",

  news_placeholder: "Paste a claim, headline, or breaking news text to verify across news sites, Google News, social media (Reddit) and fact-check databases…",
  scanning: "Scanning the web…",
  verify_news: "Verify news",
  first_publisher: "First publisher",
  unknown: "unknown",
  read_first_trace: "Read first trace ↗",
  no_traces: "No dated traces found in the scanned window.",
  coverage: "Coverage",
  coverage_sub: "{a} articles · {d} independent publications",
  factcheck_watch: "Fact-check watch ({n})",
  timeline: "Timeline · newest first",
  no_articles: "No articles found.",

  video_url_ph: "…or paste a video URL (YouTube, TikTok, X, etc.) to download & verify",
  drop_video: "🎬 Drop a video file here or click to browse",
  uploading: "Uploading… {n}%",
  downloading: "Downloading & analyzing…",
  verify_video: "Verify video",
  video_meta: "Video metadata",
  duration: "Duration",
  resolution: "Resolution",
  codec: "Codec",
  frames_checked: "Frames checked",
  by_uploader: "by {name}",
  views: "{n} views",
  frames_sampled: "6 frames sampled across the clip, each reverse-searched independently.",
  key_frames: "Key frames · click to inspect matches",
  web_matches: "{n} web matches",
  frame_matches_title: "Frame {i} · web matches",
  best_frame: "best: frame {i} ({n} matches)",
  no_similar_frame: "No similar frames found on the web — may be fresh, private, or AI-generated footage.",
};

const ar = {
  brand: "🔍 المُدقِّق",
  subtitle: "هل هذه الصورة حقيقية أم مزيفة؟ هل هذا الخبر صحيح، ومن نشره أولاً؟ ابحث في الويب كاملاً لتعرف.",
  tab_image: "🖼 تحقّق من صورة",
  tab_news: "📰 تحقّق من خبر",
  tab_video: "🎬 تحقّق من فيديو",
  footer: "المُدقِّق VeriLens · البحث العكسي عن الصور (Bing و Google Lens) · الأخبار عبر GDELT و Google News و Reddit وقواعد بيانات التحقق من الأخبار · الإشارات الجنائية استرشادية وليست إثباتاً.",
  signature: "من تطوير كريم عبد العزيز",

  verdict_likely_real: "يبدو حقيقياً",
  verdict_unverified: "غير مؤكَّد",
  verdict_likely_fake: "يبدو مزيفاً",
  confidence: "الثقة {n}/100",

  click_change: "اضغط للتغيير · {name}",
  drop_image: "🖼 أسقط صورة هنا أو اضغط للتصفّح",
  analyzing: "جارٍ التحليل… {n}%",
  verify_image: "تحقّق من الصورة",
  verify_failed: "فشل التحقق",

  img_forensics: "الفحص الجنائي للصورة",
  dims: "الأبعاد",
  format: "الصيغة",
  exif_tags: "وسوم EXIF",
  ela_max: "أقصى ELA",
  show_ela: "إظهار خريطة ELA (مناطق التعديل)",
  show_exif: "إظهار بيانات EXIF",
  ela_title: "تحليل مستوى الخطأ",
  exif_title: "بيانات EXIF",

  similar_images: "صور مشابهة على الويب ({n} نتيجة)",
  eng_ready: "جاهز — افتحه في متصفحك",
  eng_ok: "جاهز",
  eng_failed: "فشل",
  eng_error: "خطأ",
  hosted_at_pre: "نسخة التحليل مستضافة على ",
  open_lens: "فتح في Google Lens ↗",
  open_yandex: "فتح في Yandex Images ↗",
  pct_similar: "تشابه {n}%",
  no_similar_img: "لا توجد صور مشابهة. هذا شائع مع الصور الجديدة أو المولَّدة بالذكاء الاصطناعي.",
  found_on: "ظهرت في: {list}",

  news_placeholder: "الصق خبراً أو عنواناً أو نصاً إخبارياً للتحقق منه عبر المواقع الإخبارية و Google News ووسائل التواصل (Reddit) وقواعد بيانات التحقق…",
  scanning: "جارٍ مسح الويب…",
  verify_news: "تحقّق من الخبر",
  first_publisher: "أول ناشر",
  unknown: "غير معروف",
  read_first_trace: "اطّلع على أول أثر ↗",
  no_traces: "لا توجد آثار مؤرّخة ضمن نافذة المسح.",
  coverage: "التغطية",
  coverage_sub: "{a} مقال · {d} منشورات مستقلة",
  factcheck_watch: "رصد التحقق من الأخبار ({n})",
  timeline: "الخط الزمني · الأحدث أولاً",
  no_articles: "لا توجد مقالات.",

  video_url_ph: "…أو الصق رابط فيديو (YouTube أو TikTok أو X…) للتحميل والتحقق",
  drop_video: "🎬 أسقط ملف فيديو هنا أو اضغط للتصفّح",
  uploading: "جارٍ الرفع… {n}%",
  downloading: "جارٍ التحميل والتحليل…",
  verify_video: "تحقّق من الفيديو",
  video_meta: "بيانات الفيديو",
  duration: "المدة",
  resolution: "الدقة",
  codec: "الترميز",
  frames_checked: "الإطارات المفحوصة",
  by_uploader: "بواسطة {name}",
  views: "{n} مشاهدة",
  frames_sampled: "تم أخذ 6 إطارات من المقطع، وفحص كل إطار بالبحث العكسي على حدة.",
  key_frames: "إطارات مفتاحية · اضغط لفحص النتائج",
  web_matches: "{n} نتيجة على الويب",
  frame_matches_title: "الإطار {i} · نتائج الويب",
  best_frame: "الأفضل: الإطار {i} ({n} نتيجة)",
  no_similar_frame: "لا توجد إطارات مشابهة على الويب — قد يكون الفيديو جديداً أو خاصاً أو مولَّداً بالذكاء الاصطناعي.",
};

const dicts = { en, ar };

export function createT(lang) {
  const d = dicts[lang] || en;
  return (key, vars, fallback) => {
    let s = d[key] ?? en[key] ?? fallback ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
    return s;
  };
}

const LangCtx = createContext(null);

export function LangProvider({ children }) {
  const [lang, setLang] = useState(
    () => localStorage.getItem("verilens_lang") || (navigator.language?.startsWith("ar") ? "ar" : "en")
  );
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    document.title = lang === "ar" ? "المُدقِّق VeriLens — التحقق من الصور والأخبار" : "VeriLens (المُدقِّق) — verify images, news & videos";
    localStorage.setItem("verilens_lang", lang);
  }, [lang]);
  return (
    <LangCtx.Provider value={{ lang, setLang, t: createT(lang), L: lang }}>
      {children}
    </LangCtx.Provider>
  );
}

export function useLang() {
  return useContext(LangCtx);
}
