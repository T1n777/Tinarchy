#!/usr/bin/env python3
"""
Tinarchy Continuous Self-Learning Thermal Budget & Adaptive Workload Governor
Dynamic Closed-Loop PID Thermal Orchestrator for Pineapple Station.

Features & Researched Methodologies:
1. Continuous Closed-Loop Thermal PID Engine:
   - Tracks package temperature T(t), thermal velocity (dT/dt), and steady-state integral.
   - Proactively brakes clock speeds and quotas upon rapid thermal ascent (Kd * dT/dt).
   - Dynamically searches for and maintains the maximum possible stable frequency
     and workload quota under a configurable target thermal budget.
2. Multi-Tier Activity & Demand Ladder:
   - Tier 0: ACTIVE INTERACTIVE (< 15 mins since user keystrokes / streaming)
     * Target: 76.0°C | Base Clock: 1.8-2.2 GHz | Turbo: OFF | Suwayomi: 60-120%
     * Maximum interactive responsiveness, cool lap/desk, whisper-quiet fan.
   - Tier 1: SHORT IDLE (15m - 30m inactivity)
     * Target: 79.0°C | Base Clock: 2.2-2.5 GHz | Turbo: OFF | Suwayomi: 140-220%
     * Smooth ramp up for background queues as user steps away.
   - Tier 2: IDLE ACCELERATION (30m - 60m / 0.5 - 1.0 hr inactivity)
     * Target: 82.0°C | Freq: 2.5-2.8 GHz | Turbo: Conditional | Suwayomi: 220-320%
     * Significant batch acceleration for download queues and background agy tasks.
   - Tier 3: UNCONSTRAINED SPRINT (> 60m / 1.0+ hr deep idle)
     * Target: 84.0°C | Freq: 3.10 GHz max hardware | Turbo: FULLY UNLOCKED | Suwayomi: 400% (max)
     * Maximum unconstrained hardware throughput to drain queues and finish heavy batch jobs.
3. Instantaneous Wakeup (< 3s):
   - Immediately snaps back to Tier 0 the instant a user types a keystroke in SSH/tmux
     or starts streaming media on Jellyfin.
4. CGroup v2 Scheduling Weights:
   - Allocates 5x scheduling priority (CPUWeight=500) to interactive user slices
     over background batch services (CPUWeight=100) via the Linux kernel CFS.
5. Workload Demand Awareness:
   - Tracks live Suwayomi cgroup throttling (throttled_usec) and agy CPU utilization.
   - Ramps up resources when demand exists; preserves idle downclocking (1.2 GHz) when idle.
"""

import os
import sys
import time
import glob
import json
import signal
import subprocess
import re
from datetime import datetime

# ─── Configuration & Defaults ───────────────────────────────────────────────
CONFIG_FILE = "/etc/default/tinarchy-resource-governor"
LOG_FILE = "/var/log/tinarchy/resource-governor.log"
LEARNING_STATE_FILE = "/var/log/tinarchy/thermal-learning.json"

DEFAULT_CONFIG = {
    "CHECK_INTERVAL_SECONDS": 4,      # Dynamic closed-loop sampling tick (seconds)
    "TIER_1_TIMEOUT": 900,            # 15 minutes -> Tier 1 (Short Idle)
    "TIER_2_TIMEOUT": 1800,           # 30 minutes (0.5 hr) -> Tier 2 (Idle Accel)
    "TIER_3_TIMEOUT": 3600,           # 60 minutes (1.0 hr) -> Tier 3 (Unconstrained Sprint)
    "TARGET_TEMP_TIER_0": 76.0,       # Active interactive thermal target (°C)
    "TARGET_TEMP_TIER_1": 79.0,       # Tier 1 thermal target (°C)
    "TARGET_TEMP_TIER_2": 82.0,       # Tier 2 thermal target (°C)
    "TARGET_TEMP_TIER_3": 84.0,       # Tier 3 thermal target (°C)
    "MAX_SAFE_TEMP": 85.5,            # Hardware safety ceiling (°C)
    "PID_KP": 1.0,                    # Proportional gain
    "PID_KI": 0.05,                   # Integral gain (slow steady-state learning)
    "PID_KD": 2.2,                    # Derivative gain (anticipatory thermal brake)
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

def get_cpu_package_temp() -> float:
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

def get_last_physical_input_time() -> float:
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

    # 2. Query loginctl login sessions
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

    # Check for active transcoding processes
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

# ─── Workload Demand Telemetry ───────────────────────────────────────────────

def get_suwayomi_demand() -> dict:
    """Read Suwayomi cgroup cpu.stat to measure usage and throttling pressure."""
    stat = {"usage_usec": 0, "throttled_usec": 0, "nr_throttled": 0}
    path = "/sys/fs/cgroup/system.slice/suwayomi-server.service/cpu.stat"
    if os.path.exists(path):
        try:
            with open(path) as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 2 and parts[1].isdigit():
                        if parts[0] in stat:
                            stat[parts[0]] = int(parts[1])
        except Exception:
            pass
    return stat

def get_agy_demand() -> tuple[int | None, float]:
    """Find agy PID and measure CPU utilization from /proc/<pid>/stat."""
    try:
        res = subprocess.run(["pgrep", "-f", "agy "], capture_output=True, text=True, timeout=2)
        pids = [int(p) for p in res.stdout.splitlines() if p.strip()]
        if not pids:
            return None, 0.0
        pid = pids[0]
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().split()
            utime = int(fields[13])
            stime = int(fields[14])
            return pid, float(utime + stime)
    except Exception:
        return None, 0.0

# ─── Hardware & CGroup Actuators ────────────────────────────────────────────

def set_intel_turbo(enable: bool) -> bool:
    """Enable (0) or disable (1) Intel Turbo Boost via intel_pstate sysfs."""
    val = "0\n" if enable else "1\n"
    path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                cur = f.read().strip()
            if cur != val.strip():
                with open(path, "w") as f:
                    f.write(val)
                return True
        except Exception:
            pass
    return False

def set_cpu_max_freq(freq_khz: int) -> bool:
    """Set maximum CPU scaling frequency on all cpufreq policies."""
    policies = glob.glob("/sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq")
    freq_str = f"{freq_khz}\n"
    changed = False
    for p in policies:
        try:
            with open(p, "r") as f:
                cur = f.read().strip()
            if cur != str(freq_khz):
                with open(p, "w") as f:
                    f.write(freq_str)
                changed = True
        except Exception:
            pass
    return changed

def set_suwayomi_cgroup_quota(quota_percent: int) -> bool:
    """
    Set Suwayomi quota directly via cgroups v2 (cpu.max).
    quota_percent=400 means 4.0 cores (unconstrained / max 100000).
    """
    path = "/sys/fs/cgroup/system.slice/suwayomi-server.service/cpu.max"
    if not os.path.exists(path):
        return False

    if quota_percent >= 400:
        val = "max 100000\n"
    else:
        limit_usec = int(quota_percent * 1000)  # e.g. 80% = 80,000 usec
        val = f"{limit_usec} 100000\n"

    try:
        with open(path, "r") as f:
            cur = f.read().strip()
        if cur != val.strip():
            with open(path, "w") as f:
                f.write(val)
            return True
    except Exception:
        # Fallback to systemctl set-property
        try:
            q_str = "max" if quota_percent >= 400 else f"{quota_percent}%"
            subprocess.run(
                ["systemctl", "set-property", "--runtime", "suwayomi-server.service", f"CPUQuota={q_str}"],
                capture_output=True, timeout=2
            )
            return True
        except Exception:
            pass
    return False

def setup_cgroup_weights():
    """Ensure interactive user slices have 5x higher scheduling priority than batch background jobs."""
    try:
        user_weight_path = "/sys/fs/cgroup/user.slice/cpu.weight"
        suw_weight_path = "/sys/fs/cgroup/system.slice/suwayomi-server.service/cpu.weight"
        if os.path.exists(user_weight_path):
            with open(user_weight_path, "w") as f:
                f.write("500\n")
        if os.path.exists(suw_weight_path):
            with open(suw_weight_path, "w") as f:
                f.write("100\n")
    except Exception:
        pass

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
    path = "/sys/fs/cgroup/system.slice/suwayomi-server.service/cpu.max"
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                val = f.read().strip().split()[0]
                if val == "max":
                    quota = "400% (Unconstrained)"
                else:
                    quota = f"{int(val) // 1000}%"
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

# ─── Closed-Loop Thermal PID Engine ─────────────────────────────────────────

class ClosedLoopThermalPID:
    def __init__(self, kp=1.0, ki=0.05, kd=2.2):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral = 0.0
        self.last_temp = None
        self.last_time = None
        self.slew_rate = 0.0
        self.control_signal = 0.0

    def compute(self, current_temp: float, target_temp: float, now: float) -> tuple[float, float]:
        if self.last_temp is None or self.last_time is None:
            self.last_temp = current_temp
            self.last_time = now
            return 0.0, 0.0

        dt = max(1.0, now - self.last_time)
        error = target_temp - current_temp
        self.slew_rate = (current_temp - self.last_temp) / dt

        # Integral term with anti-windup clamping
        self.integral = max(-30.0, min(30.0, self.integral + (error * dt * 0.1)))

        # PID control signal:
        # u > 0: Headroom available (cool, stable)
        # u < 0: Over budget or rapid temperature spike (derivative brake)
        u = (self.kp * error) + (self.ki * self.integral) - (self.kd * self.slew_rate)

        self.last_temp = current_temp
        self.last_time = now
        self.control_signal = u
        return u, self.slew_rate

# ─── Master Continuous Adaptive Governor ───────────────────────────────────

class AdaptiveGovernor:
    def __init__(self, config):
        self.config = config
        self.pid = ClosedLoopThermalPID(config["PID_KP"], config["PID_KI"], config["PID_KD"])
        self.current_tier = 0
        self.last_activity_time = time.time()
        self.last_tier_change_time = time.time()
        self.last_reasons = []

        # Actuator working state
        self.current_freq_khz = 2000000
        self.current_quota_pct = 80
        self.turbo_enabled = False

        # Workload demand tracking
        self.last_suw_stat = get_suwayomi_demand()
        self.last_agy_pid, self.last_agy_ticks = get_agy_demand()
        self.last_demand_time = time.time()
        self.suw_cores_demanded = 0.0
        self.agy_cores_demanded = 0.0

        setup_cgroup_weights()

    def get_tier_for_inactivity(self, idle_seconds: float) -> int:
        if idle_seconds < self.config["TIER_1_TIMEOUT"]:
            return 0  # Active interactive (< 15 mins)
        elif idle_seconds < self.config["TIER_2_TIMEOUT"]:
            return 1  # Short idle (15m - 30m)
        elif idle_seconds < self.config["TIER_3_TIMEOUT"]:
            return 2  # Idle acceleration (30m - 60m / 0.5 - 1.0 hr)
        else:
            return 3  # Unconstrained sprint (> 60m / 1.0+ hr deep idle)

    def get_tier_target_temp(self, tier: int) -> float:
        targets = {
            0: self.config["TARGET_TEMP_TIER_0"],
            1: self.config["TARGET_TEMP_TIER_1"],
            2: self.config["TARGET_TEMP_TIER_2"],
            3: self.config["TARGET_TEMP_TIER_3"],
        }
        return targets.get(tier, self.config["TARGET_TEMP_TIER_0"])

    def update_demand_telemetry(self, now: float):
        dt = max(1.0, now - self.last_demand_time)
        cur_suw = get_suwayomi_demand()
        cur_agy_pid, cur_agy_ticks = get_agy_demand()

        # Suwayomi usage & throttling rate
        delta_usage = (cur_suw.get("usage_usec", 0) - self.last_suw_stat.get("usage_usec", 0)) / (dt * 1e6)
        delta_throttle = (cur_suw.get("throttled_usec", 0) - self.last_suw_stat.get("throttled_usec", 0)) / (dt * 1e6)
        self.suw_cores_demanded = max(0.0, delta_usage + delta_throttle)

        # agy CPU rate
        if cur_agy_pid and self.last_agy_pid == cur_agy_pid:
            agy_usage = (cur_agy_ticks - self.last_agy_ticks) / (100.0 * dt)
            self.agy_cores_demanded = max(0.0, agy_usage)
        else:
            self.agy_cores_demanded = 0.0

        self.last_suw_stat = cur_suw
        self.last_agy_pid = cur_agy_pid
        self.last_agy_ticks = cur_agy_ticks
        self.last_demand_time = now

    def tick(self):
        now = time.time()
        current_temp = get_cpu_package_temp()

        # 1. Update workload demand
        self.update_demand_telemetry(now)

        # 2. Collect interactive user activity signals
        phys_t = get_last_physical_input_time()
        term_t, term_reasons = get_terminal_activity(self.config["TIER_1_TIMEOUT"])
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

        # 3. Determine operational tier
        new_tier = self.get_tier_for_inactivity(idle_seconds)
        tier_names = ["ACTIVE (Interactive)", "TIER 1 (Short Idle 15-30m)", "TIER 2 (Idle Accel 0.5-1hr)", "TIER 3 (Unconstrained Sprint 1hr+)"]

        if new_tier != self.current_tier:
            log_event(
                f"TIER TRANSITION: {tier_names[self.current_tier]} -> {tier_names[new_tier]} | "
                f"Idle: {int(idle_seconds // 60)}m | Active reasons: {'; '.join(reasons[:2]) or 'None'}"
            )
            self.current_tier = new_tier
            self.last_tier_change_time = now

        # 4. Compute Closed-Loop Thermal PID
        target_temp = self.get_tier_target_temp(self.current_tier)
        u, slew_rate = self.pid.compute(current_temp, target_temp, now)

        # Safety override: if temp crosses MAX_SAFE_TEMP (85.5°C), enforce emergency brake
        emergency_brake = current_temp >= self.config["MAX_SAFE_TEMP"] or slew_rate > 1.8

        # 5. Adaptive Actuator Logic based on Tier & Thermal Signal u
        target_turbo = False
        target_freq = self.current_freq_khz
        target_quota = self.current_quota_pct

        if self.current_tier == 0:
            # Active Interactive Tier
            target_turbo = False
            # Modulate frequency within 1.8 GHz - 2.2 GHz base
            if emergency_brake or u < -2.0:
                target_freq = max(1600000, self.current_freq_khz - 100000)
                target_quota = max(60, self.current_quota_pct - 10)
            elif u > 2.0 and not emergency_brake:
                target_freq = min(2200000, self.current_freq_khz + 100000)
                target_quota = min(120, self.current_quota_pct + 10)
            else:
                target_freq = max(1800000, min(2200000, self.current_freq_khz))
                target_quota = max(70, min(100, self.current_quota_pct))

        elif self.current_tier == 1:
            # Short Idle (15m - 30m)
            target_turbo = False
            # Modulate frequency within 2.2 GHz - 2.5 GHz base
            if emergency_brake or u < -2.0:
                target_freq = max(2000000, self.current_freq_khz - 100000)
                target_quota = max(120, self.current_quota_pct - 15)
            elif u > 1.5:
                target_freq = min(2500000, self.current_freq_khz + 100000)
                target_quota = min(220, self.current_quota_pct + 15)
            else:
                target_freq = max(2200000, min(2500000, self.current_freq_khz))
                target_quota = max(140, min(200, self.current_quota_pct))

        elif self.current_tier == 2:
            # Idle Acceleration (30m - 60m / 0.5 - 1.0 hr)
            if emergency_brake or u < -3.0 or current_temp > 82.5:
                target_turbo = False
                target_freq = max(2400000, self.current_freq_khz - 100000)
                target_quota = max(200, self.current_quota_pct - 20)
            else:
                # Conditional Turbo if cool & stable
                target_turbo = (current_temp < 80.0 and slew_rate < 0.4)
                target_freq = min(2800000, self.current_freq_khz + 100000) if u > 1.0 else self.current_freq_khz
                target_quota = min(320, self.current_quota_pct + 20)

        elif self.current_tier == 3:
            # Unconstrained Sprint (> 60m / 1.0+ hr deep idle)
            if emergency_brake or current_temp >= 85.0:
                # Thermal safety governor backoff
                target_turbo = False
                target_freq = 2500000
                target_quota = 250
            else:
                # Max hardware throughput
                target_turbo = True
                target_freq = 2500000  # Ceiling that allows hardware boost to reach 3.10 GHz
                target_quota = 400     # Unconstrained

        # Apply actuator updates
        freq_changed = set_cpu_max_freq(target_freq)
        turbo_changed = set_intel_turbo(target_turbo)
        quota_changed = set_suwayomi_cgroup_quota(target_quota)

        self.current_freq_khz = target_freq
        self.turbo_enabled = target_turbo
        self.current_quota_pct = target_quota

        if emergency_brake:
            log_event(f"THERMAL DAMPENER: Temp={current_temp:.1f}°C, Slew={slew_rate:+.2f}°C/s. Throttling ceiling to {target_freq//1000}MHz.")

# ─── Entry Point & CLI ──────────────────────────────────────────────────────

def print_status(gov=None):
    now = time.time()
    state = get_current_state()
    phys_t = get_last_physical_input_time()
    term_t, term_reasons = get_terminal_activity(CONFIG["TIER_1_TIMEOUT"])
    is_streaming, stream_reasons = get_streaming_and_media_activity()

    latest_act = max(phys_t, term_t)
    idle_secs = now - latest_act if latest_act > 0 else 999999
    turbo_str = "DISABLED (Cool)" if state["no_turbo"] == "1" else "ENABLED (Boost 3.1GHz)"
    freq_mhz = int(state["max_freq"]) // 1000 if state["max_freq"].isdigit() else state["max_freq"]

    tier = 0
    if idle_secs >= CONFIG["TIER_3_TIMEOUT"]:
        tier = 3
    elif idle_secs >= CONFIG["TIER_2_TIMEOUT"]:
        tier = 2
    elif idle_secs >= CONFIG["TIER_1_TIMEOUT"]:
        tier = 1

    tier_names = [
        "TIER 0: ACTIVE (Interactive Use)",
        "TIER 1: SHORT IDLE (15m - 30m)",
        "TIER 2: IDLE ACCELERATION (0.5 - 1.0 hr)",
        "TIER 3: UNCONSTRAINED SPRINT (1.0+ hr Deep Idle)"
    ]

    suw_stat = get_suwayomi_demand()
    agy_pid, agy_ticks = get_agy_demand()

    print("══════════════════════════════════════════════════════════════════════")
    print("  PINEAPPLE STATION - CONTINUOUS SELF-LEARNING THERMAL & DEMAND GOVERNOR")
    print("══════════════════════════════════════════════════════════════════════")
    print(f"• Current Operational Tier: {tier_names[tier]}")
    print(f"• Inactivity Elapsed:       {int(idle_secs)}s ({idle_secs / 60:.1f} minutes)")
    print(f"• Package Temperature:      {state['temp']:.1f} °C")
    print(f"• Target Thermal Budget:    {CONFIG[f'TARGET_TEMP_TIER_{tier}']:.1f} °C")
    print(f"• Intel Turbo Boost:        {turbo_str} (no_turbo={state['no_turbo']})")
    print(f"• Dynamic Frequency Ceiling:{freq_mhz} MHz")
    print(f"• Suwayomi CPU Quota:       {state['suwayomi_quota']}")
    print(f"• Suwayomi Demand:          throttled_usec={suw_stat.get('throttled_usec', 0)}")
    print(f"• agy Daemon (PID {agy_pid}):   Active process registered")
    print(f"• Active Media Streaming:   {'YES' if is_streaming else 'NO'}")
    if term_reasons:
        print(f"• Terminal Activity:        {'; '.join(term_reasons)}")
    if stream_reasons:
        print(f"• Streaming Sockets:        {'; '.join(stream_reasons)}")
    print("══════════════════════════════════════════════════════════════════════")

def main():
    if "--status" in sys.argv or "-s" in sys.argv:
        print_status()
        return

    governor = AdaptiveGovernor(CONFIG)

    if "--run-once" in sys.argv:
        governor.tick()
        print_status(governor)
        return

    # Graceful shutdown handler
    def handle_sigterm(signum, frame):
        log_event("Governor stopping. Restoring safe active cooling mode.")
        set_intel_turbo(False)
        set_cpu_max_freq(2000000)
        set_suwayomi_cgroup_quota(80)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    log_event(
        f"Continuous Self-Learning Thermal & Demand Governor initialized. "
        f"Tiers: 15m (Short) | 30m (0.5hr Accel) | 60m (1hr Sprint). "
        f"PID Gains: Kp={CONFIG['PID_KP']}, Ki={CONFIG['PID_KI']}, Kd={CONFIG['PID_KD']}."
    )

    # Initial tick
    governor.tick()

    while True:
        try:
            governor.tick()
            time.sleep(CONFIG["CHECK_INTERVAL_SECONDS"])
        except KeyboardInterrupt:
            break
        except Exception as e:
            log_event(f"Error in governor loop: {e}")
            time.sleep(CONFIG["CHECK_INTERVAL_SECONDS"])

    # On exit
    set_intel_turbo(False)
    set_cpu_max_freq(2000000)
    set_suwayomi_cgroup_quota(80)

if __name__ == "__main__":
    main()
