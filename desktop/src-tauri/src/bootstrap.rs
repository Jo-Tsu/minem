use std::{
    fs::{self, File, OpenOptions},
    io::{ErrorKind, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use fs2::FileExt;
use serde::{Deserialize, Serialize};

pub const BOOTSTRAP_SCHEMA_VERSION: u32 = 1;
pub const SERVICE_MANIFEST_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug)]
pub struct RuntimePaths {
    pub root: PathBuf,
    pub config: PathBuf,
    pub data: PathBuf,
    pub uploads: PathBuf,
    pub extracted: PathBuf,
    pub thumbnails: PathBuf,
    pub report_exports: PathBuf,
    pub packs: PathBuf,
    pub runtime: PathBuf,
    pub locks: PathBuf,
    pub staging: PathBuf,
    pub logs: PathBuf,
}

impl RuntimePaths {
    pub fn new(root: PathBuf) -> Self {
        Self {
            config: root.join("config"),
            data: root.join("data"),
            uploads: root.join("uploads"),
            extracted: root.join("extracted"),
            thumbnails: root.join("thumbnails"),
            report_exports: root.join("report-exports"),
            packs: root.join("packs"),
            runtime: root.join("runtime"),
            locks: root.join("runtime/locks"),
            staging: root.join("runtime/staging"),
            logs: root.join("logs"),
            root,
        }
    }

    pub fn bootstrap_state(&self) -> PathBuf {
        self.runtime.join("bootstrap-state.json")
    }

    pub fn service_manifest(&self) -> PathBuf {
        self.runtime.join("service.json")
    }

    fn required_directories(&self) -> [&Path; 12] {
        [
            &self.root,
            &self.config,
            &self.data,
            &self.uploads,
            &self.extracted,
            &self.thumbnails,
            &self.report_exports,
            &self.packs,
            &self.runtime,
            &self.locks,
            &self.staging,
            &self.logs,
        ]
    }

    pub fn ensure_layout(&self) -> Result<(), String> {
        for directory in self.required_directories() {
            fs::create_dir_all(directory).map_err(|error| {
                format!("无法创建 MineM 数据目录 {}：{error}", directory.display())
            })?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum BootstrapStatus {
    Running,
    ServicePending,
    Ready,
    Failed,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BootstrapState {
    pub schema_version: u32,
    pub app_version: String,
    pub status: BootstrapStatus,
    pub current_step: Option<String>,
    pub completed_steps: Vec<String>,
    pub error: Option<String>,
    pub updated_at_ms: u128,
}

impl BootstrapState {
    fn new(app_version: &str) -> Self {
        Self {
            schema_version: BOOTSTRAP_SCHEMA_VERSION,
            app_version: app_version.to_string(),
            status: BootstrapStatus::Running,
            current_step: None,
            completed_steps: Vec::new(),
            error: None,
            updated_at_ms: now_ms(),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ServiceManifest {
    pub schema_version: u32,
    pub app_version: String,
    pub base_url: String,
    pub port: u16,
    pub pid: Option<u32>,
    pub managed_by_client: bool,
    pub status: String,
    pub updated_at_ms: u128,
}

impl ServiceManifest {
    pub fn running(app_version: &str, port: u16, pid: Option<u32>, managed: bool) -> Self {
        Self {
            schema_version: SERVICE_MANIFEST_SCHEMA_VERSION,
            app_version: app_version.to_string(),
            base_url: format!("http://127.0.0.1:{port}"),
            port,
            pid,
            managed_by_client: managed,
            status: "running".to_string(),
            updated_at_ms: now_ms(),
        }
    }
}

pub struct BootstrapSession {
    pub paths: RuntimePaths,
    pub state: BootstrapState,
    lock_file: File,
}

impl BootstrapSession {
    pub fn begin(paths: RuntimePaths, app_version: &str) -> Result<Self, String> {
        fs::create_dir_all(&paths.locks)
            .map_err(|error| format!("无法准备 MineM 初始化锁：{error}"))?;
        let lock_path = paths.locks.join("bootstrap.lock");
        let lock_file = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|error| format!("无法打开 MineM 初始化锁：{error}"))?;
        lock_file
            .try_lock_exclusive()
            .map_err(|_| "MineM 正在由另一个客户端窗口初始化，请稍后重试".to_string())?;

        let mut state = load_json::<BootstrapState>(&paths.bootstrap_state())
            .unwrap_or_else(|| BootstrapState::new(app_version));
        if state.schema_version != BOOTSTRAP_SCHEMA_VERSION || state.app_version != app_version {
            state = BootstrapState::new(app_version);
        } else {
            state.status = BootstrapStatus::Running;
            state.current_step = None;
            state.error = None;
            state.updated_at_ms = now_ms();
        }

        let session = Self {
            paths,
            state,
            lock_file,
        };
        session.save()?;
        Ok(session)
    }

    pub fn prepare_directories(&mut self) -> Result<(), String> {
        self.start_step("preparing_directories")?;
        self.paths.ensure_layout()?;
        self.complete_step("preparing_directories")
    }

    pub fn start_step(&mut self, step: &str) -> Result<(), String> {
        self.state.status = BootstrapStatus::Running;
        self.state.current_step = Some(step.to_string());
        self.state.error = None;
        self.state.updated_at_ms = now_ms();
        self.save()
    }

    pub fn complete_step(&mut self, step: &str) -> Result<(), String> {
        if !self.state.completed_steps.iter().any(|item| item == step) {
            self.state.completed_steps.push(step.to_string());
        }
        self.state.current_step = None;
        self.state.updated_at_ms = now_ms();
        self.save()
    }

    pub fn mark_service_pending(&mut self) -> Result<(), String> {
        self.state.status = BootstrapStatus::ServicePending;
        self.state.current_step = Some("validating_runtime".to_string());
        self.state.error = None;
        self.state.updated_at_ms = now_ms();
        self.save()
    }

    pub fn mark_ready(&mut self) -> Result<(), String> {
        if !self
            .state
            .completed_steps
            .iter()
            .any(|item| item == "validating_runtime")
        {
            self.state
                .completed_steps
                .push("validating_runtime".to_string());
        }
        self.state.status = BootstrapStatus::Ready;
        self.state.current_step = None;
        self.state.error = None;
        self.state.updated_at_ms = now_ms();
        self.save()
    }

    pub fn mark_failed(&mut self, error: &str) {
        self.state.status = BootstrapStatus::Failed;
        self.state.error = Some(error.to_string());
        self.state.updated_at_ms = now_ms();
        let _ = self.save();
    }

    fn save(&self) -> Result<(), String> {
        write_json_atomic(&self.paths.bootstrap_state(), &self.state)
    }
}

impl Drop for BootstrapSession {
    fn drop(&mut self) {
        let _ = self.lock_file.unlock();
    }
}

pub fn read_service_manifest(paths: &RuntimePaths) -> Option<ServiceManifest> {
    load_json(&paths.service_manifest())
}

pub fn write_service_manifest(
    paths: &RuntimePaths,
    manifest: &ServiceManifest,
) -> Result<(), String> {
    write_json_atomic(&paths.service_manifest(), manifest)
}

pub fn mark_service_stopped(paths: &RuntimePaths) {
    let Some(mut manifest) = read_service_manifest(paths) else {
        return;
    };
    manifest.status = "stopped".to_string();
    manifest.updated_at_ms = now_ms();
    let _ = write_service_manifest(paths, &manifest);
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default()
}

fn load_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Option<T> {
    let content = fs::read_to_string(path).ok()?;
    serde_json::from_str(&content).ok()
}

fn write_json_atomic<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| format!("无效的运行时文件路径：{}", path.display()))?;
    fs::create_dir_all(parent)
        .map_err(|error| format!("无法创建运行时目录 {}：{error}", parent.display()))?;
    let temp = path.with_extension(format!("tmp-{}", std::process::id()));
    let payload = serde_json::to_vec_pretty(value)
        .map_err(|error| format!("无法序列化 MineM 运行时状态：{error}"))?;
    let mut file = File::create(&temp)
        .map_err(|error| format!("无法写入运行时临时文件 {}：{error}", temp.display()))?;
    file.write_all(&payload)
        .map_err(|error| format!("无法写入运行时状态：{error}"))?;
    file.sync_all()
        .map_err(|error| format!("无法同步运行时状态：{error}"))?;
    match fs::rename(&temp, path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {
            fs::remove_file(path)
                .map_err(|remove_error| format!("无法替换运行时状态：{remove_error}"))?;
            fs::rename(&temp, path)
                .map_err(|rename_error| format!("无法发布运行时状态：{rename_error}"))
        }
        Err(error) => Err(format!("无法发布运行时状态 {}：{error}", path.display())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_root(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "minem-bootstrap-{name}-{}-{}",
            std::process::id(),
            now_ms()
        ))
    }

    #[test]
    fn bootstrap_is_idempotent_and_persists_ready_state() {
        let root = test_root("ready");
        let paths = RuntimePaths::new(root.clone());
        {
            let mut session = BootstrapSession::begin(paths.clone(), "0.5.0").unwrap();
            session.prepare_directories().unwrap();
            session.start_step("verifying_bundle").unwrap();
            session.complete_step("verifying_bundle").unwrap();
            session.mark_service_pending().unwrap();
            session.mark_ready().unwrap();
        }

        let state: BootstrapState = load_json(&paths.bootstrap_state()).unwrap();
        assert_eq!(state.status, BootstrapStatus::Ready);
        assert_eq!(
            state
                .completed_steps
                .iter()
                .filter(|step| step.as_str() == "preparing_directories")
                .count(),
            1
        );

        {
            let mut session = BootstrapSession::begin(paths.clone(), "0.5.0").unwrap();
            session.prepare_directories().unwrap();
            session.mark_ready().unwrap();
        }
        let state: BootstrapState = load_json(&paths.bootstrap_state()).unwrap();
        assert_eq!(
            state
                .completed_steps
                .iter()
                .filter(|step| step.as_str() == "preparing_directories")
                .count(),
            1
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn bootstrap_lock_rejects_concurrent_initialization() {
        let root = test_root("lock");
        let paths = RuntimePaths::new(root.clone());
        let first = BootstrapSession::begin(paths.clone(), "0.5.0").unwrap();
        let second = BootstrapSession::begin(paths, "0.5.0");
        assert!(second.is_err());
        drop(first);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn service_manifest_round_trips() {
        let root = test_root("service");
        let paths = RuntimePaths::new(root.clone());
        paths.ensure_layout().unwrap();
        let manifest = ServiceManifest::running("0.5.0", 8790, Some(123), true);
        write_service_manifest(&paths, &manifest).unwrap();
        let loaded = read_service_manifest(&paths).unwrap();
        assert_eq!(loaded.port, 8790);
        assert_eq!(loaded.pid, Some(123));
        fs::remove_dir_all(root).unwrap();
    }
}
