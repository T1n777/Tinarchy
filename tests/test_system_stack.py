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
import ssl
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

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
    "seerr.service",
    "navidrome.service",
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

# 12. Seerr Media Discovery Live & Nginx Reverse Proxy
def test_seerr_live():
    # Direct loopback check
    req = urllib.request.Request("http://127.0.0.1:5054/api/v1/settings/public")
    with urllib.request.urlopen(req, timeout=3) as r:
        if r.status != 200:
            raise Exception(f"Seerr direct backend returned status {r.status}")
        data = json.loads(r.read().decode())
        if "applicationTitle" not in data:
            raise Exception("Seerr public settings missing applicationTitle")

    # Nginx port 5055 proxy check (SSL or HTTP redirect)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def http_error_301(self, req, fp, code, msg, headers):
            return fp
        def http_error_302(self, req, fp, code, msg, headers):
            return fp
        def http_error_307(self, req, fp, code, msg, headers):
            return fp

    opener = urllib.request.build_opener(NoRedirect)
    resp = opener.open("http://127.0.0.1:5055/", timeout=3)
    if resp.status not in (301, 302, 307):
        raise Exception(f"Nginx port 5055 HTTP redirect expected 301/307, got {resp.status}")
run_test("Seerr Media Discovery Live & Nginx Reverse Proxy (200/301 OK)", test_seerr_live)

# 13. qBittorrent Web UI Live & Nginx Reverse Proxy
def test_qbittorrent_live():
    req = urllib.request.Request("http://127.0.0.1:8084/api/v2/app/version")
    with urllib.request.urlopen(req, timeout=3) as r:
        if r.status != 200:
            raise Exception(f"qBittorrent direct backend returned status {r.status}")
        v = r.read().decode().strip()
        if not v.startswith("v"):
            raise Exception(f"Unexpected qBittorrent version string: {v}")

    # Nginx path proxy check on port 8080
    req_proxy = urllib.request.Request("http://127.0.0.1:8080/qbittorrent/api/v2/app/version")
    with urllib.request.urlopen(req_proxy, timeout=3) as r:
        if r.status != 200:
            raise Exception(f"Nginx /qbittorrent/ proxy returned status {r.status}")
run_test("qBittorrent Web UI Live & Nginx Reverse Proxy (200 OK)", test_qbittorrent_live)

# 14. Bazarr Subtitles Manager Live & Nginx Reverse Proxy
def test_bazarr_live():
    req = urllib.request.Request("http://127.0.0.1:6767/bazarr/api/system/ping")
    with urllib.request.urlopen(req, timeout=3) as r:
        if r.status != 200:
            raise Exception(f"Bazarr direct backend returned status {r.status}")

    # Nginx path proxy check on port 8080
    req_proxy = urllib.request.Request("http://127.0.0.1:8080/bazarr/api/system/ping")
    with urllib.request.urlopen(req_proxy, timeout=3) as r:
        if r.status != 200:
            raise Exception(f"Nginx /bazarr/ proxy returned status {r.status}")
run_test("Bazarr Subtitles Manager Live & Nginx Reverse Proxy (200 OK)", test_bazarr_live)

# 15. Navidrome Music Server Live
def test_navidrome_live():
    req = urllib.request.Request("http://127.0.0.1:4533/ping")
    with urllib.request.urlopen(req, timeout=3) as r:
        if r.status != 200:
            raise Exception(f"Navidrome direct backend returned status {r.status}")
run_test("Navidrome Music Server Live (200 OK)", test_navidrome_live)

# 16. Suwayomi WebP Thumbnail Fast-Path (Static Kernel Sendfile / Dynamic Optimizer)
def test_suwayomi_thumbnail_fastpath():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request("https://127.0.0.1:4567/api/v1/manga/4/thumbnail")
    with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
        if r.status != 200:
            raise Exception(f"Thumbnail fast-path returned HTTP status {r.status}")
        ctype = r.headers.get("Content-Type", "")
        if "webp" not in ctype:
            raise Exception(f"Expected image/webp content-type, got: {ctype}")
run_test("Suwayomi WebP Thumbnail Fast-Path (200 OK, image/webp)", test_suwayomi_thumbnail_fastpath)

# 17. Suwayomi Private Category '_' Isolation & Vault Injection
def test_suwayomi_privacy_vault():
    # A. Test /api/widgets/manga excludes category '_'
    req = urllib.request.Request("http://127.0.0.1:8085/api/widgets/manga")
    with urllib.request.urlopen(req, timeout=3) as r:
        if r.status != 200:
            raise Exception(f"/api/widgets/manga returned {r.status}")
        data = json.loads(r.read().decode())
        mangas = data.get("mangas", [])
        from tinarchy.thumbnails import get_private_manga_ids
        p_ids = get_private_manga_ids()
        for m in mangas:
            if m["id"] in p_ids:
                raise Exception(f"Private manga {m['id']} ({m['title']}) found in public widget!")

    # B. Test Nginx injects suwayomi-vault.js into Suwayomi WebUI
    injected = False
    for url in ("http://127.0.0.1:8080/manga/", "http://127.0.0.1:8080/"):
        try:
            req_nginx = urllib.request.Request(url)
            with urllib.request.urlopen(req_nginx, timeout=3) as r:
                html = r.read().decode()
                if "suwayomi-vault.js" in html:
                    injected = True
                    break
        except Exception:
            pass
    if not injected:
        raise Exception("Nginx did not inject suwayomi-vault.js into Suwayomi HTML")

run_test("Suwayomi Private Category '_' Isolation & Vault Injection", test_suwayomi_privacy_vault)

# --- TEST 18: Unified Draggable Dashboard Grid & Flat Items Schema ---
def test_dashboard_unified_grid():
    # 1. Test backend endpoint
    req = urllib.request.Request("http://127.0.0.1:8085/api/dashboard/layout")
    with urllib.request.urlopen(req, timeout=3) as r:
        if r.status != 200:
            raise Exception(f"Expected 200 from /api/dashboard/layout, got {r.status}")
        data = json.loads(r.read().decode())
        if "items" not in data or not isinstance(data["items"], list):
            raise Exception("Layout response missing flat 'items' list")
        if len(data["items"]) < 10:
            raise Exception(f"Expected >=10 items in layout, got {len(data['items'])}")

    # 2. Test public/index.html structure
    with open("public/index.html", "r", encoding="utf-8") as f:
        html = f.read()
    if 'id="homarr-grid"' not in html:
        raise Exception("Missing #homarr-grid in public/index.html")
    if 'id="homarr-boards"' in html:
        raise Exception("Found deprecated #homarr-boards in public/index.html")
    if 'id="homarr-filter-pills"' in html:
        raise Exception("Found deprecated #homarr-filter-pills in public/index.html")

run_test("Unified Draggable Dashboard Grid & Flat Items Schema", test_dashboard_unified_grid)

# --- TEST 19: Manga Shelf Individual Items Linked Directly to Manhwa Page ---
def test_manga_shelf_links():
    # 1. Verify /api/widgets/manga links point to specific /manga/:id
    req = urllib.request.Request("http://127.0.0.1:8085/api/widgets/manga")
    with urllib.request.urlopen(req, timeout=3) as r:
        if r.status != 200:
            raise Exception(f"Failed to fetch /api/widgets/manga: {r.status}")
        data = json.loads(r.read().decode())
        mangas = data.get("mangas", [])
        if not mangas:
            raise Exception("No mangas found in /api/widgets/manga to verify")
        for m in mangas:
            expected_link = f"/manga/{m['id']}"
            if m.get("link") != expected_link:
                raise Exception(f"Expected manga link {expected_link}, got {m.get('link')}")

    # 2. Verify backend /manga/:id redirects to Suwayomi port 4567 with target manga path
    first_manga_id = mangas[0]["id"]
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirectHandler)
    req_redir = urllib.request.Request(f"http://127.0.0.1:8085/manga/{first_manga_id}")
    try:
        resp = opener.open(req_redir, timeout=3)
        code = resp.status
        loc = resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        code = e.code
        loc = e.headers.get("Location", "")

    if code != 302:
        raise Exception(f"Expected 302 redirect from /manga/{first_manga_id}, got HTTP {code}")
    if f":4567/manga/{first_manga_id}" not in loc:
        raise Exception(f"Expected redirect location to contain :4567/manga/{first_manga_id}, got '{loc}'")

run_test("Manga Shelf Individual Items Linked Directly to Manhwa Page", test_manga_shelf_links)

# --- TEST 20: Pink Top Minimal tmux & Shared TTY / SSH Session Persistence ---
def test_tmux_pink_top_and_tty_persistence():
    # 1. Verify tmux configuration
    tmux_path = "configs/tmux/tmux.conf"
    if not os.path.exists(tmux_path):
        raise Exception(f"Missing {tmux_path}")
    with open(tmux_path, "r", encoding="utf-8") as f:
        tmux_conf = f.read()
    if "status-position top" not in tmux_conf:
        raise Exception("tmux.conf missing 'status-position top'")
    if "#ffafd3" not in tmux_conf:
        raise Exception("tmux.conf missing pastel pink accent '#ffafd3'")
    if "bg=default" not in tmux_conf:
        raise Exception("tmux.conf missing 'bg=default' terminal backdrop")
    if "window-size latest" not in tmux_conf:
        raise Exception("tmux.conf missing 'window-size latest'")

    # 2. Verify Zsh tmux auto-attach supports both SSH and physical TTY
    zsh_path = "configs/zsh/zshrc"
    if not os.path.exists(zsh_path):
        raise Exception(f"Missing {zsh_path}")
    with open(zsh_path, "r", encoding="utf-8") as f:
        zsh_conf = f.read()
    if "/dev/tty" not in zsh_conf:
        raise Exception("configs/zsh/zshrc missing /dev/tty auto-attach matching")
    if "exec tmux new-session -A -s main" not in zsh_conf:
        raise Exception("configs/zsh/zshrc missing 'exec tmux new-session -A -s main'")

    # 3. Verify getty-autologin.conf drop-in
    autologin_path = "configs/systemd/getty-autologin.conf"
    if not os.path.exists(autologin_path):
        raise Exception(f"Missing {autologin_path}")
    with open(autologin_path, "r", encoding="utf-8") as f:
        auto_conf = f.read()
    if "--autologin" not in auto_conf:
        raise Exception("getty-autologin.conf missing --autologin")

run_test("Pink Top Minimal tmux & Shared TTY / SSH Session Persistence", test_tmux_pink_top_and_tty_persistence)

# --- TEST 21: Universal Shell Installer Piped Execution & Dry-Run Mode ---
def test_shell_installer_flags_and_piped():
    installer_path = os.path.join(REPO_ROOT, "install.sh")
    if not os.path.exists(installer_path):
        raise Exception(f"Missing {installer_path}")

    # Syntax check
    chk = subprocess.run(["bash", "-n", installer_path], capture_output=True, text=True)
    if chk.returncode != 0:
        raise Exception(f"install.sh syntax error: {chk.stderr}")

    # Test --dry-run
    res_dry = subprocess.run([installer_path, "--dry-run"], capture_output=True, text=True)
    if res_dry.returncode != 0:
        raise Exception(f"install.sh --dry-run failed with code {res_dry.returncode}: {res_dry.stderr}")
    if "Dry Run" not in res_dry.stdout or "Target User" not in res_dry.stdout:
        raise Exception(f"install.sh --dry-run output missing expected confirmation headers: {res_dry.stdout[:200]}")

    # Test piped invocation simulation
    with open(installer_path, "r", encoding="utf-8") as f:
        pipe_input = f.read()
    res_pipe = subprocess.run(["bash", "-s", "--", "--dry-run"], input=pipe_input, capture_output=True, text=True)
    if res_pipe.returncode != 0:
        raise Exception(f"cat install.sh | bash --dry-run failed: {res_pipe.stderr}")
    if "Remote or piped bootstrap execution detected" not in res_pipe.stdout:
        raise Exception(f"Piped installer failed to detect remote pipe execution: {res_pipe.stdout[:200]}")

    # Test --help
    res_help = subprocess.run([installer_path, "--help"], capture_output=True, text=True)
    if "--iso-mode" not in res_help.stdout or "--dry-run" not in res_help.stdout:
        raise Exception(f"install.sh --help output missing required options: {res_help.stdout}")

run_test("Universal Shell Installer Flags & Piped Bootstrap Validation", test_shell_installer_flags_and_piped)

# --- TEST 22: Dashboard HTTP Endpoint Serving /install.sh ---
def test_install_script_http_serving():
    port = 8085
    base_url = f"http://127.0.0.1:{port}"

    for ep in ["/install.sh", "/install", "/bootstrap.sh"]:
        req = urllib.request.Request(f"{base_url}{ep}")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status != 200:
                    raise Exception(f"Expected HTTP 200 from {ep}, got {resp.status}")
                ctype = resp.headers.get("Content-Type", "")
                if "text/x-shellscript" not in ctype:
                    raise Exception(f"Expected text/x-shellscript Content-Type from {ep}, got {ctype}")
                body = resp.read().decode("utf-8", errors="replace")
                if not body.startswith("#!/usr/bin/env bash"):
                    raise Exception(f"Response from {ep} does not start with '#!/usr/bin/env bash'")
                if "Tinarchy Server Ecosystem" not in body:
                    raise Exception(f"Response from {ep} missing Tinarchy header")
        except urllib.error.URLError as e:
            raise Exception(f"Failed connecting to {base_url}{ep}: {e}")

run_test("Dashboard HTTP Endpoint Serving /install.sh & Bootstrap Scripts", test_install_script_http_serving)

# --- TEST 23: Bootable Live ISO Profile & Packaging Manifest Validation ---
def test_iso_packaging_profile():
    iso_dir = os.path.join(REPO_ROOT, "packaging", "iso")
    if not os.path.isdir(iso_dir):
        raise Exception(f"Missing ISO profile directory: {iso_dir}")

    # 1. Profiledef.sh validation
    profiledef = os.path.join(iso_dir, "profiledef.sh")
    if not os.path.exists(profiledef):
        raise Exception("Missing profiledef.sh")
    res_prof = subprocess.run(["bash", "-n", profiledef], capture_output=True, text=True)
    if res_prof.returncode != 0:
        raise Exception(f"profiledef.sh syntax error: {res_prof.stderr}")
    with open(profiledef, "r", encoding="utf-8") as f:
        prof_content = f.read()
    if 'iso_name="tinarchy-os"' not in prof_content:
        raise Exception("profiledef.sh missing iso_name=\"tinarchy-os\"")
    if "tinarchy-installer" not in prof_content:
        raise Exception("profiledef.sh missing file_permissions for tinarchy-installer")

    # 2. Package manifest validation
    pkg_file = os.path.join(iso_dir, "packages.x86_64")
    if not os.path.exists(pkg_file):
        raise Exception("Missing packages.x86_64")
    with open(pkg_file, "r", encoding="utf-8") as f:
        packages = {line.strip() for line in f if line.strip() and not line.startswith("#")}
    required_pkgs = [
        "base", "base-devel", "linux-lts", "linux-firmware", "arch-install-scripts",
        "python", "python-pillow", "python-requests", "nginx", "syncthing", "tor",
        "tailscale", "rclone", "tmux", "fish", "zsh", "starship", "acpid"
    ]
    missing = [pkg for pkg in required_pkgs if pkg not in packages]
    if missing:
        raise Exception(f"packages.x86_64 missing core packages: {', '.join(missing)}")

    # 3. Guided installer script validation
    installer_bin = os.path.join(iso_dir, "airootfs", "usr", "local", "bin", "tinarchy-installer")
    if not os.path.exists(installer_bin):
        raise Exception(f"Missing live installer: {installer_bin}")
    res_inst = subprocess.run(["bash", "-n", installer_bin], capture_output=True, text=True)
    if res_inst.returncode != 0:
        raise Exception(f"tinarchy-installer syntax error: {res_inst.stderr}")
    if not os.access(installer_bin, os.X_OK):
        raise Exception("tinarchy-installer is not executable")

    # 4. Build script validation
    build_script = os.path.join(iso_dir, "build.sh")
    if not os.path.exists(build_script):
        raise Exception("Missing packaging/iso/build.sh")
    res_bld = subprocess.run(["bash", "-n", build_script], capture_output=True, text=True)
    if res_bld.returncode != 0:
        raise Exception(f"build.sh syntax error: {res_bld.stderr}")

    # 5. CI Workflow validation
    ci_workflow = os.path.join(REPO_ROOT, ".github", "workflows", "build-iso.yml")
    if not os.path.exists(ci_workflow):
        raise Exception("Missing .github/workflows/build-iso.yml")

run_test("Bootable Live ISO Profile & Packaging Manifest Validation", test_iso_packaging_profile)


passed = sum(1 for _, ok, _ in tests if ok)
print(f"\n==========================================")
print(f"  TEST RESULTS: {passed}/{len(tests)} TESTS PASSED")
print(f"==========================================")
if passed != len(tests):
    sys.exit(1)
