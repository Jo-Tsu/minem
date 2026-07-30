use std::{fs, process::Command, thread};

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindowBuilder,
};

use crate::{
    desktop_runtime::{data_root, service_url},
    native_bridge::ensure_user_cli_tool,
    navigation,
};

pub const WINDOW_LABEL: &str = "quick-actions";
pub const EXPANDED_WIDTH: f64 = 420.0;
pub const COLLAPSED_SIZE: f64 = 48.0;
const MIN_HEIGHT: f64 = 480.0;
const MAX_HEIGHT: f64 = 520.0;
const MARGIN: f64 = 12.0;
const ONBOARDING_MARKER: &str = "quick-actions-onboarding-v2";

#[derive(Debug, PartialEq)]
struct Layout {
    position: PhysicalPosition<i32>,
    size: PhysicalSize<u32>,
}

fn layout_for_monitor(
    work_position: PhysicalPosition<i32>,
    work_size: PhysicalSize<u32>,
    scale_factor: f64,
    collapsed: bool,
) -> Layout {
    let scale = scale_factor.max(1.0);
    let margin = (MARGIN * scale).round() as i32;
    let available_height = (f64::from(work_size.height) / scale - MARGIN * 2.0).max(320.0);
    let logical_width = if collapsed {
        COLLAPSED_SIZE
    } else {
        EXPANDED_WIDTH
    };
    let logical_height = if collapsed {
        COLLAPSED_SIZE
    } else if available_height < MIN_HEIGHT {
        available_height
    } else {
        available_height.min(MAX_HEIGHT)
    };
    let width = (logical_width * scale).round() as u32;
    let height = (logical_height * scale).round() as u32;
    Layout {
        position: PhysicalPosition::new(
            work_position.x + work_size.width as i32 - width as i32 - margin,
            work_position.y + (work_size.height as i32 - height as i32) / 2,
        ),
        size: PhysicalSize::new(width, height),
    }
}

fn apply_layout(window: &tauri::WebviewWindow, collapsed: bool) -> Result<(), String> {
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .or(window
            .primary_monitor()
            .map_err(|error| error.to_string())?)
        .ok_or_else(|| "无法读取当前屏幕工作区".to_string())?;
    let work_area = monitor.work_area();
    let layout = layout_for_monitor(
        work_area.position,
        work_area.size,
        monitor.scale_factor(),
        collapsed,
    );
    window
        .set_size(layout.size)
        .map_err(|error| error.to_string())?;
    window
        .set_position(layout.position)
        .map_err(|error| error.to_string())
}

fn clamp(value: i32, minimum: i32, maximum: i32) -> i32 {
    value.max(minimum).min(maximum.max(minimum))
}

fn anchored_position(
    work_position: PhysicalPosition<i32>,
    work_size: PhysicalSize<u32>,
    current_position: PhysicalPosition<i32>,
    current_size: PhysicalSize<u32>,
    next_size: PhysicalSize<u32>,
) -> PhysicalPosition<i32> {
    let right = current_position.x + current_size.width as i32;
    let center_y = current_position.y + current_size.height as i32 / 2;
    PhysicalPosition::new(
        clamp(
            right - next_size.width as i32,
            work_position.x,
            work_position.x + work_size.width as i32 - next_size.width as i32,
        ),
        clamp(
            center_y - next_size.height as i32 / 2,
            work_position.y,
            work_position.y + work_size.height as i32 - next_size.height as i32,
        ),
    )
}

fn resize_preserving_position(
    window: &tauri::WebviewWindow,
    collapsed: bool,
) -> Result<(), String> {
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .or(window
            .primary_monitor()
            .map_err(|error| error.to_string())?)
        .ok_or_else(|| "无法读取当前屏幕工作区".to_string())?;
    let work_area = monitor.work_area();
    let next = layout_for_monitor(
        work_area.position,
        work_area.size,
        monitor.scale_factor(),
        collapsed,
    );
    let position = window.outer_position().map_err(|error| error.to_string())?;
    let size = window.outer_size().map_err(|error| error.to_string())?;
    let next_position = anchored_position(
        work_area.position,
        work_area.size,
        position,
        size,
        next.size,
    );
    window
        .set_size(next.size)
        .map_err(|error| error.to_string())?;
    window
        .set_position(next_position)
        .map_err(|error| error.to_string())
}

pub fn show(app: &AppHandle) -> Result<(), String> {
    let (window, created) = if let Some(window) = app.get_webview_window(WINDOW_LABEL) {
        let _ = window.eval("window.setMineMDrawerCollapsed?.(false)");
        (window, false)
    } else {
        let window = WebviewWindowBuilder::new(
            app,
            WINDOW_LABEL,
            WebviewUrl::App("quick-actions.html".into()),
        )
        .title("MineM 创作助手")
        .inner_size(EXPANDED_WIDTH, MAX_HEIGHT)
        .decorations(false)
        .shadow(false)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .visible(false)
        .build()
        .map_err(|error| error.to_string())?;
        (window, true)
    };
    if created {
        apply_layout(&window, false)?;
    } else {
        resize_preserving_position(&window, false)?;
    }
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())
}

pub fn show_onboarding(app: &AppHandle, version: &str) -> Result<(), String> {
    let marker = data_root(app)?.join("state").join(ONBOARDING_MARKER);
    if marker.is_file() {
        return Ok(());
    }
    show(app)?;
    if let Some(parent) = marker.parent() {
        fs::create_dir_all(parent).map_err(|error| format!("无法创建创作助手引导目录：{error}"))?;
    }
    fs::write(marker, version).map_err(|error| format!("无法记录创作助手引导状态：{error}"))
}

#[tauri::command]
pub fn service_base_url() -> String {
    service_url().trim_end_matches('/').to_string()
}

#[tauri::command]
pub fn current_context_url() -> String {
    navigation::current_url()
}

#[tauri::command]
pub fn hide(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(WINDOW_LABEL) {
        window.hide().map_err(|error| error.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub fn set_collapsed(app: AppHandle, collapsed: bool) -> Result<(), String> {
    let window = app
        .get_webview_window(WINDOW_LABEL)
        .ok_or_else(|| "创作助手窗口尚未创建".to_string())?;
    resize_preserving_position(&window, collapsed)?;
    window.show().map_err(|error| error.to_string())?;
    if !collapsed {
        window.set_focus().map_err(|error| error.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub fn start_dragging(app: AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window(WINDOW_LABEL)
        .ok_or_else(|| "创作助手窗口尚未创建".to_string())?;
    window.start_dragging().map_err(|error| error.to_string())
}

fn notify(message: &str) {
    let escaped = message.replace('\\', "\\\\").replace('"', "\\\"");
    let script = format!("display notification \"{escaped}\" with title \"MineM\"");
    let _ = Command::new("/usr/bin/osascript")
        .args(["-e", &script])
        .status();
}

pub fn setup_tray(app: &AppHandle) -> tauri::Result<()> {
    let open_main = MenuItem::with_id(app, "open-main", "打开 MineM", true, None::<&str>)?;
    let open_assistant = MenuItem::with_id(
        app,
        "quick-actions",
        "创作助手（⌥⌘M / ⌃⌥M）",
        true,
        Some("Alt+Cmd+M"),
    )?;
    let install_cli = MenuItem::with_id(app, "install-cli", "修复命令行工具", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出 MineM", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open_main, &open_assistant, &install_cli, &quit])?;
    let mut tray = TrayIconBuilder::with_id("minem")
        .menu(&menu)
        .tooltip("MineM")
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open-main" => navigation::show_main(app),
            "quick-actions" => {
                let _ = show(app);
            }
            "install-cli" => {
                let app = app.clone();
                thread::spawn(move || match ensure_user_cli_tool(&app) {
                    Ok(path) => notify(&format!("命令行工具已修复：{}", path.display())),
                    Err(error) => notify(&error),
                });
            }
            "quit" => app.exit(0),
            _ => {}
        });
    if let Some(icon) = app.default_window_icon().cloned() {
        tray = tray.icon(icon);
    }
    tray.build(app)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn drawer_is_right_aligned_on_retina_displays() {
        let layout = layout_for_monitor(
            PhysicalPosition::new(0, 48),
            PhysicalSize::new(3024, 1876),
            2.0,
            false,
        );
        assert_eq!(layout.size, PhysicalSize::new(840, 1040));
        assert_eq!(layout.position, PhysicalPosition::new(2160, 466));
    }

    #[test]
    fn drawer_collapses_to_a_compact_right_edge_button() {
        let layout = layout_for_monitor(
            PhysicalPosition::new(-1920, 0),
            PhysicalSize::new(1920, 1080),
            1.0,
            true,
        );
        assert_eq!(layout.size, PhysicalSize::new(48, 48));
        assert_eq!(layout.position, PhysicalPosition::new(-60, 516));
    }

    #[test]
    fn resizing_keeps_the_dragged_window_anchor_inside_the_work_area() {
        let position = anchored_position(
            PhysicalPosition::new(0, 24),
            PhysicalSize::new(1440, 876),
            PhysicalPosition::new(540, 140),
            PhysicalSize::new(420, 520),
            PhysicalSize::new(48, 48),
        );
        assert_eq!(position, PhysicalPosition::new(912, 376));

        let clamped = anchored_position(
            PhysicalPosition::new(0, 24),
            PhysicalSize::new(1440, 876),
            PhysicalPosition::new(10, 30),
            PhysicalSize::new(48, 48),
            PhysicalSize::new(420, 520),
        );
        assert_eq!(clamped, PhysicalPosition::new(0, 24));
    }
}
