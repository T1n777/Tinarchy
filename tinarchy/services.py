import os
import json
import subprocess
import threading
import time
from tinarchy.config import PRIMARY_USER, LOCAL_SERVICES_FILE, BASE_DIR

# Core Service Toggles (configurable via .env, default: true)
ENABLE_SUWAYOMI = os.environ.get('ENABLE_SUWAYOMI', 'true').strip().lower() in ('true', '1', 'yes')
ENABLE_JELLYFIN = os.environ.get('ENABLE_JELLYFIN', 'true').strip().lower() in ('true', '1', 'yes')
ENABLE_TOR = os.environ.get('ENABLE_TOR', 'true').strip().lower() in ('true', '1', 'yes')
ENABLE_TAILSCALE_SSH = os.environ.get('ENABLE_TAILSCALE_SSH', 'true').strip().lower() in ('true', '1', 'yes')
ENABLE_SYNCTHING = os.environ.get('ENABLE_SYNCTHING', 'true').strip().lower() in ('true', '1', 'yes')

SERVICES = []
if ENABLE_SUWAYOMI:
    SERVICES.append({'id': 'suwayomi', 'name': 'Suwayomi Server', 'port': int(os.environ.get('SUWAYOMI_PORT', 4567)), 'systemd': 'suwayomi-server', 'icon': '📚', 'description': 'Manga library and reader'})
if ENABLE_JELLYFIN:
    SERVICES.append({'id': 'jellyfin', 'name': 'Jellyfin Media Server', 'port': int(os.environ.get('JELLYFIN_PORT', 8096)), 'systemd': 'jellyfin', 'icon': '🍿', 'description': 'Movies, TV shows & media streaming'})
if ENABLE_TOR:
    SERVICES.append({'id': 'tor', 'name': 'Tor Proxy', 'port': int(os.environ.get('TOR_SOCKS_PORT', 9050)), 'systemd': 'tor', 'icon': '🧅', 'description': 'SOCKS5 anonymity proxy'})
if ENABLE_TAILSCALE_SSH:
    SERVICES.append({'id': 'tailscale-ssh', 'name': 'Tailscale SSH', 'port': int(os.environ.get('SSH_PORT', 22)), 'systemd': 'tailscaled', 'systemd_name': 'tailscale ssh', 'icon': '🔑', 'description': 'Keyless mesh shell access via Tailscale', 'link': '/ssh', 'link_text': '/ssh'})
if ENABLE_SYNCTHING:
    SERVICES.append({'id': 'syncthing', 'name': 'Syncthing', 'port': int(os.environ.get('SYNCTHING_PORT', 8384)), 'systemd': f"syncthing@{PRIMARY_USER}", 'icon': '🔄', 'description': 'Continuous, encrypted folder sync for personal devices', 'link': '/syncthing', 'link_text': '/syncthing'})

# Optional Services (toggleable via .env)
ENABLE_SYNCYOMI = os.environ.get('ENABLE_SYNCYOMI', 'false').strip().lower() in ('true', '1', 'yes')
if ENABLE_SYNCYOMI:
    syncyomi_port = int(os.environ.get('SYNCYOMI_PORT', 8282))
    SERVICES.append({
        'id': 'syncyomi',
        'name': 'SyncYomi',
        'port': syncyomi_port,
        'systemd': 'syncyomi',
        'icon': '📖',
        'description': 'Tachiyomi, Mihon & Suwayomi manga reading progress sync',
        'link': '/syncyomi',
        'link_text': f':{syncyomi_port}'
    })

ENABLE_FILEBROWSER = os.environ.get('ENABLE_FILEBROWSER', 'false').strip().lower() in ('true', '1', 'yes')
if ENABLE_FILEBROWSER:
    filebrowser_port = int(os.environ.get('FILEBROWSER_PORT', 8081))
    filebrowser_unit = os.environ.get('FILEBROWSER_SYSTEMD', 'filebrowser-quantum')
    SERVICES.append({
        'id': 'filebrowser',
        'name': 'File Manager',
        'port': filebrowser_port,
        'systemd': filebrowser_unit,
        'icon': '📂',
        'description': 'Modern web-based file manager',
        'link': '/files',
        'link_text': f':{filebrowser_port}'
    })

ENABLE_COUCHDB = os.environ.get('ENABLE_COUCHDB', 'false').strip().lower() in ('true', '1', 'yes')
if ENABLE_COUCHDB:
    couchdb_port = int(os.environ.get('COUCHDB_PORT', 5984))
    SERVICES.append({
        'id': 'couchdb',
        'name': 'Obsidian LiveSync',
        'port': couchdb_port,
        'systemd': 'couchdb',
        'icon': '🔮',
        'description': 'Real-time E2EE sync backend for Obsidian vaults',
        'link': '/obsidian',
        'link_text': f':{couchdb_port}'
    })

# Load optional machine-specific services
if os.path.exists(LOCAL_SERVICES_FILE):
    try:
        with open(LOCAL_SERVICES_FILE, 'r') as f:
            local_svcs = json.load(f)
            if isinstance(local_svcs, list):
                SERVICES.extend(local_svcs)
    except Exception as e:
        print(f'Error loading local services: {e}')

def get_all_service_ids():
    try:
        return [s['id'] for s in SERVICES]
    except Exception:
        return ['suwayomi', 'jellyfin', 'tor', 'tailscale-ssh', 'syncthing', 'syncyomi', 'filebrowser', 'couchdb']

def is_tailscale_ssh_active():
    try:
        res = subprocess.run(['tailscale', 'debug', 'prefs'], capture_output=True, text=True, timeout=1)
        if res.returncode == 0:
            return '"RunSSH": true' in res.stdout
    except Exception:
        pass
    return False

def trigger_suwayomi_sync_async(force=False):
    def _run():
        try:
            cmd = ['/usr/local/bin/suwayomi-trigger-sync']
            if force:
                cmd.append('--force')
            subprocess.run(cmd, capture_output=True, timeout=15)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()

_SERVICES_STATUS_CACHE = {'data': None, 'ts': 0}

def get_services_status(allowed_services=None):
    global _SERVICES_STATUS_CACHE
    now = time.time()
    if not _SERVICES_STATUS_CACHE['data'] or (now - _SERVICES_STATUS_CACHE['ts']) >= 3:
        units = [s['systemd'] for s in SERVICES]
        unit_status = {}
        try:
            res = subprocess.run(['systemctl', 'is-active'] + units, capture_output=True, text=True, timeout=2)
            lines = res.stdout.strip().splitlines()
            for u, line in zip(units, lines):
                unit_status[u] = 'online' if line.strip() == 'active' else 'offline'
        except Exception:
            pass

        tor_proxy_enabled = False
        for sc in ['/var/lib/suwayomi/server.conf', '/var/lib/suwayomi/.local/share/Tachidesk/server.conf']:
            if os.path.isfile(sc):
                try:
                    with open(sc, 'r') as sf:
                        if 'server.socksProxyEnabled = true' in sf.read():
                            tor_proxy_enabled = True
                            break
                except Exception:
                    pass

        base_results = []
        ts_ssh_on = is_tailscale_ssh_active()
        for s in SERVICES:
            status_obj = s.copy()
            if s['id'] == 'tailscale-ssh':
                status_obj['status'] = 'online' if (unit_status.get('tailscaled') == 'online' and ts_ssh_on) else 'offline'
            else:
                status_obj['status'] = unit_status.get(s['systemd'], 'offline')

            if s['id'] == 'suwayomi':
                status_obj['torProxyEnabled'] = tor_proxy_enabled

            if 'link' in s:
                service_link = s['link']
            else:
                service_link = f"/{s['id']}"
                if s['id'] == 'filebrowser':
                    service_link = '/files'
                elif s['id'] == 'couchdb':
                    service_link = '/obsidian'
                elif s['id'] == 'suwayomi':
                    service_link = '/manga'
                elif s['id'] == 'tor':
                    service_link = '/tor'
                elif 'navidrome' in s['id']:
                    service_link = '/navidrome'
            status_obj['link'] = service_link
            base_results.append(status_obj)

        _SERVICES_STATUS_CACHE = {'data': base_results, 'ts': now}

    if allowed_services is None:
        return _SERVICES_STATUS_CACHE['data']
    return [s for s in _SERVICES_STATUS_CACHE['data'] if s['id'] in allowed_services]

def toggle_service(service_id: str, action: str):
    service = next((s for s in SERVICES if s['id'] == service_id), None)
    if not service:
        raise ValueError("Service not found")
    if action not in ['start', 'stop']:
        raise ValueError("Invalid action. Permitted: start, stop")

    if service_id == 'tailscale-ssh':
        ssh_val = 'true' if action == 'start' else 'false'
        subprocess.run(['tailscale', 'set', f'--ssh={ssh_val}', '--accept-risk=lose-ssh'], check=True, timeout=5)
    else:
        subprocess.run(['sudo', 'systemctl', action, service['systemd']], check=True)

    global _SERVICES_STATUS_CACHE
    _SERVICES_STATUS_CACHE['ts'] = 0

def set_suwayomi_tor(enable: bool):
    val = 'true' if enable else 'false'
    for path in ['/var/lib/suwayomi/server.conf', '/var/lib/suwayomi/.local/share/Tachidesk/server.conf']:
        if os.path.exists(path):
            cmd = f"sudo sed -i --follow-symlinks -E 's/^(server\\.socksProxyEnabled\\s*=\\s*)(true|false)/\\1{val}/' {path}"
            subprocess.run(cmd, shell=True, check=False)
    subprocess.run(['sudo', 'systemctl', 'restart', 'suwayomi-server'], check=True)

def set_tor_exit(enable: bool):
    action = 'start' if enable else 'stop'
    if enable:
        chk_tor = subprocess.run(['systemctl', 'is-active', 'tor'], capture_output=True, text=True)
        if chk_tor.stdout.strip() != 'active':
            subprocess.run(['sudo', 'systemctl', 'start', 'tor'], check=True)

    tor_script = os.path.join(BASE_DIR, 'configs', 'scripts', 'tor_exit_node.sh')
    cmd = f"sudo {tor_script} {action}"
    subprocess.run(cmd, shell=True, check=True)
