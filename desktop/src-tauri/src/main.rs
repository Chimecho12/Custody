#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{collections::HashMap, sync::{Arc, Mutex, atomic::{AtomicU64, Ordering}}, time::Duration};
use serde_json::{json, Value};
use tauri::{Emitter, Manager};
use tauri_plugin_shell::{ShellExt, process::{CommandChild, CommandEvent}};
use tokio::sync::oneshot;

type Pending = Arc<Mutex<HashMap<String, oneshot::Sender<Result<Value, String>>>>>;
struct Bridge { child: Mutex<Option<CommandChild>>, pending: Pending, next: AtomicU64 }

#[tauri::command]
async fn dispatch(operation: String, args: Value, state: tauri::State<'_, Bridge>) -> Result<Value, String> {
    const OPS: &[&str] = &["status", "request", "cancel", "history", "refresh", "audit", "simulation", "simulation_matrix", "export", "connect", "lab", "stop_t", "start_t",
        "export_evidence", "export_trust", "export_checkpoint", "preflight", "witness", "retention_preview", "retention_apply",
        "enroll_prepare", "enroll_propose", "enroll_endorse", "enroll_assemble", "enroll_inspect", "enroll_activate", "recipient_create", "audit_verify"];
    if !OPS.contains(&operation.as_str()) || !args.is_object() { return Err("Unsupported Agent operation".into()); }
    let id = state.next.fetch_add(1, Ordering::Relaxed).to_string();
    let mut bytes = serde_json::to_vec(&json!({"id":id,"operation":operation,"args":args})).map_err(|e| e.to_string())?;
    if bytes.len() > 128_000 { return Err("IPC request too large".into()); }
    bytes.push(b'\n');
    let (tx, rx) = oneshot::channel();
    state.pending.lock().map_err(|_| "Agent state unavailable")?.insert(id.clone(), tx);
    let written = {
        let mut child = state.child.lock().map_err(|_| "Agent state unavailable")?;
        match child.as_mut() { Some(c) => c.write(&bytes).map_err(|e| e.to_string()), None => Err("Agent is not running. Restart itx.".into()) }
    };
    if let Err(e) = written { state.pending.lock().unwrap().remove(&id); return Err(e); }
    match tokio::time::timeout(Duration::from_secs(90), rx).await {
        Ok(Ok(result)) => result,
        _ => { state.pending.lock().unwrap().remove(&id); Err("Agent response timed out. Restart the app if it does not recover.".into()) }
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let data_dir = app.path().app_local_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;
            let (mut events, child) = app.shell().sidecar("itx-agent")?
                .args(["desktop", "--data-dir", data_dir.to_string_lossy().as_ref()]).spawn()?;
            let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
            app.manage(Bridge { child: Mutex::new(Some(child)), pending: pending.clone(), next: AtomicU64::new(1) });
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                while let Some(event) = events.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            if let Ok(message) = serde_json::from_slice::<Value>(&line) {
                                if message.get("event").and_then(Value::as_str) == Some("progress") {
                                    let _ = handle.emit("agent-progress", &message["data"]);
                                } else if let Some(id) = message.get("id").and_then(Value::as_str) {
                                    if let Some(tx) = pending.lock().unwrap().remove(id) {
                                        let result = if message["ok"] == true { Ok(message["result"].clone()) }
                                            else { Err(message["error"].as_str().unwrap_or("Agent error").to_owned()) };
                                        let _ = tx.send(result);
                                    }
                                }
                            }
                        }
                        CommandEvent::Terminated(_) | CommandEvent::Error(_) => {
                            for (_, tx) in pending.lock().unwrap().drain() { let _ = tx.send(Err("Agent connection closed".into())); }
                            let _ = handle.emit("agent-failure", "Agent가 종료되었습니다. 앱을 다시 실행하세요.");
                            break;
                        }
                        _ => {}
                    }
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![dispatch])
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                let state = window.state::<Bridge>();
                if let Some(mut child) = state.child.lock().unwrap().take() {
                    let _ = child.write(b"{\"operation\":\"shutdown\"}\n");
                    // Closing the sidecar also closes each lab service's parent pipe.
                    let _ = child.kill();
                };
            }
        })
        .run(tauri::generate_context!())
        .expect("itx application failed");
}
