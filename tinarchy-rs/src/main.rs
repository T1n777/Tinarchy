use axum::{
    routing::get,
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::{fs, net::SocketAddr, sync::Arc, time::Instant};
use tokio::sync::RwLock;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RamStats {
    pub ram_total_mb: u64,
    pub ram_used_mb: u64,
    pub ram_percent: f32,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct TelemetrySnapshot {
    pub cpu_percent: f32,
    pub cpu_temp: f32,
    pub ram: RamStats,
    pub loadavg: String,
    pub uptime_secs: u64,
    pub power_supply: String,
}

struct CpuSample {
    idle: u64,
    total: u64,
    timestamp: Instant,
}

struct AppState {
    last_cpu: RwLock<CpuSample>,
}

fn read_ram_stats() -> RamStats {
    let mut total_kb: u64 = 0;
    let mut avail_kb: u64 = 0;

    if let Ok(content) = fs::read_to_string("/proc/meminfo") {
        for line in content.lines() {
            if line.starts_with("MemTotal:") {
                total_kb = line.split_whitespace().nth(1).and_then(|s| s.parse().ok()).unwrap_or(0);
            } else if line.starts_with("MemAvailable:") {
                avail_kb = line.split_whitespace().nth(1).and_then(|s| s.parse().ok()).unwrap_or(0);
            }
        }
    }

    let total_mb = total_kb / 1024;
    let used_kb = total_kb.saturating_sub(avail_kb);
    let used_mb = used_kb / 1024;
    let percent = if total_kb > 0 {
        (used_kb as f32 / total_kb as f32) * 100.0
    } else {
        0.0
    };

    RamStats {
        ram_total_mb: total_mb,
        ram_used_mb: used_mb,
        ram_percent: (percent * 10.0).round() / 10.0,
    }
}

fn read_cpu_temp() -> f32 {
    let thermal_paths = [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/hwmon/hwmon0/temp1_input",
    ];
    for path in &thermal_paths {
        if let Ok(content) = fs::read_to_string(path) {
            if let Ok(milli) = content.trim().parse::<f32>() {
                return milli / 1000.0;
            }
        }
    }
    0.0
}

fn read_uptime() -> u64 {
    if let Ok(content) = fs::read_to_string("/proc/uptime") {
        if let Some(first) = content.split_whitespace().next() {
            if let Ok(secs) = first.parse::<f64>() {
                return secs as u64;
            }
        }
    }
    0
}

fn read_loadavg() -> String {
    fs::read_to_string("/proc/loadavg")
        .unwrap_or_default()
        .split_whitespace()
        .take(3)
        .collect::<Vec<&str>>()
        .join(" ")
}

fn read_power_supply() -> String {
    let power_path = "/sys/class/power_supply";
    if let Ok(entries) = fs::read_dir(power_path) {
        for entry in entries.flatten() {
            let status_file = entry.path().join("status");
            if let Ok(status) = fs::read_to_string(status_file) {
                let s = status.trim().to_uppercase();
                if s == "CHARGING" || s == "FULL" || s == "NOT CHARGING" {
                    return "AC Power".to_string();
                } else if s == "DISCHARGING" {
                    return "Battery".to_string();
                }
            }
        }
    }
    "AC Online".to_string()
}

fn read_raw_cpu() -> (u64, u64) {
    if let Ok(content) = fs::read_to_string("/proc/stat") {
        if let Some(first_line) = content.lines().next() {
            if first_line.starts_with("cpu ") {
                let parts: Vec<u64> = first_line
                    .split_whitespace()
                    .skip(1)
                    .filter_map(|s| s.parse().ok())
                    .collect();
                if parts.len() >= 4 {
                    let idle = parts[3] + parts.get(4).copied().unwrap_or(0);
                    let total: u64 = parts.iter().sum();
                    return (idle, total);
                }
            }
        }
    }
    (0, 0)
}

async fn get_telemetry(state: Arc<AppState>) -> Json<TelemetrySnapshot> {
    let (cur_idle, cur_total) = read_raw_cpu();
    let now = Instant::now();

    let mut lock = state.last_cpu.write().await;
    let diff_idle = cur_idle.saturating_sub(lock.idle);
    let diff_total = cur_total.saturating_sub(lock.total);

    let cpu_pct = if diff_total > 0 {
        let active = diff_total.saturating_sub(diff_idle);
        ((active as f32 / diff_total as f32) * 1000.0).round() / 10.0
    } else {
        0.0
    };

    lock.idle = cur_idle;
    lock.total = cur_total;
    lock.timestamp = now;
    drop(lock);

    Json(TelemetrySnapshot {
        cpu_percent: cpu_pct,
        cpu_temp: read_cpu_temp(),
        ram: read_ram_stats(),
        loadavg: read_loadavg(),
        uptime_secs: read_uptime(),
        power_supply: read_power_supply(),
    })
}

async fn health_check() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "status": "ok",
        "engine": "tinarchy-rs",
        "version": "0.1.0",
        "safety": "memory-safe (Rust 2024 edition)"
    }))
}

#[tokio::main]
async fn main() {
    let (idle, total) = read_raw_cpu();
    let state = Arc::new(AppState {
        last_cpu: RwLock::new(CpuSample {
            idle,
            total,
            timestamp: Instant::now(),
        }),
    });

    let state_for_route = state.clone();
    let app = Router::new()
        .route("/health", get(health_check))
        .route("/api/telemetry", get(move || get_telemetry(state_for_route)));

    let addr = SocketAddr::from(([127, 0, 0, 1], 8090));
    println!("🦀 Tinarchy-RS Prototype starting on http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
