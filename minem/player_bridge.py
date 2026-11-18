"""Keep page readiness and keyboard navigation working in embedded exports."""

import re


PLAYER_BRIDGE = """<script id="minem-player-bridge">
(() => {
  if (window.parent === window) return;
  const address = () => { const url = new URL(location.href); url.hash = ''; return url.href; };
  const ready = async () => {
    document.body?.getBoundingClientRect();
    const images = Array.from(document.images);
    for (const image of images) if (image.loading === 'lazy') image.loading = 'eager';
    const fonts = document.fonts.status === 'loaded' ? Promise.resolve() : document.fonts.ready;
    await Promise.all([fonts, ...images.map(image => image.decode().catch(() => {}))]);
    parent.postMessage({type:'minem-player-ready', href:address()}, '*');
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => queueMicrotask(ready), {once:true});
  else ready();
  document.addEventListener('keydown', event => {
    const key = event.key.toLowerCase();
    if (event.defaultPrevented || event.isComposing || event.altKey || event.ctrlKey || event.metaKey ||
        event.target.closest?.('input,textarea,select,button,a,[contenteditable],video,audio')) return;
    if (!['arrowleft','arrowright','pageup','pagedown','home','end',' ','f'].includes(key)) return;
    parent.postMessage({type:'minem-player-key', key, href:address()}, '*');
    event.preventDefault(); event.stopPropagation();
  }, true);
})();
</script>"""


def add_player_bridge(document):
    if 'id="minem-player-bridge"' in document:
        return document
    head = re.search(r"</head\s*>", document, re.I)
    if head:
        return document[:head.start()] + PLAYER_BRIDGE + document[head.start():]
    return PLAYER_BRIDGE + document
