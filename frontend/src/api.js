import axios from "axios";

export const api = axios.create({ baseURL: "/api/v1" });

export function verifyImage(file, onProgress) {
  const form = new FormData();
  form.append("file", file);
  return api.post("/verify/image", form, {
    onUploadProgress: (e) => onProgress && onProgress(Math.round((e.loaded / e.total) * 100)),
    timeout: 120000,
  });
}

export function verifyNews(query) {
  return api.post("/verify/news", { query }, { timeout: 120000 });
}

export function verifyVideo(file, onProgress) {
  const form = new FormData();
  form.append("file", file);
  return api.post("/verify/video", form, {
    onUploadProgress: (e) => onProgress && onProgress(Math.round((e.loaded / e.total) * 100)),
    timeout: 600000,
  });
}

export function verifyVideoUrl(url, onProgress) {
  return api.post("/verify/video_url", { url }, { timeout: 600000 });
}

export function fetchHistory() {
  return api.get("/history");
}
