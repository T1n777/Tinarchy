#!/usr/bin/env python3
"""
Tinarchy Universal Autonomous Activity & Resource Governor
Dynamically balances system thermals, interactive responsiveness,
and batch processing throughput for Pineapple Station.

Operational Principles:
1. ACTIVE MODE (Interactive use / Recent activity within 15 mins):
   - Background batch services (Suwayomi) constrained (CPUQuota=80%).
   - Intel Turbo Boost disabled (no_turbo=1) and CPU capped at base clock (2.0 GHz).
   - Keeps thermals calm (~60°C–75°C) and prevents single-core hotspotting from agy / SSH.
2. IDLE MODE (15 minutes of low traffic and zero user interaction):
   - Background batch services uncapped (CPUQuota=400% / unthrottled).
   - Intel Turbo Boost enabled (no_turbo=0) allowing hardware boost up to 3.10 GHz.
   - Batch workloads (manga scraping, transcodes, indexing) complete as fast as possible.
3. INSTANT WAKEUP:
   - Immediately reverts to ACTIVE MODE the instant user keystrokes, SSH logins,
     or media streaming sessions are detected.
4. AUTONOMOUS THERMAL GUARD:
   - In IDLE MODE, if CPU package temp reaches >= 85°C, automatically steps back
     Turbo Boost until temperatures fall below 75°C to protect laptop hardware.
"""

import os
import sys
import time
import glob
import signal
import subprocess
import re
from datetime import datetime

# ─── Configuration & Defaults ───────────────────────────────────────────────
CONFIG_FILE = "/etc/default/tinarchy-resource-governor"
LOG_FILE = "/var/log/tinarchy/resource-governor.log"

DEFAULT_CONFIG = {
    "IDLE_TIMEOUT_SECONDS": 900,       # 15 minutes
    "CHECK_INTERVAL_SECONDS": 5,       # Polling loop cycle in seconds
    "ACTIVE_SUWAYOMI_QUOTA": "80%",    # Throttled quota during active use
    "IDLE_SUWAYOMI_QUOTA": "400%",     # Uncapped quota during idle (all 4 cores)
    "ACTIVE_MAX_FREQ": "2000000",      # 2.00 GHz base ceiling
    "IDLE_MAX_FREQ": "2500000",        # 2.50 GHz ceiling (unlocks 3.10 GHz boost)
    "THERMAL_SAFETY_TEMP": 85.0,       # Step-down trip point in idle mode (°C)
    "THERMAL_RESUME_TEMP": 75.0,       # Recovery temperature (°C)
}

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("\"'")
                        if k in cfg:
                            if isinstance(DEFAULT_CONFIG[k], int):
                                cfg[k] = int(v)
                            elif isinstance(DEFAULT_CONFIG[k], float):
                                cfg[k] = float(v)
                            else:
                                cfg[k] = v
        except Exception as e:
            print(f"Warning: Failed to parse {CONFIG_FILE}: {e}")
    return cfg

CONFIG = load_config()

# ─── System Telemetry Functions ─────────────────────────────────────────────

def get_cpu_package_temp():
    """Read CPU package temperature directly from sysfs (Celsius)."""
    temps = []
    for f in glob.glob("/sys/devices/platform/coretemp.*/hwmon/hwmon*/temp*_input"):
        try:
            with open(f, "r") as fp:
                temps.append(int(fp.read().strip()) / 1000.0)
        except Exception:
            pass
    if not temps:
        for f in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
            try:
                with open(f, "r") as fp:
                    temps.append(int(fp.read().strip()) / 1000.0)
            except Exception:
                pass
    return max(temps) if temps else 0.0

def get_last_physical_input_time():
    """Check physical hardware event devices (keyboard/touchpad/mouse)."""
    last_t = 0.0
    for dev in glob.glob("/dev/input/event*"):
        try:
            st = os.stat(dev)
            last_t = max(last_t, st.st_atime, st.st_mtime)
        except Exception:
            pass
    return last_t

def get_terminal_activity(threshold_secs=900):
    """
    Check interactive user terminal activity:
    - Attached tmux client keystrokes (tmux list-clients)
    - Active login session pseudo-terminals (loginctl + /dev/pts/*)
    """
    now = time.time()
    last_t = 0.0
    reasons = []

    # 1. Query tmux client activity timestamp (epoch seconds of last keypress/mouse)
    try:
        res = subprocess.run(
            ["tmux", "list-clients", "-F", "#{client_name} #{client_activity}"],
            capture_output=True, text=True, timeout=2
        )
        for line in res.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) == 2 and parts[1].isdigit():
                act = float(parts[1])
                if act > last_t:
                    last_t = act
                if (now - act) < threshold_secs:
                    reasons.append(f"tmux client {parts[0]} active {int(now - act)}s ago")
    except Exception:
        pass

    # 2. Query loginctl login sessions to find real interactive user ttys/ptys
    login_ptys = set()
    try:
        res = subprocess.run(
            ["loginctl", "list-sessions", "--no-legend"],
            capture_output=True, text=True, timeout=2
        )
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 7:
                tty = parts[6]
                if tty.startswith("pts/") or tty.startswith("tty"):
                    login_ptys.add(tty)
    except Exception:
        pass

    # 3. Check access time (st_atime) and modify time (st_mtime) of user login ptys
    for tty in login_ptys:
        pty_path = f"/dev/{tty}"
        if os.path.exists(pty_path):
            try:
                st = os.stat(pty_path)
                act = max(st.st_atime, st.st_mtime)
                if act > last_t:
                    last_t = act
                if (now - act) < threshold_secs:
                    reasons.append(f"TTY {tty} active {int(now - act)}s ago")
            except Exception:
                pass

    return last_t, reasons

def get_streaming_and_media_activity():
    """
    Detect active media streaming or interactive client web connections:
    - Established sockets to Jellyfin (8096, 8095), Nginx Web UI (443, 80), FileBrowser (8085)
    - Active ffmpeg / jellyfin-ffmpeg transcoding processes
    """
    active = False
    reasons = []

    # Check for active hardware / software transcoding
    try:
        res = subprocess.run(["pgrep", "-x", "ffmpeg"], capture_output=True, text=True, timeout=2)
        pids = [p.strip() for p in res.stdout.splitlines() if p.strip()]
        if pids:
            active = True
            reasons.append(f"FFmpeg transcoding active (PIDs: {', '.join(pids)})")
    except Exception:
        pass

    # Check established incoming sockets on interactive server ports
    ports_filter = "( sport = :8096 or sport = :8095 or sport = :443 or sport = :80 or sport = :8085 )"
    try:
        res = subprocess.run(
            ["ss", "-tin", "state", "established", ports_filter],
            capture_output=True, text=True, timeout=2
        )
        lines = [l for l in res.stdout.splitlines() if l.strip()]
        for i in range(0, len(lines), 2):
            if i + 1 < len(lines):
                hdr = lines[i]
                info = lines[i + 1]
                m_rcv = re.search(r"lastrcv:(\d+)", info)
                m_snd = re.search(r"lastsnd:(\d+)", info)
                rcv_ms = int(m_rcv.group(1)) if m_rcv else 999999
                snd_ms = int(m_snd.group(1)) if m_snd else 999999
                # If packets were exchanged within the last 30 seconds
                if min(rcv_ms, snd_ms) < 30000:
                    active = True
                    reasons.append(f"Client stream socket active: {hdr.split()[3]} -> {hdr.split()[4]}")
    except Exception:
        pass

    return active, reasons

# ─── Hardware & CGroup Actuators ────────────────────────────────────────────

def set_intel_turbo(enable: bool):
    """Enable (0) or disable (1) Intel Turbo Boost via intel_pstate sysfs."""
    val = "0\n" if enable else "1\n"
    path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
    if os.path.exists(path):
        try:
            with open(path, "w") as f:
                f.write(val)
            return True
        except Exception as e:
            print(f"Error setting no_turbo={val.strip()}: {e}")
    return False

def set_cpu_max_freq(freq_khz: str):
    """Set maximum CPU scaling frequency on all cpufreq policies."""
    policies = glob.glob("/sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq")
    success = False
    for p in policies:
        try:
            with open(p, "w") as f:
                f.write(f"{freq_khz}\n")
            success = True
        except Exception:
            pass
    if not success:
        try:
            subprocess.run(["cpupower", "frequency-set", "-u", freq_khz], capture_output=True)
            success = True
        except Exception:
            pass
    return success

def set_suwayomi_quota(quota_str: str):
    """Set runtime CPUQuota on suwayomi-server.service via systemd."""
    try:
        subprocess.run(
            ["systemctl", "set-property", "--runtime", "suwayomi-server.service", f"CPUQuota={quota_str}"],
            check=True, capture_output=True, text=True
        )
        return True
    except Exception as e:
        print(f"Error setting Suwayomi CPUQuota to {quota_str}: {e}")
        return False

def get_current_state():
    """Retrieve current operational and hardware state."""
    no_turbo = "unknown"
    if os.path.exists("/sys/devices/system/cpu/intel_pstate/no_turbo"):
        try:
            with open("/sys/devices/system/cpu/intel_pstate/no_turbo", "r") as f:
                no_turbo = f.read().strip()
        except Exception:
            pass

    max_freq = "unknown"
    if os.path.exists("/sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq"):
        try:
            with open("/sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq", "r") as f:
                max_freq = f.read().strip()
        except Exception:
            pass

    quota = "unknown"
    try:
        res = subprocess.run(
            ["systemctl", "show", "suwayomi-server.service", "-p", "CPUQuotaPerSecUSec"],
            capture_output=True, text=True, timeout=2
        )
        val = res.stdout.strip().split("=")[-1]
        quota = val if val else "none"
    except Exception:
        pass

    return {
        "no_turbo": no_turbo,
        "max_freq": max_freq,
        "suwayomi_quota": quota,
        "temp": get_cpu_package_temp()
    }

def log_event(message):
    """Log an event with timestamp to the Tinarchy log file and stdout."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] {message}"
    print(log_line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(log_line + "\n")
    except Exception:
        pass

# ─── Governor Engine ────────────────────────────────────────────────────────

class ResourceGovernor:
    def __init__(self, config):
        self.config = config
        self.current_mode = None
        self.thermal_braked = False
        self.last_activity_time = time.time()
        self.last_transition_time = time.time()
        self.last_reasons = []

    def transition_to(self, mode: str, reason: str = ""):
        if self.current_mode == mode:
            return

        prev = self.current_mode or "INIT"
        self.current_mode = mode
        self.last_transition_time = time.time()

        if mode == "ACTIVE":
            self.thermal_braked = False
            set_suwayomi_quota(self.config["ACTIVE_SUWAYOMI_QUOTA"])
            set_intel_turbo(False)
            set_cpu_max_freq(self.config["ACTIVE_MAX_FREQ"])
            log_event(f"MODE TRANSITION: {prev} -> ACTIVE | Reason: {reason} | Suwayomi={self.config['ACTIVE_SUWAYOMI_QUOTA']}, Turbo=OFF, FreqMax=2.0GHz")

        elif mode == "IDLE_PERF":
            self.thermal_braked = False
            set_suwayomi_quota(self.config["IDLE_SUWAYOMI_QUOTA"])
            set_intel_turbo(True)
            set_cpu_max_freq(self.config["IDLE_MAX_FREQ"])
            log_event(f"MODE TRANSITION: {prev} -> IDLE_PERF | Reason: {reason} | Suwayomi={self.config['IDLE_SUWAYOMI_QUOTA']}, Turbo=ON, FreqMax=3.1GHz")

        elif mode == "IDLE_THERMAL_BRAKE":
            self.thermal_braked = True
            set_intel_turbo(False)
            set_cpu_max_freq("2200000")
            set_suwayomi_quota("200%")
            log_event(f"THERMAL GUARD ENGAGED: Temp reached safety limit. Stepping down Turbo until cools to {self.config['THERMAL_RESUME_TEMP']}°C")

    def tick(self):
        now = time.time()
        temp = get_cpu_package_temp()

        # Collect activity signals
        phys_t = get_last_physical_input_time()
        term_t, term_reasons = get_terminal_activity(self.config["IDLE_TIMEOUT_SECONDS"])
        is_streaming, stream_reasons = get_streaming_and_media_activity()

        latest_input = max(phys_t, term_t)
        if latest_input > self.last_activity_time:
            self.last_activity_time = latest_input

        if is_streaming:
            self.last_activity_time = now

        idle_seconds = now - self.last_activity_time
        reasons = []
        if term_reasons:
            reasons.extend(term_reasons)
        if stream_reasons:
            reasons.extend(stream_reasons)
        self.last_reasons = reasons

        # ── State Machine Logic ──
        if is_streaming or idle_seconds < self.config["IDLE_TIMEOUT_SECONDS"]:
            # Active interactive use
            trigger_reason = f"Active activity detected (idle: {int(idle_seconds)}s / {self.config['IDLE_TIMEOUT_SECONDS']}s)"
            if reasons:
                trigger_reason += f" [{'; '.join(reasons[:2])}]"
            self.transition_to("ACTIVE", trigger_reason)
        else:
            # Idle for >= IDLE_TIMEOUT_SECONDS
            if not self.thermal_braked:
                if temp >= self.config["THERMAL_SAFETY_TEMP"]:
                    self.transition_to("IDLE_THERMAL_BRAKE", f"Temp={temp:.1f}°C >= {self.config['THERMAL_SAFETY_TEMP']}°C")
                else:
                    self.transition_to("IDLE_PERF", f"System idle for {int(idle_seconds // 60)}m (timeout={int(self.config['IDLE_TIMEOUT_SECONDS'] // 60)}m)")
            else:
                # In thermal brake, check if cooled down below recovery threshold
                if temp <= self.config["THERMAL_RESUME_TEMP"]:
                    self.transition_to("IDLE_PERF", f"Cooled to {temp:.1f}°C <= {self.config['THERMAL_RESUME_TEMP']}°C, resuming full performance")

# ─── Entry Point & CLI ──────────────────────────────────────────────────────

def print_status(gov=None):
    now = time.time()
    state = get_current_state()
    phys_t = get_last_physical_input_time()
    term_t, term_reasons = get_terminal_activity(CONFIG["IDLE_TIMEOUT_SECONDS"])
    is_streaming, stream_reasons = get_streaming_and_media_activity()

    latest_act = max(phys_t, term_t)
    idle_secs = now - latest_act if latest_act > 0 else 999999
    turbo_str = "DISABLED (Cool)" if state["no_turbo"] == "1" else "ENABLED (Boost)"
    freq_mhz = int(state["max_freq"]) // 1000 if state["max_freq"].isdigit() else state["max_freq"]

    print("══════════════════════════════════════════════════════════════════════")
    print("      PINEAPPLE STATION - AUTONOMOUS RESOURCE & ACTIVITY GOVERNOR     ")
    print("══════════════════════════════════════════════════════════════════════")
    print(f"• Current CPU Temp:       {state['temp']:.1f} °C")
    print(f"• Intel Turbo Boost:      {turbo_str} (no_turbo={state['no_turbo']})")
    print(f"• Max Frequency Ceiling:  {freq_mhz} MHz")
    print(f"• Suwayomi CPU Quota:     {state['suwayomi_quota']}")
    print(f"• Inactivity Elapsed:     {int(idle_secs)}s ({idle_secs / 60:.1f} minutes)")
    print(f"• Idle Threshold:         {CONFIG['IDLE_TIMEOUT_SECONDS']}s ({CONFIG['IDLE_TIMEOUT_SECONDS'] / 60:.1f} minutes)")
    print(f"• Active Media Streaming: {'YES' if is_streaming else 'NO'}")
    if term_reasons:
        print(f"• Terminal Activity:      {'; '.join(term_reasons)}")
    if stream_reasons:
        print(f"• Streaming Sockets:      {'; '.join(stream_reasons)}")
    print("══════════════════════════════════════════════════════════════════════")

def main():
    if "--status" in sys.argv or "-s" in sys.argv:
        print_status()
        return

    governor = ResourceGovernor(CONFIG)

    if "--run-once" in sys.argv:
        governor.tick()
        print_status(governor)
        return

    # Graceful shutdown handler
    def handle_sigterm(signum, frame):
        log_event("Governor stopping. Safely restoring ACTIVE cool mode.")
        governor.transition_to("ACTIVE", "Service termination")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    log_event(f"Autonomous Resource Governor started. Inactivity threshold: {CONFIG['IDLE_TIMEOUT_SECONDS']}s ({CONFIG['IDLE_TIMEOUT_SECONDS'] // 60}m).")

    # Initial tick
    governor.tick()

    while True:
        try:
            governor.tick()
            time.sleep(CONFIG["CHECK_INTERVAL_SECONDS"])
        except KeyboardInterrupt:
            break
        except Exception as e:
            log_event(f"Error in governor cycle: {e}")
            time.sleep(CONFIG["CHECK_INTERVAL_SECONDS"])

    governor.transition_to("ACTIVE", "Shutdown")

if __name__ == "__main__":
    main()
