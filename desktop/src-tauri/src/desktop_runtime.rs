use std::{
    env,
    fs::{self, OpenOptions},
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    os::unix::process::CommandExt,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicU16, Ordering},
        Mutex,
    },
    thread,
    time::{Duration, Instant},
};

use tauri::{AppHandle, Manager};
use url::Url;

use crate::bootstrap::{
    mark_service_stopped, read_service_manifest, write_service_manifest, BootstrapSession,
    RuntimePaths, ServiceManifest,
};

const SERVICE_HOST: &str = "127.0.0.1";
const DEFAULT_SERVICE_PORT: u16 = 8790;
static ACTIVE_SERVICE_PORT: AtomicU16 = AtomicU16::new(DEFAULT_SERVICE_PORT);

struct ServiceRuntime {
    child: Option<Child>,
    paths: RuntimePaths,
    process_group_id: Option<u32>,
}

pub struct ServiceState {
    runtime: Mutex<Option<ServiceRuntime>>,
}

impl ServiceState {
    pub fn empty() -> Self {
        Self {
            runtime: Mutex::new(None),
        }
    }
}

pub fn data_root(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(path) = env::var("MINEM_DATA_DIR") {
        if !path.trim().is_empty() {
            return Ok(expand_tilde(PathBuf::from(path)));
        }
    }
    if let Ok(home) = env::var("HOME") {
        return Ok(PathBuf::from(home).join("Library/Application Support/MineM"));
    }
    app.path()
        .app_local_data_dir()
        .map_err(|error| error.to_string())
}

fn expand_tilde(path: PathBuf) -> PathBuf {
    let Some(value) = path.to_str() else {
        return path;
    };
    if value == "~" {
        return env::var("HOME").map(PathBuf::from).unwrap_or(path);
    }
    if let Some(rest) = value.strip_prefix("~/") {
        if let Ok(home) = env::var("HOME") {
            return PathBuf::from(home).join(rest);
        }
    }
    path
}

pub fn current_port() -> u16 {
    ACTIVE_SERVICE_PORT.load(Ordering::Relaxed)
}

pub fn service_url() -> String {
    format!("http://{SERVICE_HOST}:{}/", current_port())
}

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("MineM project root must exist")
}

fn healthcheck(port: u16) -> bool {
    let Ok(address) = format!("{SERVICE_HOST}:{port}").parse() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(300)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    if stream
        .write_all(b"GET /api/version HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = Vec::with_capacity(4096);
    let _ = stream.take(16 * 1024).read_to_end(&mut response);
    let response = String::from_utf8_lossy(&response);
    response.contains(" 200 ") && response.contains("\"product\"") && response.contains("MineM")
}

fn log_summary(content: &str) -> Option<String> {
    const MAX_LINES: usize = 4;
    const MAX_CHARS: usize = 900;

    let lines = content
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect::<Vec<_>>();
    if lines.is_empty() {
        return None;
    }
    let summary = lines[lines.len().saturating_sub(MAX_LINES)..].join(" | ");
    let char_count = summary.chars().count();
    if char_count <= MAX_CHARS {
        return Some(summary);
    }
    Some(format!(
        "…{}",
        summary
            .chars()
            .skip(char_count.saturating_sub(MAX_CHARS))
            .collect::<String>()
    ))
}

fn startup_failure_message(status: &str, stderr_log: &Path) -> String {
    let detail = fs::read_to_string(stderr_log)
        .ok()
        .and_then(|content| log_summary(&content));
    match detail {
        Some(detail) => format!("MineM 本机服务启动失败（{status}）：{detail}"),
        None => format!("MineM 本机服务启动失败，退出状态：{status}"),
    }
}

fn startup_timeout() -> Duration {
    // A cold PyInstaller start on a slow disk or a first-run Gatekeeper scan can
    // exceed a tight fixed budget, surfacing a false "启动超时". Keep a generous
    // default and let operators tune it. A genuine crash still returns early via
    // the child.try_wait() check below, so a larger cap does not slow real
    // failures.
    let secs = env::var("MINEM_STARTUP_TIMEOUT_SECS")
        .ok()
        .and_then(|value| value.trim().parse::<u64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(60);
    Duration::from_secs(secs)
}

fn wait_for_service(child: &mut Child, port: u16, stderr_log: &Path) -> Result<(), String> {
    let deadline = Instant::now() + startup_timeout();
    while Instant::now() < deadline {
        if healthcheck(port) {
            return Ok(());
        }
        if let Ok(Some(status)) = child.try_wait() {
            return Err(startup_failure_message(&status.to_string(), stderr_log));
        }
        thread::sleep(Duration::from_millis(250));
    }
    let detail = fs::read_to_string(stderr_log)
        .ok()
        .and_then(|content| log_summary(&content));
    Err(detail.map_or_else(
        || "MineM 本机服务启动超时，请退出客户端后重试".to_string(),
        |detail| format!("MineM 本机服务启动超时：{detail}"),
    ))
}

fn signal_process_group(process_group_id: u32, signal: &str) -> bool {
    Command::new("/bin/kill")
        .args([signal, &format!("-{process_group_id}")])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok_and(|status| status.success())
}

fn process_group_exists(process_group_id: u32) -> bool {
    signal_process_group(process_group_id, "-0")
}

fn terminate_process_group(process_group_id: u32) {
    signal_process_group(process_group_id, "-TERM");
    let deadline = Instant::now() + Duration::from_secs(2);
    while process_group_exists(process_group_id) && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(50));
    }
    if process_group_exists(process_group_id) {
        signal_process_group(process_group_id, "-KILL");
        let deadline = Instant::now() + Duration::from_secs(1);
        while process_group_exists(process_group_id) && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(50));
        }
    }
}

fn terminate_service(child: &mut Child) {
    let process_group_id = child.id();
    terminate_process_group(process_group_id);
    let _ = child.wait();
}

#[derive(Debug, PartialEq, Eq)]
enum ExistingServiceAction {
    Reuse(u16),
    Replace { port: u16, process_group_id: u32 },
    ClearStale,
    Ignore,
    Block(String),
}

fn existing_service_action(
    manifest: &ServiceManifest,
    app_version: &str,
    healthy: bool,
    process_group_alive: bool,
) -> ExistingServiceAction {
    if manifest.status != "running" || !manifest.managed_by_client {
        return ExistingServiceAction::Ignore;
    }
    if manifest.app_version == app_version && healthy && process_group_alive {
        return ExistingServiceAction::Reuse(manifest.port);
    }
    if let (true, Some(process_group_id)) = (process_group_alive, manifest.pid) {
        return ExistingServiceAction::Replace {
            port: manifest.port,
            process_group_id,
        };
    }
    if healthy {
        return ExistingServiceAction::Block(
            "检测到旧版 MineM 服务仍在运行，但缺少可验证的托管进程信息。请退出旧版 MineM 后重试"
                .to_string(),
        );
    }
    ExistingServiceAction::ClearStale
}

fn available_service_port(paths: &RuntimePaths, app_version: &str) -> Result<(u16, bool), String> {
    if let Some(manifest) = read_service_manifest(paths) {
        let healthy = healthcheck(manifest.port);
        let process_group_alive = manifest.pid.is_some_and(process_group_exists);
        match existing_service_action(&manifest, app_version, healthy, process_group_alive) {
            ExistingServiceAction::Reuse(port) => return Ok((port, true)),
            ExistingServiceAction::Replace {
                port,
                process_group_id,
            } => {
                // A packaged upgrade may inherit an orphaned Sidecar from the previous app.
                // Only the process group recorded as client-managed is eligible for takeover.
                terminate_process_group(process_group_id);
                let deadline = Instant::now() + Duration::from_secs(3);
                while healthcheck(port) && Instant::now() < deadline {
                    thread::sleep(Duration::from_millis(100));
                }
                if healthcheck(port) || process_group_exists(process_group_id) {
                    return Err(
                        "旧版 MineM 本机服务未能安全退出，请退出旧版客户端后重试".to_string()
                    );
                }
                mark_service_stopped(paths);
            }
            ExistingServiceAction::ClearStale => mark_service_stopped(paths),
            ExistingServiceAction::Block(error) => return Err(error),
            ExistingServiceAction::Ignore => {}
        }
    }
    if TcpListener::bind((SERVICE_HOST, DEFAULT_SERVICE_PORT)).is_ok() {
        return Ok((DEFAULT_SERVICE_PORT, false));
    }
    let listener = TcpListener::bind((SERVICE_HOST, 0))
        .map_err(|error| format!("无法为 MineM 分配本机端口：{error}"))?;
    let port = listener
        .local_addr()
        .map_err(|error| format!("无法读取 MineM 本机端口：{error}"))?
        .port();
    Ok((port, false))
}

fn server_candidates(executable: Option<&Path>, resources: Option<&Path>) -> Vec<PathBuf> {
    let mut candidates = Vec::with_capacity(6);
    if let Some(directory) = executable.and_then(Path::parent) {
        candidates.push(directory.join("sidecar/minem-server"));
        candidates.push(directory.join("minem-server"));
    }
    if let Some(resources) = resources {
        candidates.push(resources.join("sidecar/minem-server"));
        candidates.push(resources.join("minem-server"));
        candidates.push(resources.join("../MacOS/sidecar/minem-server"));
        candidates.push(resources.join("../MacOS/minem-server"));
    }
    candidates
}

pub fn bundled_server_path(app: &AppHandle) -> Result<PathBuf, String> {
    let executable = env::current_exe().ok();
    let resources = app.path().resource_dir().ok();
    server_candidates(executable.as_deref(), resources.as_deref())
        .into_iter()
        .find(|path| path.is_file())
        .ok_or_else(|| "找不到 MineM 本机服务组件，请重新安装客户端".to_string())
}

fn verify_bundle(app: &AppHandle) -> Result<(), String> {
    if cfg!(debug_assertions) {
        for required in [
            project_root().join("server.py"),
            project_root().join("public/index.html"),
        ] {
            if !required.is_file() {
                return Err(format!("MineM 开发运行文件缺失：{}", required.display()));
            }
        }
        Ok(())
    } else {
        bundled_server_path(app).map(|_| ())
    }
}

fn rotate_log(path: &Path) -> Result<fs::File, String> {
    if path.exists() {
        let old = path.with_extension("log.old");
        let _ = fs::remove_file(&old);
        let _ = fs::rename(path, old);
    }
    OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(path)
        .map_err(|error| format!("无法打开 MineM 服务日志：{error}"))
}

fn desktop_executable_for_server(current_executable: Option<&Path>) -> Option<PathBuf> {
    current_executable
        .filter(|path| !path.as_os_str().is_empty())
        .map(PathBuf::from)
}

fn start_service(app: &AppHandle, paths: &RuntimePaths, port: u16) -> Result<Child, String> {
    let mut command = if cfg!(debug_assertions) {
        let root = project_root();
        let python = env::var("MINEM_DESKTOP_PYTHON").unwrap_or_else(|_| "python3".to_string());
        let mut command = Command::new(python);
        command.arg(root.join("server.py")).current_dir(root);
        command
    } else {
        Command::new(bundled_server_path(app)?)
    };
    let stdout = rotate_log(&paths.logs.join("minem-server.stdout.log"))?;
    let stderr = rotate_log(&paths.logs.join("minem-server.stderr.log"))?;
    let desktop_executable = env::current_exe().ok();

    command
        .env("HOST", SERVICE_HOST)
        .env("PORT", port.to_string())
        .env("AUTO_IMPORT_ON_START", "0")
        .env("MINEM_DATA_DIR", &paths.root)
        .env("MINEM_PARENT_PID", std::process::id().to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .process_group(0);

    // The service must re-open the exact app that started it. A hard-coded
    // /Applications path fails for customers who launch MineM from a DMG,
    // Downloads, or another managed installation location.
    if let Some(executable) = desktop_executable_for_server(desktop_executable.as_deref()) {
        command.env("MINEM_DESKTOP_EXECUTABLE", executable);
    }

    command
        .spawn()
        .map_err(|error| format!("无法启动 MineM 本机服务：{error}"))
}

pub fn initialize(app: &AppHandle, app_version: &str) -> Result<Url, String> {
    let paths = RuntimePaths::new(data_root(app)?);
    let mut bootstrap = BootstrapSession::begin(paths.clone(), app_version)?;
    let result = (|| {
        bootstrap.prepare_directories()?;
        bootstrap.start_step("verifying_bundle")?;
        verify_bundle(app)?;
        bootstrap.complete_step("verifying_bundle")?;
        bootstrap.mark_service_pending()?;

        let (port, reuse_existing) = available_service_port(&paths, app_version)?;
        ACTIVE_SERVICE_PORT.store(port, Ordering::Relaxed);
        let mut child = if reuse_existing {
            None
        } else {
            let mut child = start_service(app, &paths, port)?;
            let stderr_log = paths.logs.join("minem-server.stderr.log");
            if let Err(error) = wait_for_service(&mut child, port, &stderr_log) {
                terminate_service(&mut child);
                return Err(error);
            }
            Some(child)
        };
        if !healthcheck(port) {
            if let Some(process) = child.as_mut() {
                terminate_service(process);
            }
            return Err("MineM 本机服务健康检查未通过".to_string());
        }

        let previous_pid = reuse_existing
            .then(|| read_service_manifest(&paths).and_then(|manifest| manifest.pid))
            .flatten();
        let process_group_id = child.as_ref().map(Child::id).or(previous_pid);
        write_service_manifest(
            &paths,
            &ServiceManifest::running(app_version, port, process_group_id, true),
        )?;
        bootstrap.mark_ready()?;

        *app.state::<ServiceState>()
            .runtime
            .lock()
            .map_err(|_| "MineM 服务状态锁不可用".to_string())? = Some(ServiceRuntime {
            child,
            paths,
            process_group_id,
        });
        service_url()
            .parse::<Url>()
            .map_err(|error| error.to_string())
    })();
    if let Err(error) = &result {
        bootstrap.mark_failed(error);
    }
    result
}

pub fn shutdown(app: &AppHandle) {
    let Some(mut runtime) = app
        .state::<ServiceState>()
        .runtime
        .lock()
        .ok()
        .and_then(|mut runtime| runtime.take())
    else {
        return;
    };
    if let Some(child) = runtime.child.as_mut() {
        terminate_service(child);
    } else if let Some(process_group_id) = runtime.process_group_id {
        terminate_process_group(process_group_id);
    }
    mark_service_stopped(&runtime.paths);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn managed_manifest(version: &str, pid: Option<u32>) -> ServiceManifest {
        ServiceManifest::running(version, 62049, pid, true)
    }

    #[test]
    fn packaged_sidecar_prefers_onedir_resource() {
        let executable = Path::new("/Applications/MineM.app/Contents/MacOS/minem-desktop");
        let resources = Path::new("/Applications/MineM.app/Contents/Resources");
        let candidates = server_candidates(Some(executable), Some(resources));
        assert!(candidates.contains(&resources.join("sidecar/minem-server")));
        assert!(
            candidates
                .iter()
                .position(|path| path == &resources.join("sidecar/minem-server"))
                < candidates
                    .iter()
                    .position(|path| path == &resources.join("minem-server"))
        );
    }

    #[test]
    fn server_uses_the_actual_desktop_executable_path() {
        let executable = Path::new("/Volumes/MineM/MineM.app/Contents/MacOS/minem-desktop");
        assert_eq!(
            desktop_executable_for_server(Some(executable)),
            Some(executable.to_path_buf())
        );
    }

    #[test]
    fn same_version_healthy_service_is_reused() {
        let manifest = managed_manifest("0.5.0-alpha.14", Some(101));
        assert_eq!(
            existing_service_action(&manifest, "0.5.0-alpha.14", true, true),
            ExistingServiceAction::Reuse(62049)
        );
    }

    #[test]
    fn older_managed_service_is_replaced_during_upgrade() {
        let manifest = managed_manifest("0.5.0-alpha.13", Some(101));
        assert_eq!(
            existing_service_action(&manifest, "0.5.0-alpha.14", true, true),
            ExistingServiceAction::Replace {
                port: 62049,
                process_group_id: 101
            }
        );
    }

    #[test]
    fn unmanaged_service_is_never_replaced() {
        let mut manifest = managed_manifest("0.5.0-alpha.13", Some(101));
        manifest.managed_by_client = false;
        assert_eq!(
            existing_service_action(&manifest, "0.5.0-alpha.14", true, true),
            ExistingServiceAction::Ignore
        );
    }

    #[test]
    fn stale_managed_manifest_is_cleared() {
        let manifest = managed_manifest("0.5.0-alpha.13", Some(101));
        assert_eq!(
            existing_service_action(&manifest, "0.5.0-alpha.14", false, false),
            ExistingServiceAction::ClearStale
        );
    }

    #[test]
    fn startup_error_includes_a_short_log_summary() {
        let summary =
            log_summary("ignored\nfirst\nsecond\nMineM 启动失败：旧版服务仍在使用同一份数据目录\n")
                .unwrap();
        assert!(summary.contains("MineM 启动失败"));
        assert!(summary.contains("旧版服务"));
    }
}
