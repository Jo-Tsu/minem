mod bootstrap;
mod desktop_runtime;
mod native_bridge;
mod navigation;
mod quick_actions;

use std::{env, thread};

use tauri::{AppHandle, Manager, WebviewUrl};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

use desktop_runtime::{
    initialize as initialize_runtime, shutdown as shutdown_runtime, ServiceState,
};

const APP_VERSION: &str = env!("CARGO_PKG_VERSION");

fn requests_assistant(arguments: impl IntoIterator<Item = impl AsRef<str>>) -> bool {
    arguments.into_iter().any(|argument| {
        matches!(
            argument.as_ref(),
            "--assistant" | "--creator-assistant" | "minem://assistant"
        )
    })
}

fn restore_main_window_on_reopen(_has_visible_windows: bool) -> bool {
    true
}

fn should_restore_main_window(event: &tauri::RunEvent) -> bool {
    match event {
        tauri::RunEvent::Reopen {
            has_visible_windows,
            ..
        } => restore_main_window_on_reopen(*has_visible_windows),
        _ => false,
    }
}

fn navigate_to_service(app: &AppHandle, url: url::Url) {
    navigation::remember(&url);
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.navigate(url);
    }
}

fn initialize_in_background(app: AppHandle) {
    thread::spawn(move || match initialize_runtime(&app, APP_VERSION) {
        Ok(url) => {
            navigate_to_service(&app, url);
            if let Err(error) = quick_actions::show_onboarding(&app, APP_VERSION) {
                eprintln!("无法显示 MineM 创作助手首次引导：{error}");
            }
        }
        Err(error) => {
            eprintln!("{error}");
            if let Some(window) = app.get_webview_window("main") {
                let message = serde_json::to_string(&error)
                    .unwrap_or_else(|_| "\"本机服务启动失败\"".to_string());
                let _ = window.eval(format!("window.setMineMBootState?.('failed', {message})"));
            }
        }
    });
}

#[tauri::command]
async fn retry_runtime(app: AppHandle) -> Result<String, String> {
    let runtime_app = app.clone();
    let url =
        tauri::async_runtime::spawn_blocking(move || initialize_runtime(&runtime_app, APP_VERSION))
            .await
            .map_err(|error| format!("MineM 重试任务异常：{error}"))??;
    navigation::remember(&url);
    Ok(url.to_string())
}

fn main() {
    let shortcuts = [
        Shortcut::new(Some(Modifiers::ALT | Modifiers::SUPER), Code::KeyM),
        Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyM),
    ];
    let handler_shortcuts = shortcuts.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            if requests_assistant(&argv) {
                let _ = quick_actions::show(app);
            } else {
                navigation::show_main(app);
            }
        }))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |app, shortcut, event| {
                    if handler_shortcuts.contains(shortcut)
                        && event.state() == ShortcutState::Pressed
                    {
                        let _ = quick_actions::show(app);
                    }
                })
                .build(),
        )
        .manage(ServiceState::empty())
        .invoke_handler(tauri::generate_handler![
            retry_runtime,
            native_bridge::clipboard_read,
            native_bridge::clipboard_write,
            native_bridge::cli_tool_path,
            native_bridge::install_cli_tool,
            quick_actions::service_base_url,
            quick_actions::current_context_url,
            quick_actions::hide,
            quick_actions::set_collapsed,
            quick_actions::start_dragging,
        ])
        .setup(move |app| {
            for shortcut in shortcuts.iter().cloned() {
                if let Err(error) = app.global_shortcut().register(shortcut.clone()) {
                    eprintln!("无法注册 MineM 创作助手快捷键 {shortcut}：{error}");
                }
            }
            if let Err(error) = native_bridge::ensure_user_cli_tool(app.handle()) {
                eprintln!("无法初始化 MineM CLI 用户入口：{error}");
            }
            navigation::open_main_window(app.handle(), WebviewUrl::App("index.html".into()))?;
            quick_actions::setup_tray(app.handle())?;
            if requests_assistant(env::args()) {
                quick_actions::show(app.handle())?;
            }
            initialize_in_background(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building MineM desktop client")
        .run(|app, event| {
            if should_restore_main_window(&event) {
                navigation::show_main(app);
            } else if matches!(
                event,
                tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
            ) {
                shutdown_runtime(app);
            }
        });
}

#[cfg(test)]
mod tests {
    use super::{requests_assistant, restore_main_window_on_reopen};

    #[test]
    fn assistant_can_be_opened_by_launch_argument() {
        assert!(requests_assistant(["MineM", "--assistant"]));
        assert!(requests_assistant(["minem://assistant"]));
        assert!(!requests_assistant(["MineM"]));
    }

    #[test]
    fn dock_reopen_restores_the_existing_main_window() {
        assert!(restore_main_window_on_reopen(false));
        assert!(restore_main_window_on_reopen(true));
    }
}
