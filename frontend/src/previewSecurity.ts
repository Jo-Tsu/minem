import { safePreviewUrl } from "./urlSafety";

const TRUSTED_PREVIEW_SANDBOX = "allow-scripts allow-same-origin allow-forms allow-modals allow-popups allow-downloads";
const SOURCE_PREVIEW_SANDBOX = "allow-scripts";

function isTrustedPreviewPath(path: string) {
  return (
    path.startsWith("/pages/")
    || path.startsWith("/reports/")
    || path.startsWith("/case-groups/")
    || path.startsWith("/temp-reports/")
    || (path.startsWith("/api/reports/") && path.endsWith("/arrangement/viewer"))
  );
}

export function previewSandbox(src: string) {
  try {
    const safeSrc = safePreviewUrl(src);
    if (!safeSrc) return SOURCE_PREVIEW_SANDBOX;
    const target = new URL(safeSrc, window.location.href);
    if (target.origin !== window.location.origin) return SOURCE_PREVIEW_SANDBOX;
    return isTrustedPreviewPath(target.pathname)
      ? TRUSTED_PREVIEW_SANDBOX
      : SOURCE_PREVIEW_SANDBOX;
  } catch {
    return SOURCE_PREVIEW_SANDBOX;
  }
}
