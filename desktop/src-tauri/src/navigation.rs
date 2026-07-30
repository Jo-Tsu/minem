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
    const origin = event.target instanceof Element ? event.target : event.target?.parentElement;
    const link = origin?.closest?.('a[target="_blank"]');
    if (!link?.href || event.defaultPrevented) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    bridge(link.href);
  }, true);
  const nativeOpen = window.open.bind(window);
  window.open = (url, target, features) => {
    if (url && target === "_blank") {
      bridge(url);
      return null;
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
    let mut builder = WebviewWindowBuilder::new(app, label, WebviewUrl::External(target))
        .title("MineM")
        .inner_size(1440.0, 920.0)
        .min_inner_size(1080.0, 720.0)
        .tabbing_identifier(TAB_GROUP)
        .initialization_script(LINK_BRIDGE_SCRIPT)
        .on_navigation(move |next| handle_navigation(&navigation_app, next));
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
    if is_mine_m_url(target) {
        remember(target);
        true
    } else {
        open_external(target);
        false
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
        .on_new_window(move |target, features| {
            if !is_mine_m_url(&target) {
                open_external(&target);
                return NewWindowResponse::Deny;
            }
            match build_tab(&new_window_app, target, Some(features)) {
                Ok(window) => NewWindowResponse::Create { window },
                Err(error) => {
                    eprintln!("无法创建 MineM 标签页：{error}");
                    NewWindowResponse::Deny
                }
            }
        })
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
