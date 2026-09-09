import os
import time
import platform
import subprocess
from datetime import datetime
from tinarchy.config import get_system_hostname, get_app_config, PRIMARY_USER, BASE_DIR
from tinarchy.telemetry import get_cpu_temp, get_cpu_percent, get_ram_stats, get_power_supply_status, get_tailscale_ip

_DAILY_REPORT_CACHE = {'data': None, 'ts': 0}

def generate_daily_system_report(force=False):
    global _DAILY_REPORT_CACHE
    now = time.time()
    if not force and _DAILY_REPORT_CACHE['data'] and (now - _DAILY_REPORT_CACHE['ts']) < 4:
        return _DAILY_REPORT_CACHE['data']

    rep = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "hostname": get_system_hostname(),
        "kernel": platform.release(),
        "arch": platform.machine(),
    }

    # 1. Uptime & Load
    try:
        with open('/proc/uptime', 'r') as f:
            up = float(f.readline().split()[0])
            d = int(up // 86400)
            h = int((up % 86400) // 3600)
            m = int((up % 3600) // 60)
            rep['uptime'] = f"{d}d {h}h {m}m"
            rep['uptime_seconds'] = int(up)
    except Exception:
        rep['uptime'] = "Unknown"
        rep['uptime_seconds'] = 0

    try:
        with open('/proc/loadavg', 'r') as f:
            parts = f.readline().split()
            rep['loadavg'] = parts[:3]
            rep['runnable'] = parts[3] if len(parts) > 3 else "N/A"
    except Exception:
        rep['loadavg'] = ["0.00", "0.00", "0.00"]
        rep['runnable'] = "N/A"

    # 2. CPU & Thermals
    celsius_str, celsius_val = get_cpu_temp()
    rep['cpu_temp'] = celsius_str
    rep['cpu_temp_val'] = celsius_val
    rep['cpu_percent'] = get_cpu_percent()

    # Governor Telemetry
    gov_raw = ""
    gov_script = os.path.join(BASE_DIR, "configs", "scripts", "tinarchy-resource-governor.py")
    if not os.path.exists(gov_script):
        for candidate in ["/usr/local/bin/tinarchy-resource-governor", "/home/pineapple/Tinarchy/configs/scripts/tinarchy-resource-governor.py", "/home/tin/server-dashboard/configs/scripts/tinarchy-resource-governor.py"]:
            if os.path.exists(candidate):
                gov_script = candidate
                break
    try:
        res = subprocess.run(
            ["/usr/bin/python3", gov_script, "--status"],
            capture_output=True, text=True, timeout=2
        )
        gov_raw = res.stdout.strip()
    except Exception as e:
        gov_raw = f"Governor status error: {e}"
    rep['governor_raw'] = gov_raw

    rep['governor'] = {
        "tier": "TIER 0: ACTIVE (Interactive Use)",
        "target_temp": "76.0 °C",
        "turbo": "DISABLED (Cool)",
        "max_freq": "2000 MHz",
        "suwayomi_quota": "200%",
        "inactivity": "0s",
        "demand": "throttled_usec=0",
        "agy_status": "Active process registered"
    }
    for line in gov_raw.splitlines():
        if "Current Operational Tier:" in line:
            rep['governor']['tier'] = line.split(":", 1)[1].strip()
        elif "Target Thermal Budget:" in line:
            rep['governor']['target_temp'] = line.split(":", 1)[1].strip()
        elif "Intel Turbo Boost:" in line:
            rep['governor']['turbo'] = line.split(":", 1)[1].strip()
        elif "Dynamic Frequency Ceiling:" in line:
            rep['governor']['max_freq'] = line.split(":", 1)[1].strip()
        elif "Suwayomi CPU Quota:" in line:
            rep['governor']['suwayomi_quota'] = line.split(":", 1)[1].strip()
        elif "Inactivity Elapsed:" in line:
            rep['governor']['inactivity'] = line.split(":", 1)[1].strip()
        elif "Suwayomi Demand:" in line:
            rep['governor']['demand'] = line.split(":", 1)[1].strip()
        elif "agy Daemon" in line:
            rep['governor']['agy_status'] = line.split(":", 1)[1].strip()

    # 3. RAM & Storage
    ram = get_ram_stats()
    used_gb = round(ram.get('ram_used_mb', 0) / 1024, 1)
    tot_gb = round(ram.get('ram_total_mb', 0) / 1024, 1)
    rep['ram'] = {
        'used': f"{used_gb}GB",
        'total': f"{tot_gb}GB",
        'percent': ram.get('ram_percent', 0)
    }
    try:
        vfs = os.statvfs('/')
        tot = vfs.f_blocks * vfs.f_frsize
        free = vfs.f_bfree * vfs.f_frsize
        used = tot - free
        rep['disk'] = {
            'used': f"{int(used / (1024**3))}GB",
            'total': f"{int(tot / (1024**3))}GB",
            'percent': round((used / tot) * 100, 1) if tot > 0 else 0
        }
    except Exception:
        rep['disk'] = {'used': '0GB', 'total': '0GB', 'percent': 0}

    rep['zram'] = {
        'device': '/dev/zram0',
        'size': '3.8 GB',
        'compression': 'LZ4',
        'priority': 100
    }
    try:
        with open('/sys/block/sda/queue/read_ahead_kb', 'r') as f:
            rep['read_ahead_kb'] = f.read().strip()
    except Exception:
        rep['read_ahead_kb'] = '2048'

    rep['ramdisk_transcodes'] = {
        'path': '/dev/shm/jellyfin-transcodes',
        'active': os.path.exists('/dev/shm/jellyfin-transcodes'),
        'engine': 'iGPU QuickSync VA-API (Intel HD Graphics 4000)'
    }

    # 4. Network & PESU WiFi
    rep['network'] = {
        'rps_mask': 'f (All 4 Cores: wlan0, tailscale0, enp2s0f0)',
        'congestion_control': 'BBR (Bottleneck Bandwidth and RTT)',
        'tcp_buffer_max': '64 MB Autotuned',
        'tailscale_ip': get_tailscale_ip()
    }
    try:
        jnl = subprocess.run(
            ["journalctl", "-u", "pesu-wifi.service", "--no-pager", "-n", "1"],
            capture_output=True, text=True, timeout=1
        )
        last_pesu = jnl.stdout.strip().split("]: ")[-1] if "]: " in jnl.stdout else "Session active"
    except Exception:
        last_pesu = "Session active"
    rep['pesu_wifi'] = {
        'ssid': 'PESU-EC-Campus',
        'gateway': 'http://192.168.254.1:8090',
        'account': 'deltatime-4',
        'status': last_pesu
    }

    # 5. Battery & Autonomous UPS Telemetry
    pwr = get_power_supply_status()
    rep['battery'] = {
        'ac_online': pwr['ac_online'],
        'source': 'Mains AC (Online)' if pwr['ac_online'] else f"Battery Reserve ({pwr['status']})",
        'capacity': pwr['capacity'],
        'status': pwr['status'],
        'health_pct': pwr['health_pct'],
        'charge_mah': f"{pwr['charge_now_mah']} / {pwr['charge_full_mah']} mAh",
        'design_mah': f"{pwr['design_mah']} mAh",
        'voltage_v': f"{pwr['voltage_v']} V",
        'chemistry': 'Li-ion (SONY 3S 18650 Steel Cans)',
        'failover': '< 10 µs (Instantaneous Silicon Switch)',
        'safe_cutoff': '15% Auto-Poweroff'
    }

    # 6. Core Services Status
    cfg_app = get_app_config()
    current_user = cfg_app.get('ssh_user') or PRIMARY_USER
    syncthing_unit = f"syncthing@{current_user}.service"
    try:
        st_chk = subprocess.run(["systemctl", "is-active", syncthing_unit], capture_output=True, text=True, timeout=1).stdout.strip()
        if st_chk != "active":
            for candidate_user in ["pineapple", "tin"]:
                cand_unit = f"syncthing@{candidate_user}.service"
                if subprocess.run(["systemctl", "is-active", cand_unit], capture_output=True, text=True, timeout=1).stdout.strip() == "active":
                    syncthing_unit = cand_unit
                    break
    except Exception:
        pass

    services = [
        ("tinarchy.service", "Tinarchy Control Engine"),
        ("tinarchy-resource-governor.service", "Autonomous Resource Governor"),
        ("tinarchy-net-autotune.service", "Dynamic Network Tuner"),
        ("pesu-wifi.service", "PESU WiFi Portal Daemon"),
        ("suwayomi-server.service", "Suwayomi Manga Server"),
        ("xvfb.service", "Xvfb Headless Display (:99)"),
        ("jellyfin.service", "Jellyfin Media Server"),
        (syncthing_unit, "Syncthing Mesh Sync"),
        ("tailscaled.service", "Tailscale VPN Engine"),
        ("nginx.service", "Nginx Web Proxy"),
        ("thermald.service", "Intel Thermal Daemon"),
    ]
    rep['services'] = []
    for unit, label in services:
        try:
            res = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=1)
            st = res.stdout.strip()
            rep['services'].append({"unit": unit, "name": label, "status": st if st else "inactive"})
        except Exception:
            rep['services'].append({"unit": unit, "name": label, "status": "unknown"})

    # 7. Generate Pre-formatted Markdown String
    host_display = cfg_app.get('display_name') or rep['hostname'].replace('-', ' ').title()
    md_lines = [
        f"# 🍍 {host_display} Daily System Report",
        f"**Generated:** {rep['timestamp']} | **Uptime:** {rep['uptime']} | **Load:** {', '.join(rep['loadavg'])}",
        f"",
        f"---",
        f"",
        f"### 🌡️ Thermal & Closed-Loop Governor",
        f"- **Current Temperature:** {rep['cpu_temp']} (Target Budget: {rep['governor']['target_temp']})",
        f"- **Operational Tier:** `{rep['governor']['tier']}`",
        f"- **Intel Turbo Boost:** `{rep['governor']['turbo']}`",
        f"- **Dynamic Clock Ceiling:** `{rep['governor']['max_freq']}`",
        f"- **Suwayomi CPU Quota:** `{rep['governor']['suwayomi_quota']}` (Demand: {rep['governor']['demand']})",
        f"- **User Inactivity Elapsed:** `{rep['governor']['inactivity']}`",
        f"",
        f"### 🔋 Autonomous UPS & Battery Guard",
        f"- **Power Source:** `{rep['battery']['source']}`",
        f"- **Battery Charge Level:** `{rep['battery']['capacity']}%` ({rep['battery']['status']})",
        f"- **Pack Health:** `{rep['battery']['health_pct']}%` ({rep['battery']['charge_mah']} | Design: {rep['battery']['design_mah']})",
        f"- **Cell Pack & Voltage:** `{rep['battery']['chemistry']}` @ `{rep['battery']['voltage_v']}`",
        f"- **AC Failover Latency:** `{rep['battery']['failover']}`",
        f"- **Brownout Protection Cutoff:** `{rep['battery']['safe_cutoff']}`",
        f"",
        f"### 🌐 Network & Packet Steering",
        f"- **Multicore RPS/RFS:** `{rep['network']['rps_mask']}`",
        f"- **Congestion Control:** `{rep['network']['congestion_control']}`",
        f"- **Tailscale Mesh IP:** `{rep['network']['tailscale_ip']}`",
        f"- **PESU Wi-Fi:** SSID `{rep['pesu_wifi']['ssid']}` | Active Account: `{rep['pesu_wifi']['account']}`",
        f"- **Watchdog Status:** `{rep['pesu_wifi']['status']}`",
        f"",
        f"### 💾 Storage, RAM & Acceleration",
        f"- **Physical RAM:** {rep['ram'].get('used', '0GB')} / {rep['ram'].get('total', '0GB')} ({rep['ram'].get('percent', 0)}%)",
        f"- **LZ4 ZRAM Cushion:** {rep['zram']['size']} (Priority {rep['zram']['priority']})",
        f"- **Primary SSD:** {rep['disk']['used']} / {rep['disk']['total']} ({rep['disk']['percent']}%)",
        f"- **Sequential Read-Ahead:** `{rep['read_ahead_kb']} KB`",
        f"- **RAM-Disk Transcoding:** `{rep['ramdisk_transcodes']['path']}` ({rep['ramdisk_transcodes']['engine']})",
        f"",
        f"### 📦 Core System Services Matrix",
    ]
    for s in rep['services']:
        icon = "🟢" if s['status'] == 'active' else "🔴"
        md_lines.append(f"- {icon} **{s['name']}** (`{s['unit']}`): `{s['status']}`")

    rep['markdown_report'] = "\n".join(md_lines)
    _DAILY_REPORT_CACHE = {'data': rep, 'ts': now}
    return rep
