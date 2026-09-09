import os
import glob
import time
import math
import socket
import subprocess
import threading
from tinarchy.config import get_system_hostname, get_app_config

# ─── Network Telemetry & Locks ───
PREV_NET = {'time': time.time(), 'rx': 0, 'tx': 0, 'rx_spd': 0, 'tx_spd': 0, 'rx_tot': 0, 'tx_tot': 0}
_NET_LOCK = threading.Lock()

# ─── CPU Telemetry & Locks ───
_CPU_LOCK = threading.Lock()
_LAST_CPU_PERCENT = 0.0

def _read_cpu_times():
    try:
        with open('/proc/stat', 'r') as f:
            line = f.readline()
        fields = [float(x) for x in line.strip().split()[1:]]
        # Linux standard: [0] user, [1] nice, [2] system, [3] idle, [4] iowait, [5] irq, [6] softirq, [7] steal
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0.0)
        non_idle = fields[0] + fields[1] + fields[2] + (sum(fields[5:8]) if len(fields) >= 8 else 0.0)
        total = idle + non_idle
        return time.time(), total, idle
    except Exception:
        return time.time(), 0.0, 0.0

_t_init, _tot_init, _idle_init = _read_cpu_times()
PREV_CPU = {'time': _t_init, 'total': _tot_init, 'idle': _idle_init}

def get_cpu_percent():
    global PREV_CPU, _LAST_CPU_PERCENT
    with _CPU_LOCK:
        now_t, total, idle = _read_cpu_times()
        if total == 0.0:
            return _LAST_CPU_PERCENT

        dt = now_t - PREV_CPU['time']
        diff_total = total - PREV_CPU['total']
        diff_idle = idle - PREV_CPU['idle']

        # Prevent false 0% spikes from rapid concurrent requests (< 0.5s)
        if dt < 0.5 or diff_total <= 0:
            return _LAST_CPU_PERCENT

        usage = max(0.0, min(100.0, (1.0 - (diff_idle / diff_total)) * 100.0))
        _LAST_CPU_PERCENT = round(usage, 1)
        PREV_CPU = {'time': now_t, 'total': total, 'idle': idle}
        return _LAST_CPU_PERCENT

def get_ram_stats():
    """Hardware-adaptive RAM usage calculation.
    Uses MemAvailable on modern Linux kernels with legacy fallbacks.
    """
    try:
        meminfo = {}
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.split(':')
                if len(parts) == 2:
                    meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])

        total_kb = meminfo.get('MemTotal', 0)
        if total_kb <= 0:
            return {'ram_used_mb': 0, 'ram_total_mb': 0, 'ram_percent': 0.0}

        if 'MemAvailable' in meminfo:
            avail_kb = meminfo['MemAvailable']
            used_kb = max(0, total_kb - avail_kb)
        else:
            free_kb = meminfo.get('MemFree', 0)
            buffers_kb = meminfo.get('Buffers', 0)
            cached_kb = meminfo.get('Cached', 0)
            sreclaim_kb = meminfo.get('SReclaimable', 0)
            shmem_kb = meminfo.get('Shmem', 0)
            used_kb = max(0, total_kb - free_kb - buffers_kb - cached_kb - sreclaim_kb + shmem_kb)

        used_mb = int(used_kb / 1024)
        total_mb = int(total_kb / 1024)
        percent = round((used_kb / total_kb) * 100.0, 1)

        return {
            'ram_used_mb': used_mb,
            'ram_total_mb': total_mb,
            'ram_percent': percent
        }
    except Exception:
        return {'ram_used_mb': 0, 'ram_total_mb': 0, 'ram_percent': 0.0}

def format_speed(bytes_per_sec):
    if bytes_per_sec < 1024:
        return f"{int(bytes_per_sec)} B/s"
    elif bytes_per_sec < 1024 * 1024:
        return f"{bytes_per_sec / 1024:.1f} KB/s"
    else:
        return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"

def format_total(bytes_total):
    if bytes_total < 1024 * 1024:
        return f"{bytes_total / 1024:.1f} KB"
    elif bytes_total < 1024 * 1024 * 1024:
        return f"{bytes_total / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_total / (1024 * 1024 * 1024):.2f} GB"

_CPU_TEMP_PATH = None

def find_best_cpu_temp_path():
    cpu_hwmon_names = {'coretemp', 'k10temp', 'zenpower', 'cpu_thermal', 'soc_thermal'}
    for hwmon in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
        try:
            with open(os.path.join(hwmon, 'name'), 'r') as f:
                h_name = f.read().strip().lower()
            if h_name in cpu_hwmon_names:
                for label_file in sorted(glob.glob(os.path.join(hwmon, 'temp*_label'))):
                    try:
                        with open(label_file, 'r') as lf:
                            lbl = lf.read().strip().lower()
                        if any(k in lbl for k in ('package', 'tdie', 'tctl', 'core 0')):
                            inp_file = label_file.replace('_label', '_input')
                            if os.path.isfile(inp_file):
                                return inp_file
                    except Exception:
                        pass
                t1 = os.path.join(hwmon, 'temp1_input')
                if os.path.isfile(t1):
                    return t1
        except Exception:
            pass

    cpu_zone_keywords = ('x86_pkg_temp', 'cpu', 'pkg', 'k10temp', 'coretemp', 'soc')
    for zone in sorted(glob.glob('/sys/class/thermal/thermal_zone*')):
        try:
            with open(os.path.join(zone, 'type'), 'r') as f:
                z_type = f.read().strip().lower()
            if any(k in z_type for k in cpu_zone_keywords):
                t_file = os.path.join(zone, 'temp')
                if os.path.isfile(t_file):
                    return t_file
        except Exception:
            pass

    for hwmon in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
        try:
            with open(os.path.join(hwmon, 'name'), 'r') as f:
                h_name = f.read().strip().lower()
            if any(k in h_name for k in ('dell', 'thinkpad', 'asus')):
                t1 = os.path.join(hwmon, 'temp1_input')
                if os.path.isfile(t1):
                    return t1
        except Exception:
            pass

    legacy_paths = [
        '/sys/class/thermal/thermal_zone0/temp',
        '/sys/class/hwmon/hwmon0/temp1_input',
        '/sys/class/hwmon/hwmon1/temp1_input'
    ]
    for p in legacy_paths:
        if os.path.isfile(p):
            return p

    return None

def get_cpu_temp():
    global _CPU_TEMP_PATH
    if not _CPU_TEMP_PATH or not os.path.isfile(_CPU_TEMP_PATH):
        _CPU_TEMP_PATH = find_best_cpu_temp_path()

    if _CPU_TEMP_PATH:
        try:
            with open(_CPU_TEMP_PATH, 'r') as f:
                val = int(f.read().strip())
                celsius = round(val / 1000.0, 1) if val > 1000 else float(val)
                return f"{celsius}°C", int(celsius)
        except Exception:
            _CPU_TEMP_PATH = None

    return "N/A", 0

def get_power_supply_status() -> dict:
    """Read AC mains and battery status directly from sysfs for UPS telemetry."""
    info = {
        "ac_online": True,
        "present": False,
        "capacity": 100,
        "status": "Full",
        "voltage_v": 0.0,
        "health_pct": 100.0,
        "charge_now_mah": 0,
        "charge_full_mah": 0,
        "design_mah": 0
    }
    # Check both ACAD and AC sysfs paths
    for acad_cand in ["/sys/class/power_supply/ACAD/online", "/sys/class/power_supply/AC/online"]:
        if os.path.exists(acad_cand):
            try:
                with open(acad_cand, "r") as f:
                    info["ac_online"] = (f.read().strip() == "1")
                break
            except Exception:
                pass

    # Check both BAT1 and BAT0 sysfs paths
    for bat_cand in ["/sys/class/power_supply/BAT1", "/sys/class/power_supply/BAT0"]:
        if os.path.exists(bat_cand):
            info["present"] = True
            try:
                with open(f"{bat_cand}/capacity", "r") as f:
                    info["capacity"] = int(f.read().strip())
            except Exception:
                pass
            try:
                with open(f"{bat_cand}/status", "r") as f:
                    info["status"] = f.read().strip()
                    if info["status"] == "Discharging":
                        info["ac_online"] = False
            except Exception:
                pass
            try:
                with open(f"{bat_cand}/voltage_now", "r") as f:
                    info["voltage_v"] = round(int(f.read().strip()) / 1e6, 2)
            except Exception:
                pass
            try:
                with open(f"{bat_cand}/charge_now", "r") as f:
                    info["charge_now_mah"] = int(f.read().strip()) // 1000
                with open(f"{bat_cand}/charge_full", "r") as f:
                    info["charge_full_mah"] = int(f.read().strip()) // 1000
                with open(f"{bat_cand}/charge_full_design", "r") as f:
                    info["design_mah"] = int(f.read().strip()) // 1000
                if info["design_mah"] > 0:
                    info["health_pct"] = round((info["charge_full_mah"] / info["design_mah"]) * 100, 1)
            except Exception:
                pass
            break

    return info

_TAILSCALE_IP_CACHE = {'ip': None, 'ts': 0}

def get_tailscale_ip():
    global _TAILSCALE_IP_CACHE
    now_t = time.time()
    if _TAILSCALE_IP_CACHE['ip'] and (now_t - _TAILSCALE_IP_CACHE['ts']) < 60:
        return _TAILSCALE_IP_CACHE['ip']
    try:
        res = subprocess.run(['tailscale', 'ip', '-4'], capture_output=True, text=True, timeout=2)
        ip = res.stdout.strip() if res.returncode == 0 else "Offline"
        _TAILSCALE_IP_CACHE = {'ip': ip, 'ts': now_t}
        return ip
    except Exception:
        return _TAILSCALE_IP_CACHE.get('ip') or "Offline"

def get_disk_stats():
    try:
        vfs = os.statvfs('/')
        disk_total = vfs.f_blocks * vfs.f_frsize
        disk_free = vfs.f_bfree * vfs.f_frsize
        disk_used = disk_total - disk_free
        return {
            'disk_used': f"{int(disk_used / (1024**3))}GB",
            'disk_total': f"{int(disk_total / (1024**3))}GB",
            'disk_percent': round((disk_used / disk_total) * 100, 1) if disk_total > 0 else 0
        }
    except Exception:
        return {'disk_used': "0GB", 'disk_total': "0GB", 'disk_percent': 0}

def get_uptime_and_load():
    res = {'uptime': "Unknown", 'loadavg': ["0.00", "0.00", "0.00"]}
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
            days = int(uptime_seconds // (24 * 3600))
            hours = int((uptime_seconds % (24 * 3600)) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            res['uptime'] = f"{days}d {hours}h {minutes}m"
    except Exception:
        pass
    try:
        with open('/proc/loadavg', 'r') as f:
            res['loadavg'] = f.readline().split()[:3]
    except Exception:
        pass
    return res

def get_network_stats():
    global PREV_NET
    now_t = time.time()
    try:
        with _NET_LOCK:
            rx_tot = 0
            tx_tot = 0
            with open('/proc/net/dev', 'r') as f_dev:
                for line in f_dev.readlines()[2:]:
                    parts = line.split(':')
                    if len(parts) == 2:
                        iface = parts[0].strip()
                        if iface != 'lo':
                            fields = parts[1].split()
                            rx_tot += int(fields[0])
                            tx_tot += int(fields[8])
            dt = now_t - PREV_NET['time']
            if dt >= 0.5:
                rx_spd = max(0, (rx_tot - PREV_NET['rx']) / dt) if PREV_NET['rx'] > 0 and rx_tot >= PREV_NET['rx'] else 0
                tx_spd = max(0, (tx_tot - PREV_NET['tx']) / dt) if PREV_NET['tx'] > 0 and tx_tot >= PREV_NET['tx'] else 0
                PREV_NET = {'time': now_t, 'rx': rx_tot, 'tx': tx_tot, 'rx_spd': rx_spd, 'tx_spd': tx_spd, 'rx_tot': rx_tot, 'tx_tot': tx_tot}
            else:
                rx_spd = PREV_NET.get('rx_spd', 0)
                tx_spd = PREV_NET.get('tx_spd', 0)

        tot_spd = rx_spd + tx_spd
        if tot_spd > 512:
            net_percent = min(100, max(5, int(math.log10(tot_spd) * 15)))
        else:
            net_percent = 2

        net_rx_speed = format_speed(rx_spd)
        net_tx_speed = format_speed(tx_spd)
        return {
            'net_rx_bytes_sec': rx_spd,
            'net_tx_bytes_sec': tx_spd,
            'net_rx_speed': net_rx_speed,
            'net_tx_speed': net_tx_speed,
            'net_rx_formatted': net_rx_speed,
            'net_tx_formatted': net_tx_speed,
            'net_rx_total': format_total(rx_tot),
            'net_tx_total': format_total(tx_tot),
            'net_text': f"▲ {net_tx_speed} · ▼ {net_rx_speed}",
            'net_percent': net_percent
        }
    except Exception:
        return {
            'net_rx_speed': '0 B/s',
            'net_tx_speed': '0 B/s',
            'net_text': '↓ 0 B/s · ↑ 0 B/s',
            'net_percent': 0,
            'net_rx_total': '0 MB',
            'net_tx_total': '0 MB'
        }

def collect_full_system_snapshot(syncthing_module=None):
    """Gathers complete telemetry dictionary matching /api/system output."""
    stats = {}
    stats.update(get_ram_stats())
    stats.update(get_disk_stats())
    stats['cpu_percent'] = get_cpu_percent()

    up_load = get_uptime_and_load()
    stats['uptime'] = up_load['uptime']
    stats['loadavg'] = up_load['loadavg']

    stats['hostname'] = get_system_hostname()
    stats['tailscale_ip'] = get_tailscale_ip()

    stats.update(get_network_stats())

    celsius_str, celsius_val = get_cpu_temp()
    stats['cpu_temp'] = celsius_str
    stats['cpu_temp_val'] = celsius_val

    app_cfg = get_app_config()
    stats['display_name'] = app_cfg.get('display_name') or stats['hostname']
    stats['server_name'] = stats['display_name']
    stats['project_name'] = app_cfg.get('project_name', stats['hostname'])
    stats['app_icon'] = app_cfg.get('app_icon', '🍍')
    stats['branding_subtitle'] = app_cfg.get('branding_subtitle', 'Server Control Center')
    stats['ssh_user'] = app_cfg.get('ssh_user', '')
    stats['tailscale_domain'] = app_cfg.get('tailscale_domain', '')

    # Drive sync status
    sync_last_file = '/run/tinarchy-drive/sync-last' if os.path.exists('/run/tinarchy-drive/sync-last') else '/run/pinedash-drive/sync-last'
    if os.path.exists(sync_last_file):
        try:
            with open(sync_last_file, 'r') as f_s:
                ts = int(f_s.read().strip())
                stats['drive_last_sync'] = ts
                diff = int(time.time()) - ts
                if diff < 60:
                    stats['drive_last_sync_human'] = 'Just now'
                elif diff < 3600:
                    stats['drive_last_sync_human'] = f"{diff // 60}m ago"
                elif diff < 86400:
                    stats['drive_last_sync_human'] = f"{diff // 3600}h ago"
                else:
                    stats['drive_last_sync_human'] = f"{diff // 86400}d ago"
        except Exception:
            stats['drive_last_sync_human'] = 'Synced'
    else:
        stats['drive_last_sync_human'] = 'Pending'

    if syncthing_module:
        stats['syncthing_device_id'] = syncthing_module.get_syncthing_device_id()
    else:
        stats['syncthing_device_id'] = ""

    stats['syncthing_port'] = int(os.environ.get('SYNCTHING_PORT', 8384))
    stats['syncthing_folder_id'] = os.environ.get('SYNCTHING_SHARED_FOLDER_ID', 'shared')
    stats['syncthing_folder_label'] = os.environ.get('SYNCTHING_SHARED_FOLDER_LABEL', 'Shared')

    return stats
