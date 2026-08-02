const TRUSTED_PREVIEW_SANDBOX = "allow-scripts allow-same-origin allow-forms allow-modals allow-popups allow-downloads";
const SOURCE_PREVIEW_SANDBOX = "allow-scripts allow-forms allow-modals allow-popups allow-downloads";

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
    const target = new URL(src, window.location.href);
    if (target.origin !== window.location.origin) return SOURCE_PREVIEW_SANDBOX;
    return isTrustedPreviewPath(target.pathname)
      ? TRUSTED_PREVIEW_SANDBOX
      : SOURCE_PREVIEW_SANDBOX;
  } catch {
    return SOURCE_PREVIEW_SANDBOX;
  }
}
