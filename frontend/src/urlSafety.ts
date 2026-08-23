const SAFE_DATA_MEDIA = /^data:(?:image|video)\/[a-z0-9.+-]+(?:;[a-z0-9=.+-]+)*(?:;base64)?,/i;

function baseUrl(base?: string) {
  if (base) return base;
  if (typeof window !== "undefined") return window.location.href;
  return "http://127.0.0.1/";
}

function parsedUrl(value?: string, base?: string) {
  const raw = String(value || "").trim();
  if (!raw || /[\u0000-\u001f\u007f]/.test(raw)) return null;
  try {
    const target = new URL(raw, baseUrl(base));
    if (target.username || target.password) return null;
    return target;
  } catch {
    return null;
  }
}

export function safeAbsoluteUrl(value?: string, base?: string) {
  const target = parsedUrl(value, base);
  if (!target) return "";
  if (target.protocol === "https:") return target.href;
  if (target.protocol !== "http:") return "";
  const source = parsedUrl(baseUrl(base), base);
  return source && target.origin === source.origin ? target.href : "";
}

export function safePreviewUrl(value?: string, base?: string) {
  const raw = String(value || "").trim();
  if (SAFE_DATA_MEDIA.test(raw)) return raw;
  const target = parsedUrl(raw, base);
  if (!target) return "";
  if (target.protocol === "blob:") {
    const source = parsedUrl(baseUrl(base), base);
    return source && target.origin === source.origin ? target.href : "";
  }
  return safeAbsoluteUrl(raw, base);
}
