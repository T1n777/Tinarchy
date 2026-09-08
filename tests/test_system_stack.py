#!/usr/bin/env python3
"""
Tinarchy Server Comprehensive Verification & Test Suite
Runs validation across Python code syntax, systemd services, Nginx, SSH,
Resource Governor PID telemetry, Network packet steering, RAM/ZRAM,
and Web API endpoints.
"""

import subprocess
import sys
import json
import urllib.request
import os

tests = []

def run_test(name, fn):
    try:
        fn()
        print(f"✅ PASS: {name}")
        tests.append((name, True, ""))
    except Exception as e:
        print(f"❌ FAIL: {name} -> {e}")
        tests.append((name, False, str(e)))

# 1. Python Syntax
def test_py_syntax():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    targets = [
        os.path.join(root, "server.py"),
        os.path.join(root, "configs", "scripts", "tinarchy-resource-governor.py"),
        os.path.join(root, "configs", "scripts", "tinarchy-net-autotune.py")
    ]
    for f in targets:
        if os.path.exists(f):
            res = subprocess.run(["python3", "-m", "py_compile", f], capture_output=True, text=True)
            if res.returncode != 0:
                raise Exception(f"{f} syntax error: {res.stderr}")
run_test("Python Scripts Syntax Compilation", test_py_syntax)

# 2. Systemd Services
SERVICES = [
    "tinarchy.service",
    "tinarchy-resource-governor.service",
    "tinarchy-net-autotune.service",
    "pesu-wifi.service",
    "suwayomi-server.service",
    "jellyfin.service",
    "syncthing@pineapple.service",
    "tailscaled.service",
    "nginx.service",
    "thermald.service"
]
def test_services():
    for s in SERVICES:
        res = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True)
        st = res.stdout.strip()
        if st != "active":
            raise Exception(f"Service {s} is {st}")
run_test("Core Systemd Services Active (10/10)", test_services)

# 3. Nginx config
def test_nginx():
    res = subprocess.run(["sudo", "nginx", "-t"], capture_output=True, text=True)
    if res.returncode != 0:
        raise Exception(res.stderr)
run_test("Nginx Configuration Test (sudo nginx -t)", test_nginx)

# 4. SSH config
def test_sshd():
    res = subprocess.run(["sudo", "sshd", "-t"], capture_output=True, text=True)
    if res.returncode != 0:
        raise Exception(res.stderr)
run_test("OpenSSH Server Configuration Test (sudo sshd -t)", test_sshd)

# 5. Governor Status
def test_governor():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "configs", "scripts", "tinarchy-resource-governor.py")
    res = subprocess.run(["python3", script, "--status"], capture_output=True, text=True)
    if res.returncode != 0 or "PINEAPPLE STATION" not in res.stdout:
        raise Exception("Governor status failed")
run_test("Autonomous Resource Governor Telemetry", test_governor)

# 6. Network & Packet Steering
def test_network():
    if os.path.exists("/sys/class/net/wlan0/queues/rx-0/rps_cpus"):
        with open("/sys/class/net/wlan0/queues/rx-0/rps_cpus") as f:
            val = f.read().strip()
            if val != "f":
                raise Exception(f"wlan0 rps_cpus is {val}, expected f")
    res = subprocess.run(["sysctl", "-n", "net.ipv4.tcp_congestion_control"], capture_output=True, text=True)
    if res.stdout.strip() != "bbr":
        raise Exception(f"TCP congestion control is {res.stdout.strip()}, expected bbr")
run_test("Multicore RPS (Mask f) & BBR Congestion Control", test_network)

# 7. Hardware & Storage
def test_hardware():
    if os.path.exists("/sys/block/sda/queue/read_ahead_kb"):
        with open("/sys/block/sda/queue/read_ahead_kb") as f:
            ra = f.read().strip()
            if ra != "2048":
                raise Exception(f"sda read_ahead_kb is {ra}, expected 2048")
    if not os.path.exists("/dev/shm/jellyfin-transcodes"):
        raise Exception("RAM-disk /dev/shm/jellyfin-transcodes missing")
run_test("2048KB Readahead & RAM-Disk Transcodes", test_hardware)

# 8. Web Telemetry Endpoint
def test_api():
    req = urllib.request.Request("http://127.0.0.1:8085/api/reports/daily")
    with urllib.request.urlopen(req, timeout=3) as r:
        data = json.loads(r.read().decode())
        assert data.get("hostname") == "pineapple-station"
        assert "markdown_report" in data
        assert len(data.get("services", [])) == 10
run_test("Web Telemetry Endpoint (/api/reports/daily)", test_api)

# 9. Terminfo & Mosh
def test_terminfo_mosh():
    for term in ["xterm-kitty", "foot", "alacritty", "ghostty"]:
        res = subprocess.run(["infocmp", term], capture_output=True, text=True)
        if res.returncode != 0:
            raise Exception(f"Missing terminfo for {term}")
    res = subprocess.run(["mosh-server", "--version"], capture_output=True, text=True)
    if res.returncode != 0:
        raise Exception("mosh-server missing or failed")
run_test("Terminfo Matrix (Kitty, Foot, Alacritty, Ghostty) & Mosh", test_terminfo_mosh)

passed = sum(1 for _, ok, _ in tests if ok)
print(f"\n==========================================")
print(f"  TEST RESULTS: {passed}/{len(tests)} TESTS PASSED")
print(f"==========================================")
if passed != len(tests):
    sys.exit(1)
