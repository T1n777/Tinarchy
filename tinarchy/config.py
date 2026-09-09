import os
import json
import socket
import subprocess
import time

def load_env():
    env_paths = [
        os.environ.get('TINARCHY_ENV_FILE', ''),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'),
        '/etc/tinarchy/tinarchy.env'
    ]
    for env_path in env_paths:
        if env_path and os.path.exists(env_path):
            try:
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if '=' in line and not line.startswith('#'):
                            k, v = line.split('=', 1)
                            k = k.strip()
                            v = v.strip().strip('"\'')
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass

load_env()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')
WALLPAPER_DIR = (
    os.path.join(os.path.expanduser('~'), 'Wall')
    if os.path.isdir(os.path.join(os.path.expanduser('~'), 'Wall'))
    else os.path.join(PUBLIC_DIR, 'Wallpapers')
)
APP_CONFIG_FILE = os.path.join(BASE_DIR, 'app_config.json')
ROLES_CONFIG_FILE = os.path.join(BASE_DIR, 'roles_config.json')
LOCAL_SERVICES_FILE = os.path.join(BASE_DIR, 'services.local.json')

PORT = int(os.environ.get('PORT', 8085))
PRIMARY_USER = (
    os.environ.get('SSH_USER')
    or ('tin' if os.path.isdir('/home/tin') else ('pineapple' if os.path.isdir('/home/pineapple') else (os.environ.get('SUDO_USER') or os.environ.get('USER', 'tin'))))
)

_TAILSCALE_DNS_CACHE = {'domain': None, 'ts': 0}

def get_tailscale_domain():
    env_dom = os.environ.get('TAILSCALE_DOMAIN')
    if env_dom:
        return env_dom
    global _TAILSCALE_DNS_CACHE
    now_t = time.time()
    if _TAILSCALE_DNS_CACHE['domain'] and (now_t - _TAILSCALE_DNS_CACHE['ts']) < 120:
        return _TAILSCALE_DNS_CACHE['domain']
    try:
        res = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            d = json.loads(res.stdout)
            dns = d.get('Self', {}).get('DNSName', '').rstrip('.')
            if dns:
                _TAILSCALE_DNS_CACHE = {'domain': dns, 'ts': now_t}
                return dns
    except Exception:
        pass
    fallback = os.environ.get('SERVER_NAME') or socket.gethostname()
    return _TAILSCALE_DNS_CACHE.get('domain') or fallback

def get_system_hostname():
    try:
        return socket.gethostname() or os.uname().nodename or 'server'
    except Exception:
        return 'server'

def get_app_config():
    sys_name = get_system_hostname()
    env_server_name = os.environ.get('SERVER_NAME', '')
    env_project_name = os.environ.get('PROJECT_NAME', '')
    env_app_icon = os.environ.get('APP_ICON', '🍍')
    env_subtitle = os.environ.get('BRANDING_SUBTITLE', 'Server Control Center')
    env_ssh_user = os.environ.get('SSH_USER', '')
    if not env_ssh_user or env_ssh_user == 'root':
        if os.path.isdir('/home/tin'):
            env_ssh_user = 'tin'
        elif os.path.isdir('/home/pineapple'):
            env_ssh_user = 'pineapple'
        elif os.environ.get('SUDO_USER'):
            env_ssh_user = os.environ.get('SUDO_USER')
        else:
            try:
                import getpass
                env_ssh_user = getpass.getuser()
            except Exception:
                env_ssh_user = 'user'

    server_name = env_server_name
    project_name = env_project_name or 'Tinarchy'

    if os.path.exists(APP_CONFIG_FILE):
        try:
            with open(APP_CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
                if not server_name:
                    server_name = cfg.get('server_name')
                if not env_project_name:
                    project_name = cfg.get('project_name') or project_name
        except Exception:
            pass

    display_name = server_name or sys_name

    return {
        'server_name': server_name or '',
        'project_name': project_name,
        'display_name': display_name,
        'hostname': sys_name,
        'app_icon': env_app_icon,
        'branding_subtitle': env_subtitle,
        'ssh_user': env_ssh_user,
        'tailscale_domain': get_tailscale_domain()
    }

def save_app_config(cfg):
    with open(APP_CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)
