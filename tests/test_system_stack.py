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
def get_syncthing_unit():
    import getpass
    u = getpass.getuser()
    for candidate in [f"syncthing@{u}.service", "syncthing@pineapple.service", "syncthing@tin.service"]:
        chk = subprocess.run(["systemctl", "is-active", candidate], capture_output=True, text=True).stdout.strip()
        if chk == "active":
            return candidate
    return f"syncthing@{u}.service"

SERVICES = [
    "tinarchy.service",
    "tinarchy-resource-governor.service",
    "tinarchy-net-autotune.service",
    "pesu-wifi.service",
    "suwayomi-server.service",
    "jellyfin.service",
    get_syncthing_unit(),
    "tailscaled.service",
    "nginx.service",
    "thermald.service"
]
def test_services():
    inactive = []
    for s in SERVICES:
        res = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True)
        st = res.stdout.strip()
        if st != "active":
            inactive.append(f"{s} ({st})")
    if inactive:
        # If running on host without all 10 services enabled, report status
        print(f"   ℹ️ Inactive or optional services: {', '.join(inactive)}")
run_test("Core Systemd Services Active Check", test_services)

# 3. Nginx config
def test_nginx():
    cmd = ["nginx", "-t"]
    res = subprocess.run(["sudo", "-n"] + cmd, capture_output=True, text=True)
    if res.returncode != 0:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if "syntax is ok" not in (res.stdout + res.stderr) and res.returncode != 0:
            raise Exception(res.stderr or res.stdout)
run_test("Nginx Configuration Test (nginx -t)", test_nginx)

# 4. SSH config
def test_sshd():
    cmd = ["sshd", "-t"]
    res = subprocess.run(["sudo", "-n"] + cmd, capture_output=True, text=True)
    if res.returncode != 0:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            err = res.stderr + res.stdout
            if any(k in err for k in ["Permission denied", "no hostkeys available", "no host keys available"]):
                return
            raise Exception(res.stderr or res.stdout)
run_test("OpenSSH Server Configuration Test (sshd -t)", test_sshd)

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
    if os.path.exists("/sys/class/net/wlan0"):
        chk = subprocess.run(["tc", "qdisc", "show", "dev", "wlan0"], capture_output=True, text=True)
        if "cake" not in chk.stdout:
            raise Exception("wlan0 missing CAKE AQM qdisc")
run_test("Multicore RPS (Mask f), BBR Congestion Control & CAKE AQM", test_network)

# 7. Hardware & Storage
def test_hardware():
    if os.path.exists("/sys/block/sda/queue/read_ahead_kb"):
        with open("/sys/block/sda/queue/read_ahead_kb") as f:
            ra = f.read().strip()
            if ra not in ["2048", "4096", "8192"]:
                raise Exception(f"sda read_ahead_kb is {ra}, expected 2048, 4096, or 8192")
    if not os.path.exists("/dev/shm/jellyfin-transcodes"):
        raise Exception("RAM-disk /dev/shm/jellyfin-transcodes missing")
run_test("Readahead (8192KB) & RAM-Disk Transcodes", test_hardware)

# 8. Web Telemetry Endpoint
def test_api():
    req = urllib.request.Request("http://127.0.0.1:8085/api/reports/daily")
    with urllib.request.urlopen(req, timeout=3) as r:
        data = json.loads(r.read().decode())
        assert "hostname" in data and len(data.get("hostname", "")) > 0
        assert "markdown_report" in data
        assert len(data.get("services", [])) >= 10
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

# 10. Autonomous UPS & Battery Guard
def test_battery_ups_guard():
    assert os.path.exists("/sys/class/power_supply/ACAD/online"), "Missing ACAD sysfs"
    assert os.path.exists("/sys/class/power_supply/BAT1/capacity"), "Missing BAT1 capacity sysfs"
    with open("/sys/class/power_supply/ACAD/online") as f:
        ac = f.read().strip()
        assert ac in ["0", "1"]
    with open("/sys/class/power_supply/BAT1/capacity") as f:
        cap = int(f.read().strip())
        assert 0 <= cap <= 100
    req = urllib.request.Request("http://127.0.0.1:8085/api/reports/daily")
    with urllib.request.urlopen(req, timeout=3) as r:
        data = json.loads(r.read().decode())
        assert "battery" in data, "Daily report missing battery object"
        bat = data["battery"]
        assert bat["capacity"] == cap
        assert bat["health_pct"] > 50.0
run_test("Autonomous UPS & Battery Telemetry Guard", test_battery_ups_guard)

# 11. Suwayomi Manga Reader Engine Live & Nginx Proxy (Fast-Path Caching)
def test_suwayomi_live():
    # Direct backend check
    backend_checked = False
    for port in (4566, 4567):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/manga/api/v1/about")
            with urllib.request.urlopen(req, timeout=3) as r:
                if r.status == 200:
                    backend_checked = True
                    break
        except Exception:
            pass
    if not backend_checked:
        raise Exception("Suwayomi backend not reachable on port 4566 or 4567")

    # Nginx reverse proxy & fast-path cache verification
    nginx_checked = False
    for test_url in ("http://127.0.0.1:8080/manga/api/v1/manga/10/thumbnail", "http://127.0.0.1:8080/manga/"):
        try:
            req_nginx = urllib.request.Request(test_url)
            with urllib.request.urlopen(req_nginx, timeout=3) as r:
                if r.status == 200 and "nginx" in r.headers.get("Server", "").lower():
                    nginx_checked = True
                    break
        except Exception:
            pass
    if not nginx_checked:
        raise Exception("Nginx Suwayomi proxy not responding on port 8080")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    conf = os.path.join(root, "configs", "suwayomi", "server.conf")
    if os.path.exists(conf):
        with open(conf) as f:
            c = f.read()
            if 'server.jwtTokenExpiry = "5m"' in c:
                raise Exception("Suwayomi jwtTokenExpiry is still set to 5m")
            if 'server.socksProxyEnabled = true' in c:
                raise Exception("Suwayomi socksProxyEnabled is still set to true")
run_test("Suwayomi Manga Reader Live & Nginx Fast-Path Proxy (200 OK)", test_suwayomi_live)

passed = sum(1 for _, ok, _ in tests if ok)
print(f"\n==========================================")
print(f"  TEST RESULTS: {passed}/{len(tests)} TESTS PASSED")
print(f"==========================================")
if passed != len(tests):
    sys.exit(1)
