import gzip
import pywal_generator
import http.server
import socketserver
import json
import subprocess
import os
import re
import uuid
import time
import http.cookies
import ssl
import threading

def load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    os.environ[k] = v

load_env()

PREV_NET = {'time': time.time(), 'rx': 0, 'tx': 0}
PREV_CPU = {'time': time.time(), 'total': 0, 'idle': 0}

def get_cpu_percent():
    global PREV_CPU
    try:
        with open('/proc/stat', 'r') as f:
            line = f.readline()
        fields = [float(x) for x in line.strip().split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        total = sum(fields)
        
        diff_idle = idle - PREV_CPU['idle']
        diff_total = total - PREV_CPU['total']
        PREV_CPU = {'time': time.time(), 'total': total, 'idle': idle}
        
        if diff_total > 0:
            return round((1.0 - (diff_idle / diff_total)) * 100.0, 1)
        return 0.0
    except Exception:
        return 0.0

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

def get_cpu_temp():
    paths = [
        '/sys/class/thermal/thermal_zone0/temp',
        '/sys/class/hwmon/hwmon0/temp1_input',
        '/sys/class/hwmon/hwmon1/temp1_input'
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, 'r') as f:
                    val = int(f.read().strip())
                    celsius = round(val / 1000.0, 1)
                    return f"{celsius}°C", int(celsius)
            except Exception:
                pass
    return "N/A", 0

APP_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app_config.json')

def get_app_config():
    if os.path.exists(APP_CONFIG_FILE):
        try:
            with open(APP_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "server_name": "",
        "project_name": "tinarchy"
    }

def save_app_config(cfg):
    with open(APP_CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

# ─── Dynamic Tailscale Host Owner & RBAC ───
ROLES_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'roles_config.json')
WHOIS_CACHE = {}

def get_tailscale_host_owner():
    """
    Dynamically discovers the Tailscale account that owns/registered this server node.
    Works dynamically on any Tailscale network without hardcoded emails.
    """
    try:
        res = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout:
            st = json.loads(res.stdout)
            self_user_id = st.get('Self', {}).get('UserID')
            if self_user_id:
                user_info = st.get('User', {}).get(str(self_user_id), {})
                return {
                    'user_id': self_user_id,
                    'login_name': user_info.get('LoginName', ''),
                    'display_name': user_info.get('DisplayName', user_info.get('LoginName', 'Owner'))
                }
    except Exception as e:
        print(f"Error resolving Tailscale host owner: {e}")
    return {
        'user_id': None,
        'login_name': 'imyash0722@gmail.com',
        'display_name': 'Yashwanth Karthik'
    }

def get_roles_config():
    default_cfg = {
        "admin_accounts": [],
        "roles": {},
        "default_role": "viewer"
    }
    if os.path.exists(ROLES_CONFIG_FILE):
        try:
            with open(ROLES_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return default_cfg

def save_roles_config(cfg):
    try:
        with open(ROLES_CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving roles config: {e}")

def get_user_role(login_name, display_name=""):
    host_owner = get_tailscale_host_owner()
    # 1. The Tailscale account hosting the server is ALWAYS dynamically the Owner!
    if login_name and login_name == host_owner.get('login_name'):
        return 'owner'
    if display_name and display_name == host_owner.get('display_name'):
        return 'owner'

    # 2. Check if the Owner granted Admin permissions
    cfg = get_roles_config()
    admins = cfg.get('admin_accounts', [])
    if isinstance(cfg.get('roles'), dict) and cfg['roles'].get(login_name) == 'admin':
        return 'admin'
    if login_name in admins:
        return 'admin'

    # 3. New Tailscale accounts automatically default to Viewer!
    return 'viewer'

def resolve_tailscale_client(ip):
    host_owner = get_tailscale_host_owner()
    # Localhost / loopback / server self
    if ip in ['127.0.0.1', '::1', '100.112.193.54']:
        return {
            'login_name': host_owner.get('login_name'),
            'display_name': host_owner.get('display_name'),
            'avatar': 'https://lh3.googleusercontent.com/a/ACg8ocL92RrWfI8Ahb8E_7Rk3UvYWjsMvXusLJQqYicGtM1nm3Yrv5Dm=s96-c',
            'device_name': 'pinedash',
            'device_ip': ip,
            'role': 'owner',
            'is_owner': True,
            'is_tailscale': True
        }

    now = time.time()
    if ip in WHOIS_CACHE and (now - WHOIS_CACHE[ip]['ts']) < 60:
        return WHOIS_CACHE[ip]['data']

    try:
        res = subprocess.run(['tailscale', 'whois', '--json', ip], capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout:
            raw = json.loads(res.stdout)
            u = raw.get('UserProfile', {})
            node = raw.get('Node', {})
            login_name = u.get('LoginName', '')
            display_name = u.get('DisplayName', login_name)
            avatar = u.get('ProfilePicURL', '')
            device = node.get('ComputedName', '')

            role = get_user_role(login_name, display_name)
            user_info = {
                'login_name': login_name,
                'display_name': display_name,
                'avatar': avatar,
                'device_name': device,
                'device_ip': ip,
                'role': role,
                'is_owner': (role == 'owner'),
                'is_tailscale': True
            }
            WHOIS_CACHE[ip] = {'data': user_info, 'ts': now}
            return user_info
    except Exception as e:
        print(f"Tailscale whois error: {e}")

    # Fallback for LAN Wi-Fi / Local Subnet (e.g. 10.14.143.x)
    is_lan = ip.startswith(('10.', '192.168.', '172.'))
    fallback = {
        'login_name': 'lan_client',
        'display_name': f'Local LAN ({ip})',
        'avatar': '',
        'device_name': ip,
        'device_ip': ip,
        'role': 'owner' if is_lan else 'viewer',
        'is_owner': is_lan,
        'is_tailscale': False
    }
    return fallback

def get_tailscale_users():
    try:
        res = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=2)
        if res.returncode != 0:
            return []
        data = json.loads(res.stdout)
        users_map = data.get('User', {})
        peers = data.get('Peer', {})
        self_node = data.get('Self', {})
        
        all_nodes = list(peers.values())
        if self_node:
            all_nodes.append(self_node)
            
        ts_users = []
        for uid_str, uinfo in users_map.items():
            uid = int(uid_str)
            user_devices = []
            for node in all_nodes:
                if node.get('UserID') == uid:
                    ips = node.get('TailscaleIPs', [])
                    user_devices.append({
                        'name': node.get('HostName', 'Unknown'),
                        'dns_name': (node.get('DNSName', '')).rstrip('.'),
                        'os': node.get('OS', 'Unknown'),
                        'ip': ips[0] if ips else '',
                        'online': node.get('Online', False),
                        'active': node.get('Active', False),
                        'is_self': node.get('ID') == self_node.get('ID')
                    })
            
            l_name = uinfo.get('LoginName', '')
            d_name = uinfo.get('DisplayName', l_name)
            role = get_user_role(l_name, d_name)
            ts_users.append({
                'id': uid,
                'display_name': d_name,
                'login_name': l_name,
                'avatar': uinfo.get('ProfilePicURL', ''),
                'role': role,
                'is_owner': (role == 'owner'),
                'devices': user_devices
            })
        return ts_users
    except Exception as e:
        print(f"Tailscale status error: {e}")
        return []

PORT = 8080
PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')
WALLPAPER_DIR = '/home/pineapple/Wall' if os.path.isdir('/home/pineapple/Wall') else os.path.join(PUBLIC_DIR, 'Wallpapers')

SERVICES = [
    {'id': 'suwayomi', 'name': 'Suwayomi Server', 'port': 4567, 'systemd': 'suwayomi-server', 'icon': '📚', 'description': 'Manga library and reader'},
    {'id': 'jellyfin', 'name': 'Jellyfin Media Server', 'port': 8096, 'systemd': 'jellyfin', 'icon': '🍿', 'description': 'Movies, TV shows & media streaming'},
    {'id': 'tor', 'name': 'Tor Proxy', 'port': 9050, 'systemd': 'tor', 'icon': '🧅', 'description': 'SOCKS5 anonymity proxy'},
    {'id': 'filebrowser', 'name': 'File Manager', 'port': 8081, 'systemd': 'filebrowser-quantum', 'icon': '📂', 'description': 'Modern web-based file manager'},
    {'id': 'couchdb', 'name': 'Obsidian LiveSync', 'port': 5984, 'systemd': 'couchdb', 'icon': '🔮', 'description': 'Real-time E2EE sync backend for Obsidian vaults'},
    {'id': 'sshd', 'name': 'SSH Server', 'port': 22, 'systemd': 'sshd', 'icon': '🔑', 'description': 'Secure shell access'},
]

class DashboardHandler(http.server.SimpleHTTPRequestHandler):

    def send_compressed(self, data_bytes, content_type='application/json', code=200):
        accept_enc = self.headers.get('Accept-Encoding', '')
        if 'gzip' in accept_enc and len(data_bytes) > 200:
            compressed = gzip.compress(data_bytes, compresslevel=6)
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Encoding', 'gzip')
            self.send_header('Vary', 'Accept-Encoding')
            self.send_header('Content-Length', str(len(compressed)))
            self.end_headers()
            self.wfile.write(compressed)
        else:
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data_bytes)))
            self.end_headers()
            self.wfile.write(data_bytes)

    def end_headers(self):
        if hasattr(self, 'path') and (self.path.startswith('/Wallpapers/') or self.path.startswith('/thumbnails/') or self.path.endswith(('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.svg', '.woff2', '.ico'))):
            self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
        super().end_headers()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PUBLIC_DIR, **kwargs)

    def get_client_ip(self):
        real_ip = self.headers.get('X-Real-IP')
        if real_ip:
            return real_ip.strip()
        fwd = self.headers.get('X-Forwarded-For')
        if fwd:
            return fwd.split(',')[0].strip()
        return self.client_address[0]

    def check_auth(self):
        client_ip = self.get_client_ip()
        return resolve_tailscale_client(client_ip)

    def do_GET(self):
        # Allow static assets and public endpoints
        if self.path.startswith('/Wallpapers/') or self.path.startswith('/thumbnails/') or self.path.endswith(('.css', '.js', '.png', '.jpg', '.ico', '.woff', '.woff2', '.mp4', '.crt')):
            super().do_GET()
            return
            
        session = self.check_auth()

        if self.path == '/api/services':
            results = []
            for s in SERVICES:
                status_obj = s.copy()
                try:
                    res = subprocess.run(['systemctl', 'is-active', s['systemd']], capture_output=True, text=True)
                    status_obj['status'] = 'online' if res.stdout.strip() == 'active' else 'offline'
                except Exception:
                    status_obj['status'] = 'offline'

                if s['id'] == 'suwayomi':
                    try:
                        res = subprocess.run(['grep', '-q', 'server.socksProxyEnabled = true', '/var/lib/suwayomi/.local/share/Tachidesk/server.conf'])
                        status_obj['torProxyEnabled'] = (res.returncode == 0)
                    except Exception:
                        status_obj['torProxyEnabled'] = False

                results.append(status_obj)

            self.send_compressed(json.dumps(results).encode(), "application/json")
            
        elif self.path == '/api/me':
            self.send_compressed(json.dumps({
                "role": session.get('role', 'viewer'),
                "display_name": session.get('display_name', 'User'),
                "login_name": session.get('login_name', ''),
                "avatar": session.get('avatar', ''),
                "is_owner": session.get('is_owner', False),
                "device_name": session.get('device_name', '')
            }).encode(), "application/json")

        elif self.path == '/api/users':
            ts_users = get_tailscale_users()
            self.send_compressed(json.dumps({
                "current_user": session,
                "tailscale_users": ts_users,
                "roles_config": get_roles_config(),
                "can_manage_roles": (session.get('role') == 'owner')
            }).encode(), "application/json")

        elif self.path == '/api/app/config':
            self.send_compressed(json.dumps(get_app_config()).encode(), "application/json")

        elif self.path == '/api/pywal':
            pywal_file = os.path.join(PUBLIC_DIR, 'pywal.json')
            if os.path.exists(pywal_file):
                with open(pywal_file, 'rb') as f_in:
                    self.send_compressed(f_in.read(), 'application/json')
            else:
                self.send_compressed(b'{}', 'application/json')

        elif self.path == '/api/wallpapers':
            wallpapers = []
            wp_dir = os.path.join(PUBLIC_DIR, 'Wallpapers')
            thumb_dir = os.path.join(PUBLIC_DIR, 'thumbnails')
            if os.path.isdir(wp_dir):
                for f in sorted(os.listdir(wp_dir)):
                    if f.startswith('.'):
                        continue
                    if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.mp4')):
                        is_vid = f.lower().endswith('.mp4')
                        base_no_ext = os.path.splitext(f)[0]
                        clean_name = base_no_ext.replace('_', ' ').replace('-', ' ').title()
                        thumb_file = f"{base_no_ext}.webp"
                        thumb_url = f"/thumbnails/{thumb_file}" if os.path.exists(os.path.join(thumb_dir, thumb_file)) else f"/Wallpapers/{f}"
                        wallpapers.append({
                            'file': f,
                            'name': clean_name,
                            'url': f'/Wallpapers/{f}',
                            'thumb_url': thumb_url,
                            'is_video': is_vid,
                            'theme': 'Animated' if is_vid else 'Wallpaper'
                        })
            self.send_compressed(json.dumps(wallpapers).encode(), 'application/json')

        elif self.path == '/api/drive/sync':
            try:
                subprocess.Popen(['/usr/local/bin/tinarchy-drive-sync'])
                self.send_compressed(b'{"success": true, "message": "Drive sync triggered"}', 'application/json')
            except Exception as e:
                self.send_compressed(json.dumps({"success": False, "error": str(e)}).encode(), 'application/json', code=500)

        elif self.path == '/api/system':
            stats = {}
            try:
                with open('/proc/meminfo', 'r') as f:
                    meminfo = {}
                    for line in f:
                        parts = line.split(':')
                        if len(parts) == 2:
                            meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])
                    
                    total = meminfo.get('MemTotal', 0)
                    free = meminfo.get('MemFree', 0)
                    buffers = meminfo.get('Buffers', 0)
                    cached = meminfo.get('Cached', 0)
                    used = total - free - buffers - cached
                    stats['ram_used_mb'] = int(used / 1024)
                    stats['ram_total_mb'] = int(total / 1024)
                    stats['ram_percent'] = round((used / total) * 100, 1) if total > 0 else 0
            except Exception:
                stats['ram_used_mb'] = 0
                stats['ram_total_mb'] = 0
                stats['ram_percent'] = 0

            try:
                vfs = os.statvfs('/')
                disk_total = vfs.f_blocks * vfs.f_frsize
                disk_free = vfs.f_bfree * vfs.f_frsize
                disk_used = disk_total - disk_free
                stats['disk_used'] = f"{int(disk_used / (1024**3))}GB"
                stats['disk_total'] = f"{int(disk_total / (1024**3))}GB"
                stats['disk_percent'] = round((disk_used / disk_total) * 100, 1) if disk_total > 0 else 0
            except Exception:
                stats['disk_used'] = "0GB"
                stats['disk_total'] = "0GB"
                stats['disk_percent'] = 0

            stats['cpu_percent'] = get_cpu_percent()

            try:
                with open('/proc/uptime', 'r') as f:
                    uptime_seconds = float(f.readline().split()[0])
                    days = int(uptime_seconds // (24 * 3600))
                    hours = int((uptime_seconds % (24 * 3600)) // 3600)
                    minutes = int((uptime_seconds % 3600) // 60)
                    stats['uptime'] = f"{days}d {hours}h {minutes}m"
            except Exception:
                stats['uptime'] = "Unknown"

            try:
                with open('/proc/loadavg', 'r') as f:
                    stats['loadavg'] = f.readline().split()[:3]
            except Exception:
                stats['loadavg'] = ["0.00", "0.00", "0.00"]

            import socket
            stats['hostname'] = socket.gethostname()
            
            try:
                res = subprocess.run(['tailscale', 'ip', '-4'], capture_output=True, text=True)
                stats['tailscale_ip'] = res.stdout.strip() if res.returncode == 0 else "Offline"
            except Exception:
                stats['tailscale_ip'] = "Offline"

            now_t = time.time()
            try:
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
                dt = max(0.5, now_t - PREV_NET['time'])
                rx_spd = max(0, (rx_tot - PREV_NET['rx']) / dt) if PREV_NET['rx'] > 0 and rx_tot >= PREV_NET['rx'] else 0
                tx_spd = max(0, (tx_tot - PREV_NET['tx']) / dt) if PREV_NET['tx'] > 0 and tx_tot >= PREV_NET['tx'] else 0
                PREV_NET = {'time': now_t, 'rx': rx_tot, 'tx': tx_tot}
                
                stats['net_rx_bytes_sec'] = rx_spd
                stats['net_tx_bytes_sec'] = tx_spd
                stats['net_rx_speed'] = format_speed(rx_spd)
                stats['net_tx_speed'] = format_speed(tx_spd)
                stats['net_rx_formatted'] = stats['net_rx_speed']
                stats['net_tx_formatted'] = stats['net_tx_speed']
                stats['net_rx_total'] = format_total(rx_tot)
                stats['net_tx_total'] = format_total(tx_tot)
                stats['net_text'] = f"▲ {stats['net_tx_speed']} · ▼ {stats['net_rx_speed']}"
                tot_spd = rx_spd + tx_spd
                if tot_spd > 512:
                    import math
                    stats['net_percent'] = min(100, max(5, int(math.log10(tot_spd) * 15)))
                else:
                    stats['net_percent'] = 2
            except Exception:
                stats['net_rx_speed'] = '0 B/s'
                stats['net_tx_speed'] = '0 B/s'
                stats['net_text'] = '↓ 0 B/s · ↑ 0 B/s'
                stats['net_percent'] = 0
                stats['net_rx_total'] = '0 MB'
                stats['net_tx_total'] = '0 MB'

            celsius_str, celsius_val = get_cpu_temp()
            stats['cpu_temp'] = celsius_str
            stats['cpu_temp_val'] = celsius_val

            app_cfg = get_app_config()
            stats['display_name'] = app_cfg.get('server_name') or app_cfg.get('project_name') or 'pinedash'
            stats['server_name'] = stats['display_name']
            stats['project_name'] = app_cfg.get('project_name', 'pinedash')
            # Drive sync status
            sync_last_file = '/run/tinarchy-drive/sync-last'
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

            self.send_compressed(json.dumps(stats).encode(), "application/json")
            
        elif self.path == '/api/system/tor-exit':
            try:
                res = subprocess.run(['sudo', 'iptables', '-t', 'nat', '-L', 'TOR_EXIT'], capture_output=True)
                active = (res.returncode == 0)
            except Exception:
                active = False
            self.send_compressed(json.dumps({"active": active, "enabled": active}).encode(), "application/json")

        else:
            super().do_GET()


    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        session = self.check_auth()

        # ─── Role Management: OWNER ONLY ───
        if self.path == '/api/users/role':
            if session.get('role') != 'owner':
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Only the Owner (Yashwanth Karthik) can change user roles"}')
                return

            target_user = str(data.get('user', '')).strip()
            new_role = str(data.get('role', 'viewer')).strip().lower()
            if new_role not in ['admin', 'viewer']:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Invalid role. Permitted: admin, viewer"}')
                return

            host_owner = get_tailscale_host_owner()
            if target_user in [host_owner.get('login_name'), host_owner.get('display_name')]:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Cannot modify the host Owner role"}')
                return

            cfg = get_roles_config()
            if 'admin_accounts' not in cfg:
                cfg['admin_accounts'] = []
            if 'roles' not in cfg:
                cfg['roles'] = {}

            if new_role == 'admin':
                if target_user not in cfg['admin_accounts']:
                    cfg['admin_accounts'].append(target_user)
                cfg['roles'][target_user] = 'admin'
            else:
                if target_user in cfg['admin_accounts']:
                    cfg['admin_accounts'].remove(target_user)
                cfg['roles'][target_user] = 'viewer'

            save_roles_config(cfg)
            WHOIS_CACHE.clear()

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "user": target_user, "role": new_role}).encode())
            return

        # ─── Wallpapers: ADMIN & OWNER ───
        elif self.path == '/api/wallpaper/select':
            if session.get('role') not in ['owner', 'admin']:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Admin or Owner permissions required"}')
                return

            filename = data.get('filename') or os.path.basename(data.get('url', ''))
            if not filename:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Filename required"}')
                return
            filename = os.path.basename(filename)
            img_path = os.path.join(WALLPAPER_DIR, filename)
            if not os.path.exists(img_path):
                img_path = os.path.join(PUBLIC_DIR, 'Wallpapers', filename)
            
            pywal_data = None
            if os.path.exists(img_path):
                try:
                    pywal_data = pywal_generator.generate_pywal_palette(img_path)
                except Exception as e:
                    print(f"Pywal generation error: {e}")
            
            if not pywal_data:
                pywal_data = pywal_generator.generate_pywal_palette('default_palette')

            try:
                with open(os.path.join(PUBLIC_DIR, 'pywal.json'), 'w') as f_out:
                    json.dump(pywal_data, f_out, indent=2)
            except Exception:
                pass

            self.send_compressed(json.dumps({
                "success": True,
                "url": f"/Wallpapers/{filename}",
                "filename": filename,
                "is_video": filename.lower().endswith('.mp4'),
                "pywal": pywal_data
            }).encode(), "application/json")
            return

        # ─── Drive Sync: POST ───
        elif self.path == '/api/drive/sync':
            try:
                subprocess.Popen(['/usr/local/bin/tinarchy-drive-sync'])
                self.send_compressed(b'{"success": true, "message": "Drive sync triggered"}', "application/json")
            except Exception as e:
                self.send_compressed(json.dumps({"success": False, "error": str(e)}).encode(), "application/json", code=500)
            return

        # ─── Service Toggle: ADMIN & OWNER ───
        elif self.path.startswith('/api/services/') and self.path.endswith('/toggle'):
            if session.get('role') not in ['owner', 'admin']:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Admin or Owner permissions required to manage services"}')
                return

            service_id = self.path.split('/')[3]
            service = next((s for s in SERVICES if s['id'] == service_id), None)
            
            if not service:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Service not found"}')
                return

            action = data.get('action')
            if action not in ['start', 'stop']:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Invalid action"}')
                return

            try:
                subprocess.run(['sudo', 'systemctl', action, service['systemd']], check=True)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            except subprocess.CalledProcessError as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

        # ─── Tor Proxy & Exit Node: ADMIN & OWNER ───
        elif self.path in ['/api/suwayomi/tor', '/api/system/tor-exit']:
            if session.get('role') not in ['owner', 'admin']:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Admin or Owner permissions required for Tor"}')
                return

            if self.path == '/api/suwayomi/tor':
                enable = data.get('enable', False)
                search = 'server.socksProxyEnabled = false' if enable else 'server.socksProxyEnabled = true'
                replace = 'server.socksProxyEnabled = true' if enable else 'server.socksProxyEnabled = false'
                
                try:
                    cmd = f"sudo sed -i 's/{search}/{replace}/' /var/lib/suwayomi/.local/share/Tachidesk/server.conf && sudo systemctl restart suwayomi-server"
                    subprocess.run(cmd, shell=True, check=True)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"success": true}')
                except subprocess.CalledProcessError as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

            elif self.path == '/api/system/tor-exit':
                enable = data.get('enable', False)
                action = 'start' if enable else 'stop'
                try:
                    cmd = f"sudo /home/tin/server-dashboard/tor_exit_node.sh {action}"
                    subprocess.run(cmd, shell=True, check=True)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"success": true}')
                except subprocess.CalledProcessError as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

        # ─── Server Identity Branding: OWNER ONLY ───
        elif self.path == '/api/app/config':
            if session.get('role') != 'owner':
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Only the Owner can configure server branding"}')
                return
            new_name = str(data.get('server_name', '')).strip()
            cfg = get_app_config()
            cfg['server_name'] = new_name
            save_app_config(cfg)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "app_config": cfg}).encode())
            return

        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error": "Endpoint not found"}')


class ThreadingSimpleServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

if __name__ == '__main__':
    ThreadingSimpleServer.allow_reuse_address = True
    with ThreadingSimpleServer(("127.0.0.1", PORT), DashboardHandler) as httpd:
        print(f"Serving Pinedash backend on 127.0.0.1:{PORT}")
        httpd.serve_forever()
