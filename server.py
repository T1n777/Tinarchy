#!/usr/bin/env python3
import os
import re
import json
import gzip
import html
import base64
import socket
import socketserver
import subprocess
import threading
import queue
import time
import http.server

# ─── Modular Tinarchy Core Imports ───
import pywal_generator
from tinarchy import config, telemetry, services, auth, syncthing, reports
from tinarchy.sse import sse_broker

# ─── Backward-Compatibility Re-Exports ───
from tinarchy.config import (
    PORT, PUBLIC_DIR, WALLPAPER_DIR, APP_CONFIG_FILE, ROLES_CONFIG_FILE,
    LOCAL_SERVICES_FILE, PRIMARY_USER, load_env, get_tailscale_domain,
    get_system_hostname, get_app_config, save_app_config
)
from tinarchy.telemetry import (
    get_cpu_percent, get_ram_stats, get_cpu_temp, get_power_supply_status,
    format_speed, format_total
)
from tinarchy.services import (
    SERVICES, get_all_service_ids, is_tailscale_ssh_active,
    trigger_suwayomi_sync_async
)
from tinarchy.auth import (
    get_tailscale_host_owner, get_roles_config, save_roles_config,
    get_user_allowed_services, get_user_role, resolve_tailscale_client,
    get_tailscale_users
)
from tinarchy.syncthing import (
    get_syncthing_home_dir, get_syncthing_cli_cmd, get_syncthing_device_id,
    trigger_drive_sync, start_syncthing_auto_pair_thread
)
from tinarchy.reports import generate_daily_system_report

sse_broker.set_syncthing_module(syncthing)

# ─── Low-Churn API Micro-Caches (Sub-Millisecond Response) ───
_REPORTS_CACHE = {'data': None, 'ts': 0, 'lock': threading.Lock()}

def invalidate_services_cache():
    services.invalidate_services_cache()

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
            if self.command != 'HEAD':
                self.wfile.write(compressed)
        else:
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data_bytes)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data_bytes)

    def end_headers(self):
        if hasattr(self, 'path'):
            if self.path == '/sw.js':
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Service-Worker-Allowed', '/')
            elif (
                self.path.startswith('/Wallpapers/') or
                self.path.startswith('/thumbnails/') or
                self.path.endswith(('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.svg', '.woff2', '.ico'))
            ):
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
        return auth.resolve_tailscale_client(client_ip)

    def serve_html_file(self, rel_path):
        target_file = os.path.join(PUBLIC_DIR, rel_path)
        if not os.path.isfile(target_file):
            self.send_response(404)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(b"<h1>404 Not Found</h1><p>Page not found.</p>")
            return True
        try:
            with open(target_file, 'rb') as f:
                content = f.read()
            self.send_compressed(content, "text/html; charset=utf-8")
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(str(e).encode())
        return True

    def serve_guide_page(self, filename):
        return self.serve_html_file(os.path.join('guides', filename))

    def serve_access_denied(self, service_name="this service"):
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Access Restricted - Server Dashboard</title>
    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    <style>
        :root {{
            --bg: #0b0f14;
            --surface: rgba(20, 26, 33, 0.85);
            --border: rgba(255, 255, 255, 0.08);
            --text: #ffffff;
            --text-muted: #8892b0;
            --accent: #69B4C3;
            --font: system-ui, -apple-system, sans-serif;
        }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: var(--font);
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
            box-sizing: border-box;
        }}
        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            backdrop-filter: blur(20px);
            padding: 36px 32px;
            border-radius: 20px;
            max-width: 460px;
            text-align: center;
            box-shadow: 0 20px 50px rgba(0,0,0,0.5);
        }}
        .icon {{ font-size: 3rem; margin-bottom: 14px; }}
        h1 {{ margin: 0 0 10px 0; font-size: 1.35rem; }}
        p {{ color: var(--text-muted); font-size: 0.9rem; line-height: 1.6; margin: 0 0 24px 0; }}
        .btn {{
            display: inline-block;
            background: var(--accent);
            color: #0b0f14;
            text-decoration: none;
            padding: 10px 24px;
            border-radius: 10px;
            font-weight: 700;
            font-size: 0.9rem;
            transition: opacity 0.2s;
        }}
        .btn:hover {{ opacity: 0.9; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">🔒</div>
        <h1>Access Restricted</h1>
        <p>Your account does not have permission to access <strong>{html.escape(service_name)}</strong>.<br>Please contact the server owner to request access.</p>
        <a href="/" class="btn">Back to Dashboard</a>
    </div>
</body>
</html>"""
        self.send_response(403)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))
        return True

    def handle_service_routes(self):
        raw_path = self.path.split('?')[0].split('#')[0]
        clean_path = raw_path.rstrip('/').lower() if raw_path != '/' else '/'
        if not clean_path or clean_path == '/':
            return False

        if clean_path.startswith('/links'):
            sub = clean_path[6:].strip('/')
            if not sub:
                self.send_response(302)
                self.send_header('Location', '/')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                return True
            clean_path = '/' + sub

        if clean_path in ['/index.html', '/public/index.html']:
            self.send_response(301)
            self.send_header('Location', '/')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            return True

        if clean_path in ['/settings.html', '/public/settings.html']:
            self.send_response(301)
            self.send_header('Location', '/settings')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            return True

        if clean_path == '/settings':
            return self.serve_html_file('settings.html')

        session = self.check_auth()
        role = session.get('role', 'viewer')
        login_name = session.get('login_name', '')
        allowed_services = auth.get_user_allowed_services(login_name, role)

        # Static guide pages
        if clean_path in ['/ssh', '/sshd', '/tailscale-ssh']:
            if 'tailscale-ssh' not in allowed_services:
                return self.serve_access_denied('Tailscale SSH')
            return self.serve_guide_page('ssh.html')

        if clean_path in ['/guides/ssh', '/guides/ssh.html']:
            if 'tailscale-ssh' not in allowed_services:
                return self.serve_access_denied('Tailscale SSH')
            self.send_response(301)
            self.send_header('Location', '/ssh')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            return True

        if clean_path in ['/tor', '/tor-proxy', '/socks5', '/guides/tor', '/guides/tor.html']:
            if 'tor' not in allowed_services:
                return self.serve_access_denied('Tor Proxy')
            return self.serve_guide_page('tor.html')

        if clean_path in ['/syncthing-gui', '/sync-gui']:
            if 'syncthing' not in allowed_services:
                return self.serve_access_denied('Syncthing')
            syncthing_port = int(os.environ.get('SYNCTHING_PORT', 8384))
            raw_host = self.headers.get('Host', '')
            host = raw_host.split(':')[0] if raw_host else get_system_hostname()
            self.send_response(302)
            self.send_header('Location', f"http://{host}:{syncthing_port}/")
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            return True

        if clean_path in ['/syncthing', '/sync', '/guides/syncthing', '/guides/syncthing.html']:
            if 'syncthing' not in allowed_services:
                return self.serve_access_denied('Syncthing')
            if raw_path == '/syncthing/' or raw_path.startswith('/syncthing/'):
                syncthing_port = int(os.environ.get('SYNCTHING_PORT', 8384))
                raw_host = self.headers.get('Host', '')
                host = raw_host.split(':')[0] if raw_host else get_system_hostname()
                self.send_response(302)
                self.send_header('Location', f"http://{host}:{syncthing_port}/")
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                return True
            return self.serve_guide_page('syncthing.html')

        if clean_path in ['/api/suwayomi/sync', '/api/manga/sync']:
            services.trigger_suwayomi_sync_async(force=True)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return True

        if clean_path in ['/syncyomi', '/manga-sync', '/guides/syncyomi', '/guides/syncyomi.html']:
            if any(s['id'] == 'syncyomi' for s in SERVICES):
                if 'syncyomi' not in allowed_services:
                    return self.serve_access_denied('SyncYomi')
            return self.serve_guide_page('syncyomi.html')

        # Top-level application redirects
        raw_host = self.headers.get('Host', '')
        host = raw_host.split(':')[0] if raw_host else get_system_hostname()

        target_url = None
        if clean_path in ['/files', '/file', '/drive', '/quantum', '/filebrowser']:
            if any(s['id'] == 'filebrowser' for s in SERVICES):
                if 'filebrowser' not in allowed_services:
                    return self.serve_access_denied('File Manager')
                target_url = "/files/"
            else:
                target_url = "/syncthing"
        elif clean_path in ['/obsidian', '/sync', '/livesync', '/couchdb']:
            if any(s['id'] == 'couchdb' for s in SERVICES):
                if 'couchdb' not in allowed_services:
                    return self.serve_access_denied('Obsidian LiveSync')
                if os.path.exists(os.path.join(PUBLIC_DIR, 'guides', 'obsidian.html')):
                    return self.serve_guide_page('obsidian.html')
                target_url = "/couchdb/_utils/"
            else:
                target_url = "/syncthing"
        elif clean_path in ['/manga', '/reader', '/tachiyomi', '/suwayomi']:
            if 'suwayomi' not in allowed_services:
                return self.serve_access_denied('Suwayomi Server')
            services.trigger_suwayomi_sync_async()
            target_url = f"https://{host}:4567/"
        elif clean_path in ['/jellyfin', '/media', '/movies', '/stream']:
            if 'jellyfin' not in allowed_services:
                return self.serve_access_denied('Jellyfin Media Server')
            target_url = f"https://{host}:8096/"
        elif clean_path in ['/seerr', '/overseerr', '/requests', '/discover']:
            if 'seerr' not in allowed_services:
                return self.serve_access_denied('Seerr Discovery')
            svc = next((s for s in SERVICES if s.get('id') == 'seerr'), None)
            port = svc.get('port', 5055) if svc else 5055
            target_url = f"https://{host}:{port}/"
        elif clean_path in ['/navidrome', '/music', '/audio']:
            if 'navidrome' not in allowed_services:
                return self.serve_access_denied('Navidrome Music')
            svc = next((s for s in SERVICES if 'navidrome' in s.get('id', '')), None)
            port = svc.get('port', 4533) if svc else 4533
            scheme = svc.get('scheme') or svc.get('protocol') or 'http' if svc else 'http'
            target_url = f"{scheme}://{host}:{port}/"

        if target_url:
            self.send_response(302)
            self.send_header('Location', target_url)
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            return True

        return False

    handle_pseudo_links = handle_service_routes

    def do_HEAD(self):
        if self.handle_service_routes():
            return
        super().do_HEAD()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        clean_path = self.path.split('?')[0]

        # Dynamic client pairing script
        if clean_path in ['/pair', '/pair.sh']:
            pair_script = os.path.join(config.BASE_DIR, 'configs', 'scripts', 'pair-client.sh')
            if os.path.isfile(pair_script):
                with open(pair_script, 'r', encoding='utf-8') as f:
                    content = f.read()
                server_id = syncthing.get_syncthing_device_id()
                app_cfg = config.get_app_config()
                srv_name = app_cfg.get('display_name') or app_cfg.get('server_name') or 'Tinarchy'
                srv_folder_id = os.environ.get('SYNCTHING_SHARED_FOLDER_ID', 'shared')
                srv_folder_label = os.environ.get('SYNCTHING_SHARED_FOLDER_LABEL', 'Shared')
                if server_id:
                    content = re.sub(r'SERVER_ID="\$\{SERVER_ID:-[^}]*\}"', f'SERVER_ID="${{SERVER_ID:-{server_id}}}"', content)
                    content = re.sub(r'SERVER_ID="[^"]*"', f'SERVER_ID="{server_id}"', content)
                content = re.sub(r'SERVER_NAME="\$\{SERVER_NAME:-[^}]*\}"', f'SERVER_NAME="${{SERVER_NAME:-{srv_name}}}"', content)
                content = re.sub(r'SERVER_NAME="[^"]*"', f'SERVER_NAME="{srv_name}"', content)
                content = re.sub(r'FOLDER_ID="\$\{FOLDER_ID:-[^}]*\}"', f'FOLDER_ID="${{FOLDER_ID:-{srv_folder_id}}}"', content)
                content = re.sub(r'FOLDER_ID="[^"]*"', f'FOLDER_ID="{srv_folder_id}"', content)
                content = re.sub(r'FOLDER_LABEL="\$\{FOLDER_LABEL:-[^}]*\}"', f'FOLDER_LABEL="${{FOLDER_LABEL:-{srv_folder_label}}}"', content)
                content = re.sub(r'FOLDER_LABEL="[^"]*"', f'FOLDER_LABEL="{srv_folder_label}"', content)
                content = content.replace('Pineapple Station', srv_name)
                encoded = content.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/x-shellscript; charset=utf-8')
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return

        # 1-Click Tailscale SSH check redirect
        if clean_path in ['/ssh-auth']:
            url_file = '/tmp/tailscale_ssh_url'
            target_url = None
            if os.path.isfile(url_file):
                with open(url_file, 'r', encoding='utf-8') as f:
                    u = f.read().strip()
                    if u.startswith('https://login.tailscale.com/'):
                        target_url = u
            if target_url:
                self.send_response(307)
                self.send_header('Location', target_url)
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                return
            else:
                self.send_response(503)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"<h1>No active Tailscale SSH check session</h1><p>Wait a few seconds and refresh.</p>")
                return

        # Static assets
        if self.path.startswith('/Wallpapers/') or self.path.startswith('/thumbnails/') or self.path.endswith(('.css', '.js', '.png', '.jpg', '.ico', '.woff', '.woff2', '.mp4', '.crt', '.svg', '.webp', '.sh')):
            super().do_GET()
            return

        if self.handle_service_routes():
            return

        session = self.check_auth()

        # ─── REAL-TIME SERVER-SENT EVENTS (SSE) TELEMETRY STREAM ───
        if self.path in ['/api/events/telemetry', '/api/events']:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache, no-transform')
            self.send_header('Connection', 'keep-alive')
            self.send_header('X-Accel-Buffering', 'no')  # Informs Nginx reverse proxy to bypass buffering
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            client_q = sse_broker.subscribe()
            try:
                # 1. Push immediate initial telemetry snapshot so the client doesn't wait
                init_snapshot = telemetry.collect_full_system_snapshot(syncthing)
                self.wfile.write(f"event: telemetry\ndata: {json.dumps(init_snapshot)}\n\n".encode('utf-8'))
                self.wfile.flush()

                # 2. Stream subsequent broadcasts
                while True:
                    try:
                        msg = client_q.get(timeout=15.0)
                        self.wfile.write(msg)
                        self.wfile.flush()
                    except queue.Empty:
                        # Keepalive heartbeat comment to prevent proxy timeouts
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                sse_broker.unsubscribe(client_q)
            return

        elif self.path == '/api/services':
            role = session.get('role', 'viewer')
            login_name = session.get('login_name', '')
            allowed_services = auth.get_user_allowed_services(login_name, role)
            filtered = services.get_services_status(allowed_services)
            self.send_compressed(json.dumps(filtered).encode(), "application/json")

        elif self.path == '/api/me':
            role = session.get('role', 'viewer')
            login_name = session.get('login_name', '')
            self.send_compressed(json.dumps({
                "role": role,
                "display_name": session.get('display_name', 'User'),
                "login_name": login_name,
                "user_id": session.get('user_id'),
                "avatar": session.get('avatar', ''),
                "is_owner": session.get('is_owner', False),
                "device_name": session.get('device_name', ''),
                "allowed_services": auth.get_user_allowed_services(login_name, role)
            }).encode(), "application/json")

        elif self.path == '/api/users':
            role = session.get('role', 'viewer')
            ts_users = [] if role == 'guest' else auth.get_tailscale_users()
            self.send_compressed(json.dumps({
                "current_user": session,
                "tailscale_users": ts_users,
                "roles_config": auth.get_roles_config(),
                "can_manage_roles": (session.get('role') == 'owner'),
                "can_manage_site_access": (session.get('role') in ['owner', 'admin']),
                "available_services": [
                    {
                        "id": s['id'],
                        "name": s['name'],
                        "icon": s.get('icon', '🌐'),
                        "description": s.get('description', '')
                    }
                    for s in SERVICES
                ]
            }).encode(), "application/json")

        elif self.path == '/api/app/config':
            self.send_compressed(json.dumps(config.get_app_config()).encode(), "application/json")

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
                syncthing.trigger_drive_sync()
                self.send_compressed(b'{"success": true, "message": "Drive sync triggered"}', 'application/json')
            except Exception as e:
                self.send_compressed(json.dumps({"success": False, "error": str(e)}).encode(), 'application/json', code=500)

        # Backward-compatible REST telemetry snapshot
        elif self.path == '/api/system':
            stats = telemetry.collect_full_system_snapshot(syncthing)
            self.send_compressed(json.dumps(stats).encode(), "application/json")

        elif self.path == '/api/system/tor-exit':
            role = session.get('role', 'viewer')
            if role == 'guest':
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Guest access restricted"}')
                return

            active = services.is_tor_exit_active()
            self.send_compressed(json.dumps({"active": active, "enabled": active}).encode(), "application/json")

        elif self.path.startswith(('/api/reports/daily', '/api/system/daily-report')):
            force_fresh = 'force=true' in self.path or 'fresh=true' in self.path
            now_t = time.time()
            report_bytes = None
            if not force_fresh:
                with _REPORTS_CACHE['lock']:
                    if _REPORTS_CACHE['data'] and (now_t - _REPORTS_CACHE['ts']) < 5.0:
                        report_bytes = _REPORTS_CACHE['data']
            if report_bytes is None:
                report_data = reports.generate_daily_system_report()
                report_bytes = json.dumps(report_data).encode()
                with _REPORTS_CACHE['lock']:
                    _REPORTS_CACHE['data'] = report_bytes
                    _REPORTS_CACHE['ts'] = now_t
            self.send_compressed(report_bytes, "application/json")

        else:
            super().do_GET()

    def do_POST(self):
        if self.path in ['/api/suwayomi/sync', '/api/manga/sync']:
            services.trigger_suwayomi_sync_async(force=True)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return

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
                self.wfile.write(b'{"error": "Forbidden: Only the Owner can change user roles"}')
                return

            target_user = str(data.get('user', '')).strip()
            new_role = str(data.get('role', 'viewer')).strip().lower()
            try:
                auth.update_user_role(target_user, new_role)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "user": target_user, "role": new_role}).encode())
            except ValueError as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        # ─── Site Access Management: OWNER & ADMIN ───
        elif self.path in ['/api/users/site-access', '/api/users/permissions']:
            if session.get('role') not in ['owner', 'admin']:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Admin or Owner permissions required to manage site access"}')
                return

            target_user = str(data.get('user', '')).strip()
            allowed_services = data.get('allowed_services')
            if not target_user or not isinstance(allowed_services, list):
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Invalid user or allowed_services"}')
                return

            try:
                sanitized = auth.update_user_permissions(target_user, allowed_services)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "user": target_user, "allowed_services": sanitized}).encode())
            except ValueError as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
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

        # ─── Wallpaper Upload: ADMIN & OWNER ───
        elif self.path == '/api/wallpaper/upload':
            if session.get('role') not in ['owner', 'admin']:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Admin or Owner permissions required"}')
                return

            raw_data = data.get('data', '')
            raw_filename = data.get('filename', '')
            if not raw_data or not raw_filename:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Missing image data or filename"}')
                return

            safe_name = os.path.basename(raw_filename)
            safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', safe_name)
            target_dir = os.path.join(PUBLIC_DIR, 'Wallpapers')
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, safe_name)

            try:
                b64_content = raw_data.split(',', 1)[1] if ',' in raw_data else raw_data
                file_bytes = base64.b64decode(b64_content)
                with open(target_path, 'wb') as f_wp:
                    f_wp.write(file_bytes)

                pywal_data = None
                try:
                    pywal_data = pywal_generator.generate_pywal_palette(target_path)
                except Exception as e:
                    print(f"Pywal generation error on upload: {e}")

                if not pywal_data:
                    pywal_data = pywal_generator.generate_pywal_palette('default_palette')

                try:
                    with open(os.path.join(PUBLIC_DIR, 'pywal.json'), 'w') as f_out:
                        json.dump(pywal_data, f_out, indent=2)
                except Exception:
                    pass

                self.send_compressed(json.dumps({
                    "success": True,
                    "url": f"/Wallpapers/{safe_name}",
                    "filename": safe_name,
                    "is_video": safe_name.lower().endswith('.mp4'),
                    "pywal": pywal_data
                }).encode(), "application/json")
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        # ─── Drive Sync: POST ───
        elif self.path == '/api/drive/sync':
            try:
                syncthing.trigger_drive_sync()
                self.send_compressed(b'{"success": true, "message": "Drive sync triggered"}', "application/json")
            except Exception as e:
                self.send_compressed(json.dumps({"success": False, "error": str(e)}).encode(), "application/json", code=500)
            return

        # ─── Service Toggle: ADMIN & OWNER ───
        elif self.path.startswith('/api/services/') and self.path.endswith('/toggle'):
            service_id = self.path.split('/')[3]
            role = session.get('role', 'viewer')

            if role not in ['owner', 'admin']:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Admin or Owner permissions required to manage services"}')
                return

            action = data.get('action')
            try:
                services.toggle_service(service_id, action)
                invalidate_services_cache()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            except ValueError as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

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
                try:
                    services.set_suwayomi_tor(enable)
                    invalidate_services_cache()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"success": true}')
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
                return

            elif self.path == '/api/system/tor-exit':
                enable = data.get('enable', False)
                try:
                    services.set_tor_exit(enable)
                    invalidate_services_cache()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"success": true}')
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
                return

        # ─── Server Identity Branding: OWNER ONLY ───
        elif self.path == '/api/app/config':
            if session.get('role') != 'owner':
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Only the Owner can configure server branding"}')
                return
            new_name = str(data.get('server_name', '')).strip()
            cfg = config.get_app_config()
            cfg['server_name'] = new_name
            config.save_app_config(cfg)
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
    daemon_threads = True

if __name__ == '__main__':
    ThreadingSimpleServer.allow_reuse_address = True
    bind_host = os.environ.get('HOST', '127.0.0.1')
    app_cfg = config.get_app_config()
    syncthing.start_syncthing_auto_pair_thread()
    with ThreadingSimpleServer((bind_host, PORT), DashboardHandler) as httpd:
        print(f"Serving {app_cfg.get('project_name', 'Tinarchy')} backend ({app_cfg.get('display_name')}) on {bind_host}:{PORT}")
        httpd.serve_forever()
