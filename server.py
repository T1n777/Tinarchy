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
import sys
import traceback

# ─── Modular Tinarchy Core Imports ───
import pywal_generator
from tinarchy import config, telemetry, services, auth, syncthing, reports, thumbnails
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
            clean_p = self.path.split('?')[0].split('#')[0]
            if clean_p in ['/', '/index.html', '/settings', '/settings.html', '/sw.js', '/install.sh', '/install', '/bootstrap.sh', '/bootstrap', '/suwayomi-vault.js']:
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                if clean_p == '/sw.js':
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
            if services.is_syncyomi_active():
                services.trigger_suwayomi_sync_async(force=True)
                res_body = b'{"status": "ok"}'
            else:
                res_body = b'{"status": "skipped", "reason": "SyncYomi service is inactive"}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(res_body)
            return True

        if clean_path in ['/syncyomi', '/manga-sync', '/guides/syncyomi', '/guides/syncyomi.html']:
            if any(s['id'] == 'syncyomi' for s in SERVICES):
                if 'syncyomi' not in allowed_services:
                    return self.serve_access_denied('SyncYomi')
            return self.serve_guide_page('syncyomi.html')

        if clean_path in ['/vault-guide', '/guides/vaultwarden', '/guides/vaultwarden.html', '/bitwarden-guide']:
            if 'vaultwarden' not in allowed_services:
                return self.serve_access_denied('Vaultwarden')
            return self.serve_guide_page('vaultwarden.html')

        if clean_path in ['/beeper', '/beeper-guide', '/bbctl', '/guides/beeper', '/guides/beeper.html']:
            if 'beeper' not in allowed_services:
                return self.serve_access_denied('Beeper Bridge Manager')
            return self.serve_guide_page('beeper.html')

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
        elif clean_path in ['/manga', '/reader', '/tachiyomi', '/suwayomi'] or clean_path.startswith(('/manga/', '/reader/', '/tachiyomi/', '/suwayomi/')):
            if 'suwayomi' not in allowed_services:
                return self.serve_access_denied('Suwayomi Server')
            services.trigger_suwayomi_sync_async()
            sub = clean_path
            for prefix in ['/reader', '/tachiyomi', '/suwayomi']:
                if sub.startswith(prefix):
                    sub = '/manga' + sub[len(prefix):]
            if sub.startswith('/manga/manga/'):
                pass
            elif re.match(r'^/manga/\d+', sub):
                sub = '/manga/manga/' + sub[len('/manga/'):]
            elif sub == '/manga/history':
                sub = '/manga/history'
            elif sub == '/manga/updates':
                sub = '/manga/updates'
            elif sub.startswith('/manga/'):
                pass
            else:
                sub = '/manga/'
            query = ('?' + self.path.split('?', 1)[1]) if '?' in self.path else ''
            target_url = f"http://{host}:4567{sub}{query}"
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
        elif clean_path in ['/vaultwarden', '/vault', '/bitwarden', '/passwords']:
            if 'vaultwarden' not in allowed_services:
                return self.serve_access_denied('Vaultwarden Password Manager')
            svc = next((s for s in SERVICES if s.get('id') == 'vaultwarden'), None)
            port = svc.get('port', 8000) if svc else 8000
            target_url = f"https://{host}:{port}/"
        elif clean_path in ['/navidrome', '/music', '/audio']:
            if 'navidrome' not in allowed_services:
                return self.serve_access_denied('Navidrome Music')
            svc = next((s for s in SERVICES if 'navidrome' in s.get('id', '')), None)
            port = svc.get('port', 4533) if svc else 4533
            scheme = svc.get('scheme') or svc.get('protocol') or 'http' if svc else 'http'
            target_url = f"{scheme}://{host}:{port}/"
        elif clean_path in ['/radarr']:
            if 'radarr' not in allowed_services:
                return self.serve_access_denied('Radarr')
            svc = next((s for s in SERVICES if s.get('id') == 'radarr'), None)
            port = svc.get('port', 7878) if svc else 7878
            target_url = f"http://{host}:{port}/"
        elif clean_path in ['/sonarr']:
            if 'sonarr' not in allowed_services:
                return self.serve_access_denied('Sonarr')
            svc = next((s for s in SERVICES if s.get('id') == 'sonarr'), None)
            port = svc.get('port', 8989) if svc else 8989
            target_url = f"http://{host}:{port}/"
        elif clean_path in ['/prowlarr']:
            if 'prowlarr' not in allowed_services:
                return self.serve_access_denied('Prowlarr')
            svc = next((s for s in SERVICES if s.get('id') == 'prowlarr'), None)
            port = svc.get('port', 9696) if svc else 9696
            target_url = f"http://{host}:{port}/"
        elif clean_path in ['/qbittorrent', '/qbit', '/torrents']:
            if 'qbittorrent' not in allowed_services:
                return self.serve_access_denied('qBittorrent')
            target_url = "/qbittorrent/"
        elif clean_path in ['/bazarr', '/subtitles']:
            if 'bazarr' not in allowed_services:
                return self.serve_access_denied('Bazarr')
            target_url = "/bazarr/"

        if not target_url:
            svc_name = clean_path.lstrip('/')
            matched_svc = next((s for s in SERVICES if s.get('id') == svc_name), None)
            if matched_svc and matched_svc.get('port'):
                if matched_svc['id'] not in allowed_services:
                    return self.serve_access_denied(matched_svc.get('name', matched_svc['id']))
                scheme = matched_svc.get('scheme') or matched_svc.get('protocol') or 'http'
                target_url = f"{scheme}://{host}:{matched_svc['port']}/"

        if target_url:
            self.send_response(302)
            self.send_header('Location', target_url)
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            return True

        return False

    handle_pseudo_links = handle_service_routes

    def do_HEAD(self):
        clean_path = self.path.split('?')[0]
        if clean_path.startswith('/api/suwayomi/thumbnail/'):
            try:
                parts = clean_path.rstrip('/').split('/')
                manga_id = int(parts[-1])
                from tinarchy.thumbnails import get_or_generate_thumbnail, is_manga_private
                if is_manga_private(manga_id):
                    session = self.check_auth()
                    if session.get('role') not in ['owner', 'admin']:
                        self.send_response(404)
                        self.end_headers()
                        return
                query_string = self.path.split('?')[1] if '?' in self.path else ''
                data, ctype = get_or_generate_thumbnail(manga_id, query_string=query_string)
                if data:
                    self.send_response(200)
                    self.send_header('Content-Type', ctype)
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('Cache-Control', 'public, max-age=5184000, immutable')
                    self.send_header('X-Thumbnail-Engine', 'ON-DEMAND-DYNAMIC-OPTIMIZER')
                    self.end_headers()
                    return
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
            except Exception as e:
                print(f"[ERROR] Thumbnail HEAD generation failed for {clean_path}: {e}", file=sys.stderr)
                traceback.print_exc()
                self.send_response(500)
                self.end_headers()
                return

        if clean_path in ['/install.sh', '/install', '/bootstrap.sh', '/bootstrap']:
            install_script = os.path.join(config.BASE_DIR, 'install.sh')
            if os.path.isfile(install_script):
                self.send_response(200)
                self.send_header('Content-Type', 'text/x-shellscript; charset=utf-8')
                self.send_header('Content-Length', str(os.path.getsize(install_script)))
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        if clean_path in ['/pair', '/pair.sh']:
            pair_script = os.path.join(config.BASE_DIR, 'configs', 'scripts', 'pair-client.sh')
            if os.path.isfile(pair_script):
                self.send_response(200)
                self.send_header('Content-Type', 'text/x-shellscript; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

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

        # Universal shell installer & remote bootstrap endpoint
        if clean_path in ['/install.sh', '/install', '/bootstrap.sh', '/bootstrap']:
            install_script = os.path.join(config.BASE_DIR, 'install.sh')
            if os.path.isfile(install_script):
                with open(install_script, 'rb') as f:
                    script_bytes = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/x-shellscript; charset=utf-8')
                self.send_header('Content-Length', str(len(script_bytes)))
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                self.wfile.write(script_bytes)
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

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

        # On-demand Suwayomi thumbnail optimization fast-path
        if clean_path.startswith('/api/suwayomi/thumbnail/'):
            try:
                parts = clean_path.rstrip('/').split('/')
                manga_id = int(parts[-1])
                from tinarchy.thumbnails import get_or_generate_thumbnail, is_manga_private
                if is_manga_private(manga_id):
                    session = self.check_auth()
                    if session.get('role') not in ['owner', 'admin']:
                        self.send_response(404)
                        self.end_headers()
                        return
                query_string = self.path.split('?')[1] if '?' in self.path else ''
                data, ctype = get_or_generate_thumbnail(manga_id, query_string=query_string)
                if data:
                    self.send_response(200)
                    self.send_header('Content-Type', ctype)
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('Cache-Control', 'public, max-age=5184000, immutable')
                    self.send_header('X-Thumbnail-Engine', 'ON-DEMAND-DYNAMIC-OPTIMIZER')
                    self.end_headers()
                    self.wfile.write(data)
                    return
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
            except Exception as e:
                print(f"[ERROR] Thumbnail GET generation failed for {clean_path}: {e}", file=sys.stderr)
                traceback.print_exc()
                self.send_response(500)
                self.end_headers()
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

        elif self.path == '/api/categories':
            self.send_compressed(json.dumps(services.get_categories()).encode(), "application/json")

        elif self.path == '/api/dashboard/layout':
            from tinarchy import dashboard_layout
            import copy
            raw_layout = dashboard_layout.load_dashboard_layout()
            layout = copy.deepcopy(raw_layout)
            role = session.get('role', 'viewer')
            if role not in ['owner', 'admin']:
                login_name = session.get('login_name', '')
                allowed_svcs = auth.get_user_allowed_services(login_name, role)
                _widget_svc_map = {
                    'qbittorrent': 'qbittorrent',
                    'jdownloader': 'jdownloader',
                    'manga_shelf': 'suwayomi',
                }
                if 'widgets' in layout and isinstance(layout['widgets'], dict):
                    for wid, svc in _widget_svc_map.items():
                        if svc not in allowed_svcs and wid in layout['widgets']:
                            layout['widgets'][wid]['enabled'] = False
                if 'widget_stacks' in layout and isinstance(layout['widget_stacks'], list):
                    for st in layout['widget_stacks']:
                        if 'widgets' in st and isinstance(st['widgets'], list):
                            st['widgets'] = [w for w in st['widgets'] if _widget_svc_map.get(w, '') in allowed_svcs or w not in _widget_svc_map]
                    layout['widget_stacks'] = [st for st in layout['widget_stacks'] if st.get('widgets')]
            self.send_compressed(json.dumps(layout).encode(), "application/json")

        elif self.path == '/api/widgets/qbittorrent':
            _w_role = session.get('role', 'viewer')
            _w_allowed = auth.get_user_allowed_services(session.get('login_name', ''), _w_role)
            if 'qbittorrent' not in _w_allowed:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Access denied"}')
                return
            import urllib.request
            qbit_info = {"online": False}
            try:
                req = urllib.request.Request("http://127.0.0.1:8084/api/v2/transfer/info")
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode())
                        qbit_info = {
                            "online": True,
                            "dl_speed": data.get("dl_info_speed", 0),
                            "up_speed": data.get("up_info_speed", 0),
                            "dht_nodes": data.get("dht_nodes", 0),
                            "connection_status": data.get("connection_status", "connected"),
                            "total_torrents": 0,
                            "active_torrents": 0
                        }
                        try:
                            req_t = urllib.request.Request("http://127.0.0.1:8084/api/v2/torrents/info?filter=all")
                            with urllib.request.urlopen(req_t, timeout=1.5) as r_t:
                                if r_t.status == 200:
                                    t_data = json.loads(r_t.read().decode())
                                    qbit_info["total_torrents"] = len(t_data)
                                    qbit_info["active_torrents"] = sum(1 for t in t_data if t.get("state") in ("downloading", "uploading", "stalledDL", "stalledUP"))
                        except Exception:
                            pass
            except Exception:
                pass
            self.send_compressed(json.dumps(qbit_info).encode(), "application/json")

        elif self.path == '/api/widgets/manga':
            _w_role = session.get('role', 'viewer')
            _w_allowed = auth.get_user_allowed_services(session.get('login_name', ''), _w_role)
            if 'suwayomi' not in _w_allowed:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Access denied"}')
                return
            import urllib.request
            shelf_info = {"online": False, "history": [], "updates": [], "library": [], "mangas": []}
            gql_candidates = [
                "http://127.0.0.1:4567/manga/api/graphql",
                "http://127.0.0.1:4567/api/graphql",
                "http://127.0.0.1:4566/api/graphql",
                "http://127.0.0.1:8080/manga/api/graphql",
            ]
            gql_query = json.dumps({
                "query": """{
                    history: chapters(order: { by: LAST_READ_AT, byType: DESC_NULLS_LAST }, first: 100) {
                        nodes {
                            lastReadAt
                            manga {
                                id
                                title
                                categories { nodes { id name } }
                            }
                        }
                    }
                    updates: chapters(order: { by: FETCHED_AT, byType: DESC_NULLS_LAST }, first: 100) {
                        nodes {
                            name
                            fetchedAt
                            manga {
                                id
                                title
                                categories { nodes { id name } }
                            }
                        }
                    }
                    library: mangas(filter: { inLibrary: { equalTo: true } }, order: { by: IN_LIBRARY_AT, byType: DESC_NULLS_LAST }, first: 300) {
                        nodes {
                            id
                            title
                            categories { nodes { id name } }
                        }
                    }
                }"""
            }).encode('utf-8')
            auth_hdr = thumbnails.get_suwayomi_auth_header()
            headers = {"Content-Type": "application/json"}
            if auth_hdr:
                headers["Authorization"] = auth_hdr
            for ep in gql_candidates:
                try:
                    req = urllib.request.Request(ep, data=gql_query, headers=headers)
                    with urllib.request.urlopen(req, timeout=8.0) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode())
                            data_obj = data.get("data") or {}
                            h_nodes = (data_obj.get("history") or {}).get("nodes") or []
                            u_nodes = (data_obj.get("updates") or {}).get("nodes") or []
                            l_nodes = (data_obj.get("library") or {}).get("nodes") or []

                            def is_private_manga(m_obj):
                                if not m_obj:
                                    return True
                                cats = [c.get("name", "").strip() for c in (m_obj.get("categories") or {}).get("nodes", [])]
                                return "_" in cats or "private" in [c.lower() for c in cats]

                            # 1. Reading History (Most recently read)
                            clean_history = []
                            seen_h = set()
                            for ch in h_nodes:
                                if not ch.get("lastReadAt"):
                                    continue
                                m = ch.get("manga")
                                if not m or not m.get("id"):
                                    continue
                                mid = m["id"]
                                if mid in seen_h or is_private_manga(m):
                                    continue
                                seen_h.add(mid)
                                clean_history.append({
                                    "id": mid,
                                    "title": m.get("title", ""),
                                    "cover": f"/api/suwayomi/thumbnail/{mid}",
                                    "link": f"/manga/manga/{mid}",
                                    "lastReadAt": ch.get("lastReadAt")
                                })
                                if len(clean_history) >= 24:
                                    break

                            # 2. Latest Updates (Most recently fetched chapters)
                            clean_updates = []
                            seen_u = set()
                            for ch in u_nodes:
                                m = ch.get("manga")
                                if not m or not m.get("id"):
                                    continue
                                mid = m["id"]
                                if mid in seen_u or is_private_manga(m):
                                    continue
                                seen_u.add(mid)
                                clean_updates.append({
                                    "id": mid,
                                    "title": m.get("title", ""),
                                    "cover": f"/api/suwayomi/thumbnail/{mid}",
                                    "link": f"/manga/manga/{mid}",
                                    "chapterName": ch.get("name") or "",
                                    "fetchedAt": ch.get("fetchedAt") or ""
                                })
                                if len(clean_updates) >= 24:
                                    break

                            # 3. Library (Only mangas in the 'Reading' category)
                            clean_library = []
                            seen_l = set()
                            for m in l_nodes:
                                if not m or not m.get("id"):
                                    continue
                                mid = m["id"]
                                if mid in seen_l or is_private_manga(m):
                                    continue
                                cats = [c.get("name", "").strip() for c in (m.get("categories") or {}).get("nodes", [])]
                                if not any(c.lower() == "reading" for c in cats):
                                    continue
                                seen_l.add(mid)
                                clean_library.append({
                                    "id": mid,
                                    "title": m.get("title", ""),
                                    "cover": f"/api/suwayomi/thumbnail/{mid}",
                                    "link": f"/manga/manga/{mid}"
                                })
                                if len(clean_library) >= 24:
                                    break

                            # Fallback: if user has no mangas categorized as 'Reading', show in-library mangas
                            if len(clean_library) == 0:
                                for m in l_nodes:
                                    if not m or not m.get("id"):
                                        continue
                                    mid = m["id"]
                                    if mid in seen_l or is_private_manga(m):
                                        continue
                                    seen_l.add(mid)
                                    clean_library.append({
                                        "id": mid,
                                        "title": m.get("title", ""),
                                        "cover": f"/api/suwayomi/thumbnail/{mid}",
                                        "link": f"/manga/manga/{mid}"
                                    })
                                    if len(clean_library) >= 24:
                                        break

                            # Backwards-compatible default list
                            clean_mangas = clean_history if clean_history else clean_library

                            shelf_info = {
                                "online": True,
                                "history": clean_history,
                                "updates": clean_updates,
                                "library": clean_library,
                                "mangas": clean_mangas
                            }
                            break
                except Exception:
                    continue
            self.send_compressed(json.dumps(shelf_info).encode(), "application/json")

        elif self.path == '/api/widgets/jdownloader':
            _w_role = session.get('role', 'viewer')
            _w_allowed = auth.get_user_allowed_services(session.get('login_name', ''), _w_role)
            if 'jdownloader' not in _w_allowed:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Access denied"}')
                return
            from tinarchy import jdownloader
            jd_info = jdownloader.get_jdownloader_status()
            self.send_compressed(json.dumps(jd_info).encode(), "application/json")

        elif self.path == '/api/beeper/status':
            from tinarchy.services import get_beeper_bridges_status
            bb_status = get_beeper_bridges_status()
            try:
                whoami_res = subprocess.run(['/home/tin/.local/bin/bbctl', 'whoami'], capture_output=True, text=True, timeout=3)
                bb_status['whoami'] = whoami_res.stdout.strip()
            except Exception:
                bb_status['whoami'] = "Unable to check whoami"
            self.send_compressed(json.dumps(bb_status).encode(), "application/json")

        elif self.path == '/api/me':
            role = session.get('role', 'viewer')
            login_name = session.get('login_name', '')
            allowed_svcs = auth.get_user_allowed_services(login_name, role)
            # Map service IDs to widget IDs for the frontend
            _widget_svc_map = {
                'qbittorrent': 'qbittorrent',
                'jdownloader': 'jdownloader',
                'manga_shelf': 'suwayomi',
            }
            allowed_widgets = [wid for wid, svc in _widget_svc_map.items() if svc in allowed_svcs]
            self.send_compressed(json.dumps({
                "role": role,
                "display_name": session.get('display_name', 'User'),
                "login_name": login_name,
                "user_id": session.get('user_id'),
                "avatar": session.get('avatar', ''),
                "is_owner": session.get('is_owner', False),
                "device_name": session.get('device_name', ''),
                "allowed_services": allowed_svcs,
                "allowed_widgets": allowed_widgets
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
            if services.is_syncyomi_active():
                services.trigger_suwayomi_sync_async(force=True)
                res_body = b'{"status": "ok"}'
            else:
                res_body = b'{"status": "skipped", "reason": "SyncYomi service is inactive"}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(res_body)
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

        # ─── Homarr Dashboard Layout Management: OWNER & ADMIN ───
        elif self.path == '/api/dashboard/layout':
            if session.get('role') not in ['owner', 'admin']:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Admin or Owner permissions required"}')
                return
            try:
                from tinarchy import dashboard_layout
                dashboard_layout.save_dashboard_layout(data)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        elif self.path == '/api/dashboard/layout/reset':
            if session.get('role') not in ['owner', 'admin']:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Admin or Owner permissions required"}')
                return
            from tinarchy import dashboard_layout
            def_layout = dashboard_layout.reset_dashboard_layout()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "layout": def_layout}).encode())
            return

        # ─── Wallpapers: SELECT ───
        elif self.path == '/api/wallpaper/select':
            role = session.get('role', 'viewer')
            if role not in ['owner', 'admin', 'viewer']:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Authenticated access required"}')
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

            # Only admin and owner overwrite the server-wide default pywal.json
            if role in ['owner', 'admin']:
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

        # ─── Wallpaper Upload ───
        elif self.path == '/api/wallpaper/upload':
            role = session.get('role', 'viewer')
            if role not in ['owner', 'admin', 'viewer']:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Authenticated access required"}')
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

                # Only admin and owner overwrite the server-wide default pywal.json
                if role in ['owner', 'admin']:
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

        # ─── JDownloader Link Submission ───
        elif self.path == '/api/widgets/jdownloader/add':
            _jd_role = session.get('role', 'viewer')
            _jd_allowed = auth.get_user_allowed_services(session.get('login_name', ''), _jd_role)
            if 'jdownloader' not in _jd_allowed:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Access denied"}')
                return

            links = str(data.get('links', '')).strip()
            autostart = bool(data.get('autostart', True))
            package_name = data.get('packageName')
            if not links:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "No download links provided"}')
                return

            try:
                from tinarchy import jdownloader
                res = jdownloader.add_download_links(links, autostart=autostart, package_name=package_name)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "result": res}).encode())
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
