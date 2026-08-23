import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { previewSandbox } from "../previewSecurity";
import type { Asset, LineageItem } from "../types";
import { safeAbsoluteUrl, safePreviewUrl } from "../urlSafety";

const HTML_PREVIEW_SIZE = { width: 1920, height: 1080 };

function classNames(...items: Array<string | false | null | undefined>) {
  return items.filter(Boolean).join(" ");
}

function isVisualAsset(asset?: Asset | LineageItem | null) {
  const path = ("preview_url" in (asset || {}) ? (asset as Asset)?.preview_url : (asset as LineageItem)?.previewUrl) || "";
  const kind = "media_kind" in (asset || {}) ? (asset as Asset)?.media_kind : "";
  return ["image", "gif", "svg", "video"].includes(kind || "") || /\.(png|jpe?g|gif|webp|svg|mp4|mov|webm)$/i.test(path);
}

function isImagePreview(url = "") {
  return /\.(png|jpe?g|gif|webp|svg)(?:[?#].*)?$/i.test(url);
}

function previewSource(asset: Asset, mode: "thumbnail" | "interactive") {
  if (mode === "thumbnail") {
    if (asset.thumbnail_url) return asset.thumbnail_url;
    if (["image", "gif", "svg", "video"].includes(asset.media_kind) || isImagePreview(asset.preview_url)) {
      return asset.preview_url;
    }
    if (asset.preview_url) return asset.preview_url;
    return "";
  }
  return asset.preview_url;
}

function previewSizeForAsset(asset: Asset) {
  const width = Math.round(Number(asset.preview_meta?.width || 0));
  const height = Math.round(Number(asset.preview_meta?.height || 0));
  const valid = width >= 320 && height >= 240 && width <= 8000 && height <= 6000;
  return valid ? { width, height } : HTML_PREVIEW_SIZE;
}

function previewDocumentHasError(document?: Document | null) {
  if (!document) return false;
  const title = document.title.trim();
  return Boolean(
    document.querySelector("[data-minem-preview-error]")
    || title === "Error response"
    || /^(?:404(?:\s+Not Found)?|410(?:\s+Gone)?)$/i.test(title)
  );
}

function FramePreview({
  asset,
  src,
  interactive,
  canvasSize
}: {
  asset: Asset;
  src: string;
  interactive: boolean;
  canvasSize?: { width: number; height: number };
}) {
  const safeSrc = safeAbsoluteUrl(src);
  const shellRef = useRef<HTMLDivElement | null>(null);
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [near, setNear] = useState(false);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "slow" | "ready" | "error">("idle");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const { width: frameWidth, height: frameHeight } = canvasSize || previewSizeForAsset(asset);
  const scale = viewport.width && viewport.height ? Math.min(viewport.width / frameWidth, viewport.height / frameHeight) : 0;
  const offsetX = scale ? (viewport.width - frameWidth * scale) / 2 : 0;
  const offsetY = scale ? (viewport.height - frameHeight * scale) / 2 : 0;
  const frameSrc = safeSrc
    ? `${safeSrc}${safeSrc.includes("?") ? "&" : "?"}embed=1&v=${encodeURIComponent(`${asset.updated_at || 0}-${loadAttempt}`)}`
    : "";

  useEffect(() => {
    const node = shellRef.current;
    if (!node || near) return;
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) if (entry.isIntersecting) { setNear(true); observer.disconnect(); }
      },
      { rootMargin: "800px 0px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [near]);

  useEffect(() => {
    const node = shellRef.current;
    if (!node || !near) return;
    const measure = () => {
      const rect = node.getBoundingClientRect();
      setViewport({ width: rect.width, height: rect.height });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [near]);

  useEffect(() => {
    if (!near) {
      setLoadState("idle");
      return;
    }
    setLoadState("loading");
    const timer = window.setTimeout(() => {
      setLoadState((current) => current === "loading" ? "slow" : current);
    }, 6000);
    return () => window.clearTimeout(timer);
  }, [frameSrc, near]);

  return (
    <div
      className={classNames("frame-shell", asset.preview_meta?.longPage && "is-long-page", `is-${loadState}`)}
      ref={shellRef}
      style={{ aspectRatio: `${frameWidth} / ${frameHeight}` }}
    >
      {near && frameSrc ? (
        <div
          className="frame-stage"
          style={{
            width: frameWidth,
            height: frameHeight,
            opacity: scale && loadState !== "error" ? 1 : 0,
            transform: `translate(${offsetX}px, ${offsetY}px) scale(${scale || 1})`
          }}
        >
          <iframe
            ref={frameRef}
            className={classNames("page-frame", interactive && "is-interactive")}
            src={frameSrc}
            title={asset.title}
            loading="lazy"
            sandbox={previewSandbox(safeSrc)}
            referrerPolicy="no-referrer"
            onLoad={() => {
              try {
                const document = frameRef.current?.contentDocument;
                if (previewDocumentHasError(document)) {
                  setLoadState("error");
                  return;
                }
              } catch {
                // Cross-origin previews cannot be inspected after load.
              }
              setLoadState("ready");
            }}
            onError={() => setLoadState("error")}
          />
        </div>
      ) : (
        <div className="frame-stage-pending" aria-hidden="true" />
      )}
      {near && frameSrc && loadState === "loading" ? (
        <div className="preview-status" role="status"><Loader2 className="spin" size={18} /><span>正在加载预览</span></div>
      ) : null}
      {near && frameSrc && loadState === "slow" ? (
        <div className="preview-status is-slow" role="status">
          <Loader2 className="spin" size={18} />
          <span>页面资源较多，仍在加载</span>
        </div>
      ) : null}
      {near && (!frameSrc || loadState === "error") ? (
        <div className="preview-status is-error" role="alert">
          <AlertCircle size={20} />
          <strong>预览暂时无法显示</strong>
          <span>{frameSrc ? "素材仍然保留，可以重新加载或打开原链接。" : "预览地址不在安全白名单中。"}</span>
          {frameSrc ? <button type="button" onClick={() => setLoadAttempt((attempt) => attempt + 1)}><RefreshCw size={14} />重新加载</button> : null}
        </div>
      ) : null}
    </div>
  );
}

function MediaPreview({
  src,
  title,
  video = false,
  compact = false
}: {
  src: string;
  title: string;
  video?: boolean;
  compact?: boolean;
}) {
  const safeSrc = safePreviewUrl(src);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const versionedSrc = safeSrc.startsWith("data:")
    ? safeSrc
    : safeSrc ? `${safeSrc}${safeSrc.includes("?") ? "&" : "?"}preview_attempt=${loadAttempt}` : "";
  const content = !versionedSrc
    ? null
    : video
    ? <video className="media-preview" src={versionedSrc} muted playsInline controls={!compact} onLoadedData={() => setLoadState("ready")} onError={() => setLoadState("error")} />
    : <img className="media-preview" src={versionedSrc} alt={title} loading="lazy" onLoad={() => setLoadState("ready")} onError={() => setLoadState("error")} />;
  return (
    <div className={classNames("media-preview-shell", `is-${loadState}`)}>
      {content}
      {versionedSrc && loadState === "loading" && !compact ? <div className="preview-status" role="status"><Loader2 className="spin" size={18} /><span>正在加载预览</span></div> : null}
      {!versionedSrc || loadState === "error" ? (
        <div className="preview-status is-error" role="alert">
          <AlertCircle size={compact ? 16 : 20} />
          <strong>{compact ? "预览不可用" : versionedSrc ? "媒体预览加载失败" : "预览地址不安全"}</strong>
          {!compact && versionedSrc ? <button type="button" onClick={() => { setLoadState("loading"); setLoadAttempt((attempt) => attempt + 1); }}><RefreshCw size={14} />重新加载</button> : null}
        </div>
      ) : null}
    </div>
  );
}

export function Preview({ asset, mode = "interactive", compact = false }: { asset: Asset; mode?: "thumbnail" | "interactive"; compact?: boolean }) {
  const src = previewSource(asset, mode);
  if (mode === "interactive" && asset.asset_type === "report") {
    return <FramePreview asset={asset} src={`/reports/${encodeURIComponent(asset.id)}/index.html`} interactive canvasSize={HTML_PREVIEW_SIZE} />;
  }
  if (mode === "interactive" && asset.asset_type === "control") {
    return <FramePreview asset={asset} src={`/pages/${encodeURIComponent(asset.id)}/index.html`} interactive canvasSize={HTML_PREVIEW_SIZE} />;
  }
  if (!src && asset.preview_url && asset.media_kind === "html") {
    return <FramePreview asset={asset} src={asset.preview_url} interactive={mode === "interactive"} />;
  }
  if (!src) return <div className="preview-fallback">{asset.mediaLabel || asset.typeLabel}</div>;
  if (asset.media_kind === "video") {
    return <MediaPreview src={src} title={asset.title} video compact={compact} />;
  }
  if (["image", "gif", "svg"].includes(asset.media_kind) || isImagePreview(src)) {
    return <MediaPreview src={src} title={asset.title} compact={compact} />;
  }
  if (mode === "thumbnail" && asset.asset_type === "resource") {
    return <MediaPreview src={src} title={asset.title} compact={compact} />;
  }
  return <FramePreview asset={asset} src={src} interactive={mode === "interactive"} />;
}

export function LineagePreview({ item }: { item?: LineageItem }) {
  const src = isVisualAsset(item)
    ? safePreviewUrl(item?.previewUrl)
    : safeAbsoluteUrl(item?.previewUrl);
  if (!item?.previewUrl || !src) return <div className="preview-fallback">无预览</div>;
  if (isVisualAsset(item)) return <img src={src} alt={item.title || item.assetCode || ""} loading="lazy" />;
  return (
    <div className="lineage-frame-shell">
      <iframe src={src} title={item.title || item.assetCode || ""} loading="lazy" sandbox={previewSandbox(src)} referrerPolicy="no-referrer" />
    </div>
  );
}
