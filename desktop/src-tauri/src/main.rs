use std::{
    env,
    io::{Read, Write},
    net::TcpStream,
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
    thread,
    time::{Duration, Instant},
};

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    webview::NewWindowResponse,
    AppHandle, Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use url::Url;

const SERVICE_HOST: &str = "127.0.0.1";
const SERVICE_PORT: u16 = 8790;
const TAB_GROUP: &str = "com.minem.materialos.tabs";
static TAB_COUNTER: AtomicU64 = AtomicU64::new(1);
const TAB_BRIDGE_PATH: &str = "/__minem_open_tab";
const QUICK_ACTIONS_LABEL: &str = "quick-actions";
const QUICK_ACTIONS_MENU_ID: &str = "quick-actions";
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

struct ServiceState {
    child: Mutex<Option<Child>>,
}

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("MineM project root must exist")
}

fn service_url() -> String {
    format!("http://{SERVICE_HOST}:{SERVICE_PORT}/")
}

fn service_webview_url() -> Result<WebviewUrl, String> {
    service_url()
        .parse::<Url>()
        .map(WebviewUrl::External)
        .map_err(|error| error.to_string())
}

fn remember_context_url(url: &Url) {
    if is_minem_url(url) && url.path() != TAB_BRIDGE_PATH {
        if let Ok(mut current) = LAST_CONTEXT_URL.lock() {
            *current = url.to_string();
        }
    }
}

fn is_minem_url(url: &Url) -> bool {
    url.scheme() == "tauri"
        || (url.scheme() == "http"
            && matches!(url.host_str(), Some("127.0.0.1") | Some("localhost"))
            && url.port_or_known_default() == Some(SERVICE_PORT))
}

fn open_in_system_browser(url: &Url) {
    if matches!(url.scheme(), "http" | "https") {
        let _ = Command::new("open").arg(url.as_str()).spawn();
    }
}

fn show_quick_actions(app: &AppHandle) -> Result<(), String> {
    let window = if let Some(window) = app.get_webview_window(QUICK_ACTIONS_LABEL) {
        window
    } else {
        let window = WebviewWindowBuilder::new(
            app,
            QUICK_ACTIONS_LABEL,
            WebviewUrl::App("quick-actions.html".into()),
        )
        .title("MineM 创作助手")
        .inner_size(500.0, 700.0)
        .min_inner_size(460.0, 650.0)
        .max_inner_size(560.0, 760.0)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .visible(false)
        .build()
        .map_err(|error| error.to_string())?;
        let hide_window = window.clone();
        window.on_window_event(move |event| {
            if matches!(event, WindowEvent::Focused(false)) {
                let _ = hide_window.hide();
            }
        });
        window
    };
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn quick_clipboard_read() -> Result<String, String> {
    let output = Command::new("pbpaste")
        .output()
        .map_err(|error| format!("无法读取剪贴板：{error}"))?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        Err("无法读取剪贴板".to_string())
    }
}

#[tauri::command]
fn quick_clipboard_write(text: String) -> Result<(), String> {
    let mut child = Command::new("pbcopy")
        .stdin(Stdio::piped())
        .spawn()
        .map_err(|error| format!("无法写入剪贴板：{error}"))?;
    let Some(mut input) = child.stdin.take() else {
        return Err("无法打开剪贴板写入通道".to_string());
    };
    input
        .write_all(text.as_bytes())
        .map_err(|error| format!("无法写入剪贴板：{error}"))?;
    if child.wait().map_err(|error| error.to_string())?.success() {
        Ok(())
    } else {
        Err("无法写入剪贴板".to_string())
    }
}

#[tauri::command]
fn quick_service_url() -> String {
    service_url().trim_end_matches('/').to_string()
}

#[tauri::command]
fn quick_current_url() -> String {
    LAST_CONTEXT_URL
        .lock()
        .map(|value| value.clone())
        .unwrap_or_default()
}

#[tauri::command]
fn hide_quick_actions(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(QUICK_ACTIONS_LABEL) {
        window.hide().map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn setup_quick_actions_tray(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(
        app,
        QUICK_ACTIONS_MENU_ID,
        "创作助手",
        true,
        Some("Alt+Cmd+M"),
    )?;
    let menu = Menu::with_items(app, &[&open])?;
    let mut tray = TrayIconBuilder::with_id("minem-quick-actions")
        .menu(&menu)
        .tooltip("MineM 创作助手")
        .on_menu_event(|app, event| {
            if event.id().as_ref() == QUICK_ACTIONS_MENU_ID {
                let _ = show_quick_actions(app);
            }
        });
    if let Some(icon) = app.default_window_icon().cloned() {
        tray = tray.icon(icon).icon_as_template(true);
    }
    tray.build(app)?;
    Ok(())
}

fn tab_bridge_target(url: &Url) -> Option<Url> {
    if !is_minem_url(url) || url.path() != TAB_BRIDGE_PATH {
        return None;
    }
    url.query_pairs()
        .find(|(key, _)| key == "url")
        .and_then(|(_, target)| target.parse::<Url>().ok())
}

fn build_tab(
    app: &tauri::AppHandle,
    target: Url,
    features: Option<tauri::webview::NewWindowFeatures>,
) -> tauri::Result<tauri::WebviewWindow> {
    remember_context_url(&target);
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

fn handle_navigation(app: &tauri::AppHandle, target: &Url) -> bool {
    if let Some(tab_target) = tab_bridge_target(target) {
        if is_minem_url(&tab_target) {
            if let Ok(window) = build_tab(app, tab_target, None) {
                let _ = window.set_focus();
            }
        } else {
            open_in_system_browser(&tab_target);
        }
        return false;
    }

    if is_minem_url(target) {
        remember_context_url(target);
        true
    } else {
        open_in_system_browser(target);
        false
    }
}

fn healthcheck() -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(
        &format!("{SERVICE_HOST}:{SERVICE_PORT}")
            .parse()
            .expect("valid loopback address"),
        Duration::from_millis(300),
    ) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    if stream
        .write_all(b"GET /api/stats HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = [0_u8; 64];
    stream
        .read(&mut response)
        .map(|count| String::from_utf8_lossy(&response[..count]).contains(" 200 "))
        .unwrap_or(false)
}

fn wait_for_service(child: &mut Child) -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(20);
    while Instant::now() < deadline {
        if healthcheck() {
            return Ok(());
        }
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!("MineM 本机服务启动失败，退出状态：{status}"));
        }
        thread::sleep(Duration::from_millis(250));
    }
    Err("MineM 本机服务启动超时，请退出客户端后重试".to_string())
}

fn bundled_server_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let resources = app
        .path()
        .resource_dir()
        .map_err(|error| error.to_string())?;
    let candidates = [
        resources.join("minem-server"),
        resources.join("../MacOS/minem-server"),
        resources.join("../Resources/minem-server"),
    ];
    candidates
        .into_iter()
        .find(|path| path.exists())
        .ok_or_else(|| "找不到 MineM 本机服务组件，请重新安装客户端".to_string())
}

fn start_service(app: &tauri::AppHandle) -> Result<Child, String> {
    let data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|error| error.to_string())?;
    let mut command = if cfg!(debug_assertions) {
        let root = project_root();
        let python = env::var("MINEM_DESKTOP_PYTHON").unwrap_or_else(|_| "python3".to_string());
        let mut command = Command::new(python);
        command.arg(root.join("server.py")).current_dir(root);
        command
    } else {
        Command::new(bundled_server_path(app)?)
    };

    command
        .env("HOST", SERVICE_HOST)
        .env("PORT", SERVICE_PORT.to_string())
        .env("AUTO_IMPORT_ON_START", "0")
        .env("MINEM_DATA_DIR", data_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("无法启动 MineM 本机服务：{error}"))
}

fn open_window(app: &tauri::AppHandle, url: WebviewUrl) -> tauri::Result<()> {
    let navigation_app = app.clone();
    let new_window_app = app.clone();
    WebviewWindowBuilder::new(app, "main", url)
        .title("MineM")
        .inner_size(1440.0, 920.0)
        .min_inner_size(1080.0, 720.0)
        .tabbing_identifier(TAB_GROUP)
        .initialization_script(LINK_BRIDGE_SCRIPT)
        .on_navigation(move |target| handle_navigation(&navigation_app, target))
        .on_new_window(move |target, features| {
            if !is_minem_url(&target) {
                open_in_system_browser(&target);
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
    Ok(())
}

fn main() {
    let quick_shortcut = Shortcut::new(Some(Modifiers::ALT | Modifiers::SUPER), Code::KeyM);
    let handler_shortcut = quick_shortcut.clone();
    tauri::Builder::default()
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |app, shortcut, event| {
                    if shortcut == &handler_shortcut && event.state() == ShortcutState::Pressed {
                        let _ = show_quick_actions(app);
                    }
                })
                .build(),
        )
        .manage(ServiceState {
            child: Mutex::new(None),
        })
        .setup(move |app| {
            if let Err(error) = app.global_shortcut().register(quick_shortcut.clone()) {
                eprintln!("无法注册 MineM 创作助手快捷键：{error}");
            }
            if let Ok(url) = service_url().parse::<Url>() {
                remember_context_url(&url);
            }
            if healthcheck() {
                open_window(
                    app.handle(),
                    service_webview_url().map_err(std::io::Error::other)?,
                )?;
            } else {
                match start_service(app.handle()).and_then(|mut child| {
                    wait_for_service(&mut child)?;
                    *app.state::<ServiceState>()
                        .child
                        .lock()
                        .expect("service lock") = Some(child);
                    Ok(())
                }) {
                    Ok(()) => open_window(
                        app.handle(),
                        service_webview_url().map_err(std::io::Error::other)?,
                    )?,
                    Err(error) => {
                        eprintln!("{error}");
                        open_window(app.handle(), WebviewUrl::App("index.html".into()))?;
                    }
                }
            }
            setup_quick_actions_tray(app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            quick_clipboard_read,
            quick_clipboard_write,
            quick_service_url,
            quick_current_url,
            hide_quick_actions,
        ])
        .build(tauri::generate_context!())
        .expect("error while building MineM desktop client")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(mut child) = app
                    .state::<ServiceState>()
                    .child
                    .lock()
                    .expect("service lock")
                    .take()
                {
                    let _ = child.kill();
                }
            }
        });
}
