"""Render MineM's platform-level presenter and audience views."""

from __future__ import annotations

import html
from urllib.parse import quote

from minem.html_safety import json_for_html_script


def _page_identity(value: object) -> str:
    return str(value or "").strip().casefold()


def _page_source(value: object) -> str:
    return str(value or "").split("?", 1)[0].split("#", 1)[0].strip().casefold()


def attach_presenter_notes(page_items, presenter_pages=None, notes=None):
    """Attach optional speaker notes to the confirmed report arrangement.

    Legacy AI presenter files key notes by their own page ids. Current report
    arrangements key pages by material ids, so matching prefers stable ids and
    codes, then source/title, and only falls back to position when both lists
    describe the same deck length.
    """
    notes = notes if isinstance(notes, dict) else {}
    legacy_pages = presenter_pages if isinstance(presenter_pages, list) else []
    note_by_key = {
        _page_identity(key): str(value or "").strip()
        for key, value in notes.items()
        if _page_identity(key) and str(value or "").strip()
    }
    legacy = []
    for index, page in enumerate(legacy_pages):
        if not isinstance(page, dict):
            continue
        note = note_by_key.get(_page_identity(page.get("id")), "")
        legacy.append({
            "index": index,
            "id": _page_identity(page.get("id")),
            "code": _page_identity(page.get("code")),
            "title": _page_identity(page.get("title")),
            "src": _page_source(page.get("src")),
            "note": note,
        })

    enriched = []
    positional_match = len(legacy) == len(page_items)
    for index, raw_page in enumerate(page_items):
        page = dict(raw_page)
        direct_keys = (_page_identity(page.get("id")), _page_identity(page.get("code")))
        note = next((note_by_key[key] for key in direct_keys if key in note_by_key), "")
        if not note:
            page_title = _page_identity(page.get("title"))
            page_source = _page_source(page.get("src"))
            candidate = next((
                item for item in legacy
                if item["note"] and (
                    (page_title and item["title"] == page_title)
                    or (page_source and item["src"] == page_source)
                    or any(key and key in (item["id"], item["code"]) for key in direct_keys)
                )
            ), None)
            if candidate:
                note = candidate["note"]
        if not note and positional_match and index < len(legacy):
            note = legacy[index]["note"]
        page["speakerNote"] = note
        page["number"] = index + 1
        enriched.append(page)
    return enriched


def presenter_mode_url(report_id: str) -> str:
    return f"/reports/{quote(str(report_id), safe='')}/presenter.html"


def audience_mode_url(report_id: str) -> str:
    return f"/reports/{quote(str(report_id), safe='')}/audience.html"


def render_presenter_console(
    report_id: str,
    title: str,
    pages,
    session_token: str = "",
    token_header: str = "X-MineM-Session-Token",
) -> str:
    safe_title = html.escape(title or "汇报模式", quote=True)
    template = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>汇报模式 · __TITLE__</title>
  <style>
    :root { color-scheme: dark; font-family: Inter,"PingFang SC","Microsoft YaHei",Arial,sans-serif; }
    * { box-sizing: border-box; }
    html,body { margin: 0; min-width: 1024px; height: 100%; overflow: hidden; background: #111317; color: #f5f7fa; }
    button { font: inherit; }
    .console { height: 100vh; display: grid; grid-template-rows: 58px minmax(0,1fr) 170px; background: #111317; }
    .topbar { display: flex; align-items: center; gap: 14px; padding: 0 18px; border-bottom: 1px solid #30343b; background: #17191d; }
    .brand { min-width: 0; margin-right: auto; }
    .brand strong { display: block; overflow: hidden; color: #f8fafc; font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }
    .brand span { color: #8e98a7; font-size: 12px; }
    .clock,.timer { min-width: 74px; color: #c9d0da; font-variant-numeric: tabular-nums; text-align: center; }
    .clock { font-size: 20px; }
    .timer { display: flex; align-items: center; gap: 6px; font-size: 18px; }
    .icon-btn { width: 36px; height: 36px; display: inline-grid; place-items: center; border: 1px solid #3b424d; border-radius: 6px; color: #e9edf3; background: #22262d; cursor: pointer; }
    .icon-btn:hover,.icon-btn.is-active { border-color: #4eb8ff; background: #16364d; }
    .icon-btn svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    .projector-btn { width: auto; padding: 0 13px; display: inline-flex; gap: 8px; }
    .stage { min-height: 0; display: grid; grid-template-columns: minmax(0,1.72fr) minmax(390px,1fr); gap: 14px; padding: 14px 18px; }
    .current-panel,.side-panel { min-width: 0; min-height: 0; }
    .current-panel { display: grid; grid-template-rows: minmax(0,1fr) 48px; }
    .frame-box { position: relative; min-height: 0; overflow: hidden; border: 1px solid #343a45; border-radius: 6px; background: #030712; }
    .frame-box img { width: 100%; height: 100%; display: block; object-fit: contain; background: #030712; }
    .current-meta { display: flex; align-items: center; gap: 12px; color: #d8dde5; }
    .current-meta strong { overflow: hidden; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
    .counter { flex: none; color: #94a0b0; font-variant-numeric: tabular-nums; }
    .side-panel { display: block; }
    .notes-panel { height: 100%; min-height: 0; display: grid; grid-template-rows: 48px minmax(0,1fr) 48px; border-left: 1px solid #343a45; padding-left: 14px; }
    .notes-header,.notes-footer { display: flex; align-items: center; gap: 10px; }
    .notes-header h2 { margin: 0; color: #d7dde6; font-size: 16px; font-weight: 650; }
    .notes-state { margin-left: auto; color: #7f8a99; font-size: 12px; }
    .notes-state.is-dirty { color: #f1b563; }
    .notes-state.is-error { color: #ff746e; }
    .notes-editor { width: 100%; min-height: 0; resize: none; overflow: auto; border: 1px solid #3a424e; border-radius: 6px; outline: 0; padding: 18px; color: #edf1f7; background: #0d1117; font: 16px/1.72 Inter,"PingFang SC","Microsoft YaHei",sans-serif; caret-color: #56bfff; }
    .notes-editor::placeholder { color: #657080; }
    .notes-editor:focus { border-color: #43aeea; box-shadow: 0 0 0 2px rgba(67,174,234,.16); }
    .notes-footer { justify-content: space-between; color: #717c8b; font-size: 12px; }
    .save-note { height: 34px; display: inline-flex; align-items: center; gap: 7px; border: 1px solid #338fd0; border-radius: 6px; padding: 0 14px; color: #fff; background: #1475b8; cursor: pointer; }
    .save-note:hover { background: #1984ca; }
    .save-note:disabled { cursor: default; opacity: .48; }
    .save-note svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    .filmstrip { min-width: 0; display: flex; gap: 10px; overflow-x: auto; padding: 12px 18px 16px; border-top: 1px solid #30343b; background: #17191d; scroll-behavior: smooth; }
    .thumb { position: relative; flex: 0 0 218px; overflow: hidden; border: 2px solid transparent; border-radius: 6px; padding: 0; color: #fff; background: #070b12; cursor: pointer; text-align: left; }
    .thumb.is-active { border-color: #ff705e; box-shadow: 0 0 0 1px rgba(255,112,94,.25); }
    .thumb-media { width: 100%; aspect-ratio: 16/9; display: grid; place-items: center; overflow: hidden; background: #030712; }
    .thumb img { width: 100%; height: 100%; display: block; object-fit: contain; }
    .thumb img.is-missing { display: none; }
    .thumb-label { height: 34px; display: flex; align-items: center; gap: 7px; padding: 0 9px; background: #22262d; }
    .thumb-label span { color: #8f9aa9; font-size: 11px; font-variant-numeric: tabular-nums; }
    .thumb-label strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
    .keyboard-hint { color: #707b89; font-size: 12px; }
    @media (max-height: 760px) { .console { grid-template-rows: 52px minmax(0,1fr) 138px; } .stage { padding-top: 10px; padding-bottom: 10px; } }
  </style>
</head>
<body>
  <main class="console">
    <header class="topbar">
      <div class="brand"><strong>__TITLE__</strong><span>汇报模式</span></div>
      <span class="keyboard-hint">← → 翻页 · 空格下一页</span>
      <div class="timer"><span class="elapsed">00:00</span><button class="icon-btn timer-toggle" type="button" title="暂停计时" aria-label="暂停计时"><svg viewBox="0 0 24 24"><path d="M9 5v14M15 5v14"></path></svg></button><button class="icon-btn timer-reset" type="button" title="重置计时" aria-label="重置计时"><svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 1 0 3-6.2L4 8"></path><path d="M4 4v4h4"></path></svg></button></div>
      <time class="clock">--:--</time>
      <button class="icon-btn projector-btn open-audience" type="button" title="打开或聚焦投影窗口"><svg viewBox="0 0 24 24"><path d="M4 5h16v11H4zM8 20h8M12 16v4"></path></svg><span>投影窗口</span></button>
      <button class="icon-btn audience-fullscreen" type="button" title="投影全屏" aria-label="投影全屏"><svg viewBox="0 0 24 24"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"></path></svg></button>
    </header>
    <section class="stage">
      <div class="current-panel">
        <div class="frame-box"><img class="current-image" alt="当前页面预览"></div>
        <div class="current-meta"><span class="counter">1 / 1</span><strong class="current-title"></strong></div>
      </div>
      <aside class="side-panel">
        <section class="notes-panel">
          <header class="notes-header"><h2>当前页提示词</h2><span class="notes-state">已保存</span></header>
          <textarea class="notes-editor" maxlength="20000" spellcheck="false" placeholder="输入当前页提示词，可随时修改并保存"></textarea>
          <footer class="notes-footer"><span>支持滚动 · ⌘S 保存</span><button class="save-note" type="button"><svg viewBox="0 0 24 24"><path d="M5 4h12l2 2v14H5zM8 4v6h8V4M8 20v-6h8v6"></path></svg><span>保存</span></button></footer>
        </section>
      </aside>
    </section>
    <nav class="filmstrip" aria-label="全部页面"></nav>
  </main>
  <script>
    const reportId = __REPORT_ID_JSON__;
    const pages = __PAGES_JSON__;
    const audienceUrl = __AUDIENCE_URL_JSON__;
    const sessionToken = __SESSION_TOKEN_JSON__;
    const tokenHeader = __TOKEN_HEADER_JSON__;
    const channelName = `minem-presenter:${reportId}`;
    const storageKey = `${channelName}:state`;
    const channel = "BroadcastChannel" in window ? new BroadcastChannel(channelName) : null;
    const currentImage = document.querySelector(".current-image");
    const counter = document.querySelector(".counter");
    const currentTitle = document.querySelector(".current-title");
    const notesEditor = document.querySelector(".notes-editor");
    const notesState = document.querySelector(".notes-state");
    const saveNoteButton = document.querySelector(".save-note");
    const filmstrip = document.querySelector(".filmstrip");
    const elapsed = document.querySelector(".elapsed");
    const timerToggle = document.querySelector(".timer-toggle");
    let currentIndex = 0;
    let audienceWindow = null;
    let timerStartedAt = Date.now();
    let timerOffset = 0;
    let timerRunning = true;
    const noteDrafts = new Map();
    const dirtyPageIds = new Set();
    let savingPageId = "";
    let editorReady = false;

    function targetFromLocation() {
      const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
      const target = hash.get("page") || "";
      if (!target) return 0;
      const index = pages.findIndex((page) => [page.id,page.code,String(page.number)].includes(target));
      return index < 0 ? 0 : index;
    }
    function publish() {
      const state = { type: "page", reportId, index: currentIndex, updatedAt: Date.now() };
      channel?.postMessage(state);
      try { localStorage.setItem(storageKey, JSON.stringify(state)); } catch (_) {}
    }
    function pageKey(page) { return String(page?.id || page?.code || ""); }
    function preserveCurrentDraft() {
      const page = pages[currentIndex];
      if (!editorReady || !page || savingPageId === pageKey(page)) return;
      const key = pageKey(page);
      const value = notesEditor.value;
      if (value !== String(page.speakerNote || "")) {
        noteDrafts.set(key, value);
        dirtyPageIds.add(key);
      } else {
        noteDrafts.delete(key);
        dirtyPageIds.delete(key);
      }
    }
    function updateNoteState(page) {
      const key = pageKey(page);
      const dirty = dirtyPageIds.has(key);
      notesState.textContent = savingPageId === key ? "保存中" : dirty ? "未保存" : "已保存";
      notesState.classList.toggle("is-dirty", dirty && savingPageId !== key);
      notesState.classList.remove("is-error");
      saveNoteButton.disabled = !dirty || savingPageId === key;
    }
    function show(index, shouldPublish = true) {
      if (!pages.length) return;
      preserveCurrentDraft();
      currentIndex = Math.max(0, Math.min(index, pages.length - 1));
      const page = pages[currentIndex];
      currentImage.src = page.thumbnailUrl || "";
      counter.textContent = `${currentIndex + 1} / ${pages.length}`;
      currentTitle.textContent = page.title || page.code || `第 ${currentIndex + 1} 页`;
      notesEditor.value = noteDrafts.has(pageKey(page)) ? noteDrafts.get(pageKey(page)) : String(page.speakerNote || "");
      notesEditor.scrollTop = 0;
      editorReady = true;
      updateNoteState(page);
      document.querySelectorAll(".thumb").forEach((item, thumbIndex) => item.classList.toggle("is-active", thumbIndex === currentIndex));
      document.querySelector(`.thumb[data-index="${currentIndex}"]`)?.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
      const url = new URL(window.location.href);
      url.hash = `page=${encodeURIComponent(page.code || page.id || currentIndex + 1)}`;
      history.replaceState(null, "", url);
      if (shouldPublish) publish();
    }
    async function saveCurrentNote() {
      const page = pages[currentIndex];
      if (!page) return;
      preserveCurrentDraft();
      const key = pageKey(page);
      if (!dirtyPageIds.has(key) || savingPageId) return;
      savingPageId = key;
      updateNoteState(page);
      let saveError = "";
      try {
        const response = await fetch(`/api/reports/${encodeURIComponent(reportId)}/presenter-notes`, {
          method: "POST",
          headers: { "Content-Type": "application/json", [tokenHeader]: sessionToken },
          body: JSON.stringify({ pageId: key, note: noteDrafts.get(key) || "" }),
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || "保存失败");
        page.speakerNote = result.note || "";
        noteDrafts.delete(key);
        dirtyPageIds.delete(key);
        notesState.textContent = "已保存";
      } catch (error) {
        saveError = error instanceof Error ? error.message : "保存失败";
      } finally {
        savingPageId = "";
        if (pages[currentIndex] === page) {
          updateNoteState(page);
          if (saveError) {
            notesState.textContent = saveError;
            notesState.classList.add("is-error");
          }
        }
      }
    }
    function buildFilmstrip() {
      const fragment = document.createDocumentFragment();
      pages.forEach((page, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "thumb";
        button.dataset.index = String(index);
        button.title = page.title || page.code || `第 ${index + 1} 页`;
        const media = document.createElement("span");
        media.className = "thumb-media";
        const image = document.createElement("img");
        image.loading = index < 8 ? "eager" : "lazy";
        image.alt = "";
        image.src = page.thumbnailUrl || "";
        image.addEventListener("error", () => image.classList.add("is-missing"));
        media.append(image);
        const label = document.createElement("span");
        label.className = "thumb-label";
        const number = document.createElement("span");
        number.textContent = String(index + 1).padStart(2, "0");
        const title = document.createElement("strong");
        title.textContent = page.title || page.code || "页面";
        label.append(number, title);
        button.append(media, label);
        button.addEventListener("click", () => show(index));
        fragment.append(button);
      });
      filmstrip.append(fragment);
    }
    function openAudience(fullscreen = false) {
      audienceWindow = window.open(audienceUrl, `minem-audience-${reportId}`);
      if (!audienceWindow) return;
      audienceWindow.focus();
      window.setTimeout(() => {
        publish();
        if (fullscreen) audienceWindow?.document?.documentElement?.requestFullscreen?.().catch(() => {});
      }, 180);
    }
    function setTimerIcon() {
      timerToggle.title = timerRunning ? "暂停计时" : "继续计时";
      timerToggle.setAttribute("aria-label", timerToggle.title);
      timerToggle.innerHTML = timerRunning
        ? '<svg viewBox="0 0 24 24"><path d="M9 5v14M15 5v14"></path></svg>'
        : '<svg viewBox="0 0 24 24"><path d="m8 5 11 7-11 7z"></path></svg>';
    }
    function updateTime() {
      const now = Date.now();
      const total = timerOffset + (timerRunning ? now - timerStartedAt : 0);
      const seconds = Math.floor(total / 1000);
      elapsed.textContent = `${String(Math.floor(seconds / 60)).padStart(2,"0")}:${String(seconds % 60).padStart(2,"0")}`;
      document.querySelector(".clock").textContent = new Date(now).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
    }
    buildFilmstrip();
    show(targetFromLocation());
    updateTime();
    window.setInterval(updateTime, 500);
    document.querySelector(".open-audience").addEventListener("click", () => openAudience(false));
    document.querySelector(".audience-fullscreen").addEventListener("click", () => openAudience(true));
    notesEditor.addEventListener("input", () => { preserveCurrentDraft(); updateNoteState(pages[currentIndex]); });
    saveNoteButton.addEventListener("click", saveCurrentNote);
    timerToggle.addEventListener("click", () => {
      if (timerRunning) timerOffset += Date.now() - timerStartedAt;
      else timerStartedAt = Date.now();
      timerRunning = !timerRunning;
      setTimerIcon();
    });
    document.querySelector(".timer-reset").addEventListener("click", () => { timerOffset = 0; timerStartedAt = Date.now(); updateTime(); });
    window.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveCurrentNote(); return; }
      if (event.target === notesEditor) return;
      if (["ArrowRight","PageDown"," "].includes(event.key)) { event.preventDefault(); show(currentIndex + 1); }
      if (["ArrowLeft","PageUp"].includes(event.key)) { event.preventDefault(); show(currentIndex - 1); }
      if (event.key === "Home") show(0);
      if (event.key === "End") show(pages.length - 1);
    });
    window.addEventListener("beforeunload", (event) => { if (dirtyPageIds.size) { event.preventDefault(); event.returnValue = ""; } });
    channel?.addEventListener("message", (event) => {
      if (event.data?.type === "command" && event.data.action === "next") show(currentIndex + 1);
      if (event.data?.type === "command" && event.data.action === "previous") show(currentIndex - 1);
    });
  </script>
</body>
</html>'''
    return (template
            .replace("__TITLE__", safe_title)
            .replace("__REPORT_ID_JSON__", json_for_html_script(str(report_id)))
            .replace("__PAGES_JSON__", json_for_html_script(list(pages)))
            .replace("__AUDIENCE_URL_JSON__", json_for_html_script(audience_mode_url(report_id)))
            .replace("__SESSION_TOKEN_JSON__", json_for_html_script(str(session_token or "")))
            .replace("__TOKEN_HEADER_JSON__", json_for_html_script(str(token_header or "X-MineM-Session-Token"))))


def render_audience_view(report_id: str, title: str, pages) -> str:
    safe_title = html.escape(title or "汇报", quote=True)
    template = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>投影 · __TITLE__</title>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    html,body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: #02050c; }
    .stage { position: fixed; inset: 0; display: grid; place-items: center; background: #02050c; }
    .slide-viewport { position: relative; width: calc(1920px * var(--deck-scale,1)); height: calc(1080px * var(--deck-scale,1)); }
    .slide-shell { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; overflow: hidden; transform: scale(var(--deck-scale,1)); transform-origin: left top; background: #02050c; }
    iframe { width: 1920px; height: 1080px; border: 0; background: #02050c; }
    .tools { position: fixed; z-index: 3; top: 18px; right: 18px; display: flex; gap: 8px; opacity: 0; transition: opacity .18s ease; }
    body:hover .tools,.tools:focus-within { opacity: 1; }
    button { width: 40px; height: 40px; display: grid; place-items: center; border: 1px solid rgba(154,176,201,.4); border-radius: 6px; color: #fff; background: rgba(4,9,18,.78); cursor: pointer; }
    button svg { width: 19px; height: 19px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
  </style>
</head>
<body>
  <main class="stage"><div class="slide-viewport"><div class="slide-shell"><iframe title="投影页面" allow="fullscreen"></iframe></div></div></main>
  <div class="tools"><button class="fullscreen" type="button" title="全屏" aria-label="全屏"><svg viewBox="0 0 24 24"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"></path></svg></button></div>
  <script>
    const reportId = __REPORT_ID_JSON__;
    const pages = __PAGES_JSON__;
    const channelName = `minem-presenter:${reportId}`;
    const storageKey = `${channelName}:state`;
    const channel = "BroadcastChannel" in window ? new BroadcastChannel(channelName) : null;
    const frame = document.querySelector("iframe");
    let currentIndex = 0;
    function pageUrl(page) {
      if (!page?.src) return "about:blank";
      const url = new URL(page.src, window.location.href);
      url.searchParams.set("embed", "1");
      return url.toString();
    }
    function updateScale() {
      const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
      document.documentElement.style.setProperty("--deck-scale", String(scale));
    }
    function show(index) {
      if (!pages.length) return;
      currentIndex = Math.max(0, Math.min(Number(index) || 0, pages.length - 1));
      frame.src = pageUrl(pages[currentIndex]);
    }
    function loadStoredState() {
      try { const state = JSON.parse(localStorage.getItem(storageKey) || "{}"); show(state.index || 0); }
      catch (_) { show(0); }
    }
    channel?.addEventListener("message", (event) => { if (event.data?.type === "page") show(event.data.index); });
    window.addEventListener("storage", (event) => { if (event.key === storageKey && event.newValue) { try { show(JSON.parse(event.newValue).index); } catch (_) {} } });
    window.addEventListener("keydown", (event) => {
      if (["ArrowRight","PageDown"," "].includes(event.key)) channel?.postMessage({ type: "command", action: "next" });
      if (["ArrowLeft","PageUp"].includes(event.key)) channel?.postMessage({ type: "command", action: "previous" });
      if (event.key === "f" || event.key === "F") document.documentElement.requestFullscreen?.().catch(() => {});
    });
    document.querySelector(".fullscreen").addEventListener("click", () => document.documentElement.requestFullscreen?.().catch(() => {}));
    window.addEventListener("resize", updateScale);
    updateScale();
    loadStoredState();
  </script>
</body>
</html>'''
    return (template
            .replace("__TITLE__", safe_title)
            .replace("__REPORT_ID_JSON__", json_for_html_script(str(report_id)))
            .replace("__PAGES_JSON__", json_for_html_script(list(pages))))
