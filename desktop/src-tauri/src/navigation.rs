use std::{
    process::Command,
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
};

use tauri::{
    webview::NewWindowResponse, AppHandle, Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};
use url::Url;

use crate::desktop_runtime::current_port;

const TAB_GROUP: &str = "com.minem.materialos.tabs";
const TAB_BRIDGE_PATH: &str = "/__minem_open_tab";
static TAB_COUNTER: AtomicU64 = AtomicU64::new(1);
static LAST_CONTEXT_URL: Mutex<String> = Mutex::new(String::new());

const LINK_BRIDGE_SCRIPT: &str = r#"
(() => {
  const bridge = (rawUrl) => {
    const target = new URL(rawUrl, window.location.href).href;
    window.location.assign(`${window.location.origin}/__minem_open_tab?url=${encodeURIComponent(target)}`);
  };
  document.addEventListener("click", (event) => {
    if (!event.isTrusted) return;
    const origin = event.target instanceof Element ? event.target : event.target?.parentElement;
    const link = origin?.closest?.('a[href]');
    if (!link?.href || event.defaultPrevented) return;
    const target = new URL(link.href, window.location.href);
    const opensNewWindow = link.target === "_blank";
    const opensExternalSite = /^(https?):$/.test(target.protocol)
      && target.origin !== window.location.origin;
    if (!opensNewWindow && !opensExternalSite) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    bridge(target.href);
  }, true);
  const nativeOpen = window.open.bind(window);
  window.open = (url, target, features) => {
    if (url && target === "_blank") {
      bridge(url);
      // Return a truthy Window-like value. Callers commonly interpret null as
      // a popup blocker and fall back to window.location, which would replace
      // the MineM shell even though the native bridge accepted the request.
      return window;
    }
    return nativeOpen(url, target, features);
  };
})();
"#;

pub fn remember(url: &Url) {
    if is_mine_m_url(url) && url.path() != TAB_BRIDGE_PATH {
        if let Ok(mut current) = LAST_CONTEXT_URL.lock() {
            *current = url.to_string();
        }
    }
}

pub fn current_url() -> String {
    LAST_CONTEXT_URL
        .lock()
        .map(|value| value.clone())
        .unwrap_or_default()
}

pub fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn is_mine_m_url(url: &Url) -> bool {
    url.scheme() == "tauri"
        || (url.scheme() == "http"
            && matches!(url.host_str(), Some("127.0.0.1") | Some("localhost"))
            && url.port_or_known_default() == Some(current_port()))
}

fn open_external(url: &Url) {
    if matches!(url.scheme(), "http" | "https") {
        let _ = Command::new("open").arg(url.as_str()).spawn();
    }
}

fn tab_bridge_target(url: &Url) -> Option<Url> {
    if !is_mine_m_url(url) || url.path() != TAB_BRIDGE_PATH {
        return None;
    }
    url.query_pairs()
        .find(|(key, _)| key == "url")
        .and_then(|(_, target)| target.parse::<Url>().ok())
}

fn build_tab(
    app: &AppHandle,
    target: Url,
    features: Option<tauri::webview::NewWindowFeatures>,
) -> tauri::Result<tauri::WebviewWindow> {
    remember(&target);
    let label = format!("tab-{}", TAB_COUNTER.fetch_add(1, Ordering::Relaxed));
    let navigation_app = app.clone();
    let new_window_app = app.clone();
    let mut builder = WebviewWindowBuilder::new(app, label, WebviewUrl::External(target))
        .title("MineM")
        .inner_size(1440.0, 920.0)
        .min_inner_size(1080.0, 720.0)
        .tabbing_identifier(TAB_GROUP)
        .initialization_script(LINK_BRIDGE_SCRIPT)
        .on_navigation(move |next| handle_navigation(&navigation_app, next))
        .on_new_window(move |target, features| {
            handle_new_window(&new_window_app, target, features)
        });
    if let Some(features) = features {
        builder = builder.window_features(features);
    }
    builder.build()
}

fn handle_navigation(app: &AppHandle, target: &Url) -> bool {
    if let Some(tab_target) = tab_bridge_target(target) {
        if is_mine_m_url(&tab_target) {
            if let Ok(window) = build_tab(app, tab_target, None) {
                let _ = window.set_focus();
            }
        } else {
            open_external(&tab_target);
        }
        return false;
    }
    // Wry's macOS navigation callback is also invoked for iframe requests and
    // does not expose whether the target belongs to the main frame. Opening
    // every external URL here therefore turns a normal remote iframe source
    // into an unexpected system-browser launch. Explicit user requests already
    // travel through TAB_BRIDGE_PATH (anchors/window.open) or on_new_window, so
    // let subframe navigations proceed here and never launch an external app.
    if is_mine_m_url(target) {
        remember(target);
    }
    true
}

fn handle_new_window(
    app: &AppHandle,
    target: Url,
    features: tauri::webview::NewWindowFeatures,
) -> NewWindowResponse<tauri::Wry> {
    if !is_mine_m_url(&target) {
        open_external(&target);
        return NewWindowResponse::Deny;
    }
    match build_tab(app, target, Some(features)) {
        Ok(window) => NewWindowResponse::Create { window },
        Err(error) => {
            eprintln!("无法创建 MineM 标签页：{error}");
            NewWindowResponse::Deny
        }
    }
}

pub fn open_main_window(app: &AppHandle, url: WebviewUrl) -> tauri::Result<()> {
    let navigation_app = app.clone();
    let new_window_app = app.clone();
    let window = WebviewWindowBuilder::new(app, "main", url)
        .title("MineM")
        .inner_size(1440.0, 920.0)
        .min_inner_size(1080.0, 720.0)
        .tabbing_identifier(TAB_GROUP)
        .initialization_script(LINK_BRIDGE_SCRIPT)
        .on_navigation(move |target| handle_navigation(&navigation_app, target))
        .on_new_window(move |target, features| handle_new_window(&new_window_app, target, features))
        .build()?;
    let close_window = window.clone();
    window.on_window_event(move |event| {
        if let WindowEvent::CloseRequested { api, .. } = event {
            let _ = close_window.hide();
            api.prevent_close();
        }
    });
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{is_mine_m_url, tab_bridge_target, LINK_BRIDGE_SCRIPT, TAB_BRIDGE_PATH};
    use url::Url;

    fn parse(value: &str) -> Url {
        Url::parse(value).expect("test URL must be valid")
    }

    #[test]
    fn mine_m_urls_are_limited_to_the_active_local_service() {
        let port = crate::desktop_runtime::current_port();
        assert!(is_mine_m_url(&parse(&format!(
            "http://127.0.0.1:{port}/reports/1"
        ))));
        assert!(is_mine_m_url(&parse(&format!(
            "http://localhost:{port}/pages/1"
        ))));
        assert!(is_mine_m_url(&parse("tauri://localhost/index.html")));

        assert!(!is_mine_m_url(&parse(&format!(
            "http://127.0.0.1:{}/reports/1",
            port.saturating_add(1)
        ))));
        assert!(!is_mine_m_url(&parse("https://example.com/embedded")));
    }

    #[test]
    fn bridge_target_decodes_explicit_internal_and_external_urls() {
        let port = crate::desktop_runtime::current_port();
        let internal = format!("http://localhost:{port}/pages/page-1?mode=preview");
        let internal_bridge = parse(&format!(
            "http://127.0.0.1:{port}{TAB_BRIDGE_PATH}?url={}",
            url::form_urlencoded::byte_serialize(internal.as_bytes()).collect::<String>()
        ));
        assert_eq!(
            tab_bridge_target(&internal_bridge)
                .as_ref()
                .map(Url::as_str),
            Some(internal.as_str())
        );

        let external = "https://example.com/watch?q=mine%20m#demo";
        let external_bridge = parse(&format!(
            "http://127.0.0.1:{port}{TAB_BRIDGE_PATH}?url={}",
            url::form_urlencoded::byte_serialize(external.as_bytes()).collect::<String>()
        ));
        assert_eq!(
            tab_bridge_target(&external_bridge)
                .as_ref()
                .map(Url::as_str),
            Some(external)
        );
    }

    #[test]
    fn bridge_target_rejects_untrusted_or_malformed_requests() {
        let port = crate::desktop_runtime::current_port();
        assert_eq!(
            tab_bridge_target(&parse(&format!(
                "http://127.0.0.1:{port}/not-the-bridge?url=https%3A%2F%2Fexample.com"
            ))),
            None
        );
        assert_eq!(
            tab_bridge_target(&parse(&format!("http://127.0.0.1:{port}{TAB_BRIDGE_PATH}"))),
            None
        );
        assert_eq!(
            tab_bridge_target(&parse(&format!(
                "http://127.0.0.1:{port}{TAB_BRIDGE_PATH}?url=not-a-url"
            ))),
            None
        );
        assert_eq!(
            tab_bridge_target(&parse(&format!(
                "https://example.com{TAB_BRIDGE_PATH}?url=https%3A%2F%2Fexample.org"
            ))),
            None
        );
    }

    #[test]
    fn ordinary_navigation_never_routes_to_the_system_browser() {
        let source = include_str!("navigation.rs");
        let handler_start = source
            .find("fn handle_navigation(")
            .expect("navigation handler must exist");
        let handler_end = source[handler_start..]
            .find("\nfn handle_new_window")
            .map(|offset| handler_start + offset)
            .expect("navigation handler must end before the new-window handler");
        let handler = &source[handler_start..handler_end];

        assert!(handler.contains("tab_bridge_target(target)"));
        assert!(handler.contains("open_external(&tab_target);"));
        assert!(!handler.contains("open_external(target);"));
        assert!(handler.trim_end().ends_with("true\n}"));
    }

    #[test]
    fn every_mine_m_window_installs_the_explicit_new_window_policy() {
        let source = include_str!("navigation.rs");
        let production = source
            .split("#[cfg(test)]")
            .next()
            .expect("production source must precede its tests");
        assert_eq!(production.matches(".on_new_window(").count(), 2);
        assert_eq!(
            production
                .matches("handle_new_window(&new_window_app")
                .count(),
            2
        );
    }

    #[test]
    fn link_bridge_captures_trusted_anchors_and_returns_a_window_like_value() {
        assert!(LINK_BRIDGE_SCRIPT.contains(r#"a[href]"#));
        assert!(LINK_BRIDGE_SCRIPT.contains("if (!event.isTrusted) return;"));
        assert!(LINK_BRIDGE_SCRIPT.contains("opensExternalSite"));
        assert!(LINK_BRIDGE_SCRIPT.contains("target.origin !== window.location.origin"));
        assert!(LINK_BRIDGE_SCRIPT.contains(r#"target === "_blank""#));
        assert!(LINK_BRIDGE_SCRIPT.contains("return window;"));
        assert!(!LINK_BRIDGE_SCRIPT.contains("return null;"));
    }
}
