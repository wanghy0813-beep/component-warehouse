use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use std::{
    fs,
    path::{Path, PathBuf},
    sync::Mutex,
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tauri::{Manager, State};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

const API_PORT: u16 = 18764;
const CLIENT_ID: &str = "componentwarehouse-desktop-v1";
const ACCOUNT_DEVICE_BASE: &str = "https://wxylab.ltd/api/wxylab/device/v1";
const HARDWARE_BASE: &str = "https://wxylab.ltd/hardware";
const TOKEN_SERVICE: &str = "WXY LAB Hardware";
const TOKEN_USER: &str = "componentwarehouse-desktop-v1";

#[derive(Serialize, Deserialize, Default, Clone)]
#[serde(rename_all = "camelCase")]
struct ShellConfig {
    installation_id: String,
    device_id: Option<String>,
}

#[derive(Clone)]
struct AccessToken {
    value: String,
    expires_at: u64,
}

struct RuntimeState {
    session_key: String,
    api_base: String,
    data_dir: PathBuf,
    config: Mutex<ShellConfig>,
    device_code: Mutex<Option<String>>,
    access_token: Mutex<Option<AccessToken>>,
    sidecar: Mutex<Option<CommandChild>>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopContext {
    api_base: String,
    session_key: String,
    remote_base: String,
}

#[derive(Serialize, Deserialize)]
struct DeviceAuthorizationWire {
    device_code: String,
    user_code: String,
    verification_uri: String,
    verification_uri_complete: Option<String>,
    expires_in: u64,
    interval: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DeviceAuthorizationView {
    user_code: String,
    verification_uri: String,
    verification_uri_complete: Option<String>,
    expires_in: u64,
    interval: u64,
}

#[derive(Deserialize)]
struct TokenWire {
    access_token: String,
    refresh_token: String,
    expires_in: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PollResult {
    status: String,
    retry_after: Option<u64>,
}

fn now_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn config_path(data_dir: &Path) -> PathBuf {
    data_dir.join("desktop-shell.json")
}

fn load_config(data_dir: &Path) -> Result<ShellConfig, String> {
    let path = config_path(data_dir);
    if path.exists() {
        let content = fs::read_to_string(&path).map_err(|error| error.to_string())?;
        return serde_json::from_str(&content).map_err(|error| error.to_string());
    }
    let config = ShellConfig {
        installation_id: uuid::Uuid::new_v4().to_string(),
        device_id: None,
    };
    save_config(data_dir, &config)?;
    Ok(config)
}

fn save_config(data_dir: &Path, config: &ShellConfig) -> Result<(), String> {
    let path = config_path(data_dir);
    let temporary = path.with_extension("tmp");
    fs::write(
        &temporary,
        serde_json::to_vec_pretty(config).map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())?;
    fs::rename(temporary, path).map_err(|error| error.to_string())
}

fn keyring_entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(TOKEN_SERVICE, TOKEN_USER).map_err(|error| error.to_string())
}

async fn refresh_access(state: &RuntimeState) -> Result<String, String> {
    if let Some(token) = state
        .access_token
        .lock()
        .map_err(|_| "token lock failed")?
        .clone()
    {
        if token.expires_at > now_seconds() + 60 {
            return Ok(token.value);
        }
    }
    let refresh_token = keyring_entry()?
        .get_password()
        .map_err(|_| "账号需要重新绑定".to_string())?;
    let response = reqwest::Client::new()
        .post(format!("{ACCOUNT_DEVICE_BASE}/token"))
        .form(&[
            ("grant_type", "refresh_token"),
            ("client_id", CLIENT_ID),
            ("refresh_token", refresh_token.as_str()),
        ])
        .send()
        .await
        .map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        return Err("账号需要重新绑定".to_string());
    }
    let tokens: TokenWire = response.json().await.map_err(|error| error.to_string())?;
    keyring_entry()?
        .set_password(&tokens.refresh_token)
        .map_err(|error| error.to_string())?;
    let access = AccessToken {
        value: tokens.access_token.clone(),
        expires_at: now_seconds() + tokens.expires_in,
    };
    *state.access_token.lock().map_err(|_| "token lock failed")? = Some(access);
    Ok(tokens.access_token)
}

async fn local_post(
    state: &RuntimeState,
    path: &str,
    body: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let response = reqwest::Client::new()
        .post(format!(
            "{}/{}",
            state.api_base,
            path.trim_start_matches('/')
        ))
        .header("X-WXY-Desktop-Session", &state.session_key)
        .json(&body)
        .send()
        .await
        .map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        return Err(response
            .text()
            .await
            .unwrap_or_else(|_| "本地服务请求失败".to_string()));
    }
    response.json().await.map_err(|error| error.to_string())
}

async fn run_sync(state: &RuntimeState) -> Result<serde_json::Value, String> {
    let access = refresh_access(state).await?;
    let device_id = state
        .config
        .lock()
        .map_err(|_| "config lock failed")?
        .device_id
        .clone()
        .ok_or_else(|| "账号需要重新绑定".to_string())?;
    local_post(
        state,
        "desktop/v1/sync-now",
        serde_json::json!({
            "remote_base": HARDWARE_BASE,
            "access_token": access,
            "device_id": device_id,
        }),
    )
    .await
}

#[tauri::command]
fn desktop_context(state: State<'_, RuntimeState>) -> DesktopContext {
    DesktopContext {
        api_base: state.api_base.clone(),
        session_key: state.session_key.clone(),
        remote_base: HARDWARE_BASE.to_string(),
    }
}

#[tauri::command]
async fn start_device_authorization(
    state: State<'_, RuntimeState>,
) -> Result<DeviceAuthorizationView, String> {
    let installation_id = state
        .config
        .lock()
        .map_err(|_| "config lock failed")?
        .installation_id
        .clone();
    let response = reqwest::Client::new()
        .post(format!("{ACCOUNT_DEVICE_BASE}/authorize"))
        .json(&serde_json::json!({
            "client_id": CLIENT_ID,
            "device_kind": "account",
            "installation_id": installation_id,
            "device_name": "WXY LAB Hardware Windows",
            "model": "Windows x64",
            "platform": "windows",
            "scope": "account.profile.read hardware.sync.read hardware.sync.write"
        }))
        .send()
        .await
        .map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        return Err(response
            .text()
            .await
            .unwrap_or_else(|_| "无法开始账号授权".to_string()));
    }
    let wire: DeviceAuthorizationWire = response.json().await.map_err(|error| error.to_string())?;
    *state
        .device_code
        .lock()
        .map_err(|_| "device code lock failed")? = Some(wire.device_code);
    Ok(DeviceAuthorizationView {
        user_code: wire.user_code,
        verification_uri: wire.verification_uri,
        verification_uri_complete: wire.verification_uri_complete,
        expires_in: wire.expires_in,
        interval: wire.interval,
    })
}

#[tauri::command]
async fn poll_device_authorization(state: State<'_, RuntimeState>) -> Result<PollResult, String> {
    let device_code = state
        .device_code
        .lock()
        .map_err(|_| "device code lock failed")?
        .clone()
        .ok_or_else(|| "请重新开始账号授权".to_string())?;
    let response = reqwest::Client::new()
        .post(format!("{ACCOUNT_DEVICE_BASE}/token"))
        .form(&[
            ("grant_type", "urn:ietf:params:oauth:grant-type:device_code"),
            ("client_id", CLIENT_ID),
            ("device_code", device_code.as_str()),
        ])
        .send()
        .await
        .map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        let retry_after = response
            .headers()
            .get("retry-after")
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<u64>().ok());
        let body: serde_json::Value = response.json().await.unwrap_or_default();
        let code = body
            .get("error")
            .and_then(|value| value.as_str())
            .or_else(|| body.pointer("/error/code").and_then(|value| value.as_str()))
            .unwrap_or("authorization_failed");
        if code == "authorization_pending" || code == "slow_down" {
            return Ok(PollResult {
                status: if code == "authorization_pending" {
                    "pending"
                } else {
                    code
                }
                .to_string(),
                retry_after,
            });
        }
        return Err(body.to_string());
    }
    let tokens: TokenWire = response.json().await.map_err(|error| error.to_string())?;
    keyring_entry()?
        .set_password(&tokens.refresh_token)
        .map_err(|error| error.to_string())?;
    *state.access_token.lock().map_err(|_| "token lock failed")? = Some(AccessToken {
        value: tokens.access_token.clone(),
        expires_at: now_seconds() + tokens.expires_in,
    });

    let installation_id = state
        .config
        .lock()
        .map_err(|_| "config lock failed")?
        .installation_id
        .clone();
    let client = reqwest::Client::new();
    let registration = client
        .post(format!("{HARDWARE_BASE}/api/sync/v1/devices"))
        .bearer_auth(&tokens.access_token)
        .json(&serde_json::json!({
            "installation_id": installation_id,
            "name": "WXY LAB Hardware Windows",
            "platform": "windows-x64"
        }))
        .send()
        .await
        .map_err(|error| error.to_string())?;
    if !registration.status().is_success() {
        return Err(registration
            .text()
            .await
            .unwrap_or_else(|_| "服务器拒绝设备登记".to_string()));
    }
    let registration: serde_json::Value = registration
        .json()
        .await
        .map_err(|error| error.to_string())?;
    let device_id = registration
        .get("device_id")
        .and_then(|value| value.as_str())
        .ok_or_else(|| "设备登记响应缺少 device_id".to_string())?
        .to_string();

    let staging = state.data_dir.join("staging");
    fs::create_dir_all(&staging).map_err(|error| error.to_string())?;
    let package_path = staging.join("personal-bootstrap.zip");
    let response = client
        .get(format!("{HARDWARE_BASE}/api/sync/v1/bootstrap"))
        .bearer_auth(&tokens.access_token)
        .query(&[("device_id", device_id.as_str())])
        .send()
        .await
        .map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        return Err(response
            .text()
            .await
            .unwrap_or_else(|_| "个人数据下载失败".to_string()));
    }
    let mut output = tokio::fs::File::create(&package_path)
        .await
        .map_err(|error| error.to_string())?;
    let mut stream = response.bytes_stream();
    use tokio::io::AsyncWriteExt;
    while let Some(chunk) = stream.next().await {
        output
            .write_all(&chunk.map_err(|error| error.to_string())?)
            .await
            .map_err(|error| error.to_string())?;
    }
    output.flush().await.map_err(|error| error.to_string())?;
    local_post(
        &state,
        "desktop/v1/bootstrap/import",
        serde_json::json!({
            "path": package_path,
            "device_id": device_id,
        }),
    )
    .await?;
    let _ = fs::remove_file(&package_path);
    {
        let mut config = state.config.lock().map_err(|_| "config lock failed")?;
        config.device_id = Some(device_id);
        save_config(&state.data_dir, &config)?;
    }
    *state
        .device_code
        .lock()
        .map_err(|_| "device code lock failed")? = None;
    Ok(PollResult {
        status: "complete".to_string(),
        retry_after: None,
    })
}

#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    if !url.starts_with("https://wxylab.ltd/") {
        return Err("只允许打开 WXY LAB 账号页面".to_string());
    }
    opener::open_browser(url).map_err(|error| error.to_string())
}

#[tauri::command]
async fn desktop_sync_now(state: State<'_, RuntimeState>) -> Result<serde_json::Value, String> {
    run_sync(&state).await
}

#[tauri::command]
async fn desktop_conflicts(state: State<'_, RuntimeState>) -> Result<serde_json::Value, String> {
    let access = refresh_access(&state).await?;
    let response = reqwest::Client::new()
        .get(format!("{HARDWARE_BASE}/api/sync/v1/conflicts"))
        .bearer_auth(access)
        .send()
        .await
        .map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        return Err(response
            .text()
            .await
            .unwrap_or_else(|_| "无法读取同步冲突".to_string()));
    }
    response.json().await.map_err(|error| error.to_string())
}

#[tauri::command]
async fn resolve_desktop_conflict(
    state: State<'_, RuntimeState>,
    conflict_id: String,
    resolution: String,
) -> Result<serde_json::Value, String> {
    if !matches!(resolution.as_str(), "server" | "client" | "delete") {
        return Err("冲突处理方式无效".to_string());
    }
    let access = refresh_access(&state).await?;
    let response = reqwest::Client::new()
        .post(format!(
            "{HARDWARE_BASE}/api/sync/v1/conflicts/{conflict_id}/resolve"
        ))
        .bearer_auth(access)
        .json(&serde_json::json!({ "resolution": resolution }))
        .send()
        .await
        .map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        return Err(response
            .text()
            .await
            .unwrap_or_else(|_| "冲突处理失败".to_string()));
    }
    let resolved = response.json().await.map_err(|error| error.to_string())?;
    run_sync(&state).await?;
    Ok(resolved)
}

fn main() {
    let mut builder = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .invoke_handler(tauri::generate_handler![
            desktop_context,
            start_device_authorization,
            poll_device_authorization,
            open_external_url,
            desktop_sync_now,
            desktop_conflicts,
            resolve_desktop_conflict
        ])
        .setup(|app| {
            let local_app_data =
                std::env::var("LOCALAPPDATA").map_err(|_| "LOCALAPPDATA is unavailable")?;
            let data_dir = PathBuf::from(local_app_data).join("WXY LAB Hardware");
            fs::create_dir_all(&data_dir)?;
            let session_key = format!(
                "{}{}",
                uuid::Uuid::new_v4().simple(),
                uuid::Uuid::new_v4().simple()
            );
            let config = load_config(&data_dir).map_err(std::io::Error::other)?;
            let (mut receiver, child) = app
                .shell()
                .sidecar("wxy-hardware-api")?
                .env("DESKTOP_SESSION_KEY", &session_key)
                .env("DESKTOP_API_PORT", API_PORT.to_string())
                .env(
                    "LOCALAPPDATA",
                    data_dir
                        .parent()
                        .unwrap_or(&data_dir)
                        .to_string_lossy()
                        .to_string(),
                )
                .spawn()?;
            tauri::async_runtime::spawn(async move { while receiver.recv().await.is_some() {} });
            app.manage(RuntimeState {
                session_key: session_key.clone(),
                api_base: format!("http://127.0.0.1:{API_PORT}/api"),
                data_dir,
                config: Mutex::new(config),
                device_code: Mutex::new(None),
                access_token: Mutex::new(None),
                sidecar: Mutex::new(Some(child)),
            });
            let mut sidecar_healthy = false;
            for _ in 0..100 {
                if reqwest::blocking::get(format!("http://127.0.0.1:{API_PORT}/health"))
                    .map(|response| response.status().is_success())
                    .unwrap_or(false)
                {
                    sidecar_healthy = true;
                    break;
                }
                thread::sleep(Duration::from_millis(150));
            }
            if !sidecar_healthy {
                return Err(std::io::Error::other("本地 API 服务启动超时").into());
            }
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                loop {
                    let succeeded = {
                        let state = handle.state::<RuntimeState>();
                        run_sync(&state).await.is_ok()
                    };
                    tokio::time::sleep(if succeeded {
                        Duration::from_secs(300)
                    } else {
                        Duration::from_secs(60)
                    })
                    .await;
                }
            });
            Ok(())
        });

    builder
        .build(tauri::generate_context!())
        .expect("failed to build desktop app")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                let state = app.state::<RuntimeState>();
                if let Ok(mut sidecar) = state.sidecar.lock() {
                    if let Some(child) = sidecar.take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
