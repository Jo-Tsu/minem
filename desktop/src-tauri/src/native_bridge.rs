use std::{
    env, fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
};

use objc2::rc::autoreleasepool;
use objc2_app_kit::{NSPasteboard, NSPasteboardTypeString};
use objc2_foundation::NSString;
use tauri::AppHandle;

use crate::desktop_runtime::bundled_server_path;

fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

fn bundled_cli_path(app: &AppHandle) -> Result<PathBuf, String> {
    bundled_server_path(app)
        .map_err(|_| "当前客户端没有包含 MineM CLI，请重新安装客户端".to_string())
}

fn cli_launcher(app: &AppHandle) -> Result<String, String> {
    let cli = bundled_cli_path(app)?
        .canonicalize()
        .map_err(|error| format!("无法读取 MineM CLI：{error}"))?;
    Ok(format!(
        "#!/bin/sh\napp_cli='/Applications/MineM.app/Contents/Resources/sidecar/minem-server'\nif [ -x \"$app_cli\" ]; then\n  exec \"$app_cli\" --cli \"$@\"\nfi\nexec {} --cli \"$@\"\n",
        shell_quote(&cli.to_string_lossy())
    ))
}

fn user_cli_path() -> Result<PathBuf, String> {
    env::var_os("HOME")
        .map(|home| PathBuf::from(home).join(".local/bin/minem"))
        .ok_or_else(|| "无法读取当前用户目录".to_string())
}

pub fn ensure_user_cli_tool(app: &AppHandle) -> Result<PathBuf, String> {
    let destination = user_cli_path()?;
    let parent = destination
        .parent()
        .ok_or_else(|| "MineM CLI 用户目录无效".to_string())?;
    fs::create_dir_all(parent).map_err(|error| format!("无法创建 MineM CLI 用户目录：{error}"))?;
    fs::write(&destination, cli_launcher(app)?)
        .map_err(|error| format!("无法写入 MineM CLI 用户入口：{error}"))?;
    fs::set_permissions(&destination, fs::Permissions::from_mode(0o755))
        .map_err(|error| format!("无法设置 MineM CLI 执行权限：{error}"))?;
    Ok(destination)
}

fn executable(path: &Path) -> bool {
    path.metadata()
        .map(|metadata| metadata.is_file() && metadata.permissions().mode() & 0o111 != 0)
        .unwrap_or(false)
}

fn installed_cli_path() -> Option<PathBuf> {
    let mut candidates = Vec::with_capacity(3);
    if let Ok(user_path) = user_cli_path() {
        candidates.push(user_path);
    }
    candidates.push(PathBuf::from("/opt/homebrew/bin/minem"));
    candidates.push(PathBuf::from("/usr/local/bin/minem"));
    candidates.into_iter().find(|path| executable(path))
}

fn normalize_clipboard_text(text: &str) -> String {
    text.replace("\r\n", "\n").replace('\r', "\n")
}

fn string_type() -> &'static NSString {
    // SAFETY: AppKit exposes NSPasteboardTypeString as a process-lifetime constant.
    unsafe { NSPasteboardTypeString }
}

fn read_clipboard() -> Result<String, String> {
    autoreleasepool(|_| {
        let pasteboard = NSPasteboard::generalPasteboard();
        Ok(pasteboard
            .stringForType(string_type())
            .map(|value| value.to_string())
            .unwrap_or_default())
    })
}

fn write_clipboard(text: &str) -> Result<(), String> {
    autoreleasepool(|_| {
        let pasteboard = NSPasteboard::generalPasteboard();
        pasteboard.clearContents();
        let value = NSString::from_str(text);
        if !pasteboard.setString_forType(&value, string_type()) {
            return Err("macOS 拒绝写入系统剪贴板".to_string());
        }
        let written = pasteboard
            .stringForType(string_type())
            .map(|value| value.to_string())
            .unwrap_or_default();
        if normalize_clipboard_text(&written) != normalize_clipboard_text(text) {
            return Err("系统剪贴板没有保存完整指令".to_string());
        }
        Ok(())
    })
}

#[tauri::command]
pub async fn clipboard_read() -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(read_clipboard)
        .await
        .map_err(|error| format!("剪贴板读取任务异常：{error}"))?
}

#[tauri::command]
pub async fn clipboard_write(text: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || write_clipboard(&text))
        .await
        .map_err(|error| format!("剪贴板写入任务异常：{error}"))?
}

#[tauri::command]
pub fn cli_tool_path() -> Option<String> {
    installed_cli_path().map(|path| path.to_string_lossy().to_string())
}

#[tauri::command]
pub async fn install_cli_tool(app: AppHandle) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || ensure_user_cli_tool(&app))
        .await
        .map_err(|error| format!("CLI 安装任务异常：{error}"))?
        .map(|path| path.to_string_lossy().to_string())
}

#[cfg(test)]
mod tests {
    use super::normalize_clipboard_text;

    #[test]
    fn clipboard_comparison_normalizes_platform_line_endings() {
        assert_eq!(
            normalize_clipboard_text("第一行\r\n第二行\r第三行"),
            "第一行\n第二行\n第三行"
        );
    }
}
