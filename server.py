import socket
import platform
import gzip
import pywal_generator
import http.server
import socketserver
import json
import os
import glob
import subprocess
import re
import uuid
import time
import http.cookies
import ssl
import threading
import html

# --- Load Environment Variables ---
def load_env():
    env_paths = [
        os.environ.get('TINARCHY_ENV_FILE', ''),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'),
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


PREV_NET = {'time': time.time(), 'rx': 0, 'tx': 0, 'rx_spd': 0, 'tx_spd': 0, 'rx_tot': 0, 'tx_tot': 0}
_NET_LOCK = threading.Lock()

_CPU_LOCK = threading.Lock()
_LAST_CPU_PERCENT = 0.0
_TAILSCALE_IP_CACHE = {'ip': None, 'ts': 0}
_SERVICES_STATUS_CACHE = {'data': None, 'ts': 0}

def _read_cpu_times():
    try:
        with open('/proc/stat', 'r') as f:
            line = f.readline()
        fields = [float(x) for x in line.strip().split()[1:]]
        # Linux standard: [0] user, [1] nice, [2] system, [3] idle, [4] iowait, [5] irq, [6] softirq, [7] steal
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0.0)
        non_idle = fields[0] + fields[1] + fields[2] + (sum(fields[5:8]) if len(fields) >= 8 else 0.0)
        total = idle + non_idle
        return time.time(), total, idle
    except Exception:
        return time.time(), 0.0, 0.0

_t_init, _tot_init, _idle_init = _read_cpu_times()
PREV_CPU = {'time': _t_init, 'total': _tot_init, 'idle': _idle_init}

def get_cpu_percent():
    global PREV_CPU, _LAST_CPU_PERCENT
    with _CPU_LOCK:
        now_t, total, idle = _read_cpu_times()
        if total == 0.0:
            return _LAST_CPU_PERCENT

        dt = now_t - PREV_CPU['time']
        diff_total = total - PREV_CPU['total']
        diff_idle = idle - PREV_CPU['idle']

        # Prevent false 0% spikes from rapid concurrent requests (< 0.5s)
        if dt < 0.5 or diff_total <= 0:
            return _LAST_CPU_PERCENT

        usage = max(0.0, min(100.0, (1.0 - (diff_idle / diff_total)) * 100.0))
        _LAST_CPU_PERCENT = round(usage, 1)
        PREV_CPU = {'time': now_t, 'total': total, 'idle': idle}
        return _LAST_CPU_PERCENT

def get_ram_stats():
    """Hardware-adaptive RAM usage calculation.
    Uses MemAvailable on modern Linux kernels (3.14+) with legacy fallbacks
    for older machines and kernels.
    """
    try:
        meminfo = {}
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.split(':')
                if len(parts) == 2:
                    meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])

        total_kb = meminfo.get('MemTotal', 0)
        if total_kb <= 0:
            return {'ram_used_mb': 0, 'ram_total_mb': 0, 'ram_percent': 0.0}

        # Modern Linux: MemAvailable is the kernel's official freeable memory estimate
        if 'MemAvailable' in meminfo:
            avail_kb = meminfo['MemAvailable']
            used_kb = max(0, total_kb - avail_kb)
        else:
            # Fallback for older kernels: total - free - buffers - cached
            free_kb = meminfo.get('MemFree', 0)
            buffers_kb = meminfo.get('Buffers', 0)
            cached_kb = meminfo.get('Cached', 0)
            sreclaim_kb = meminfo.get('SReclaimable', 0)
            shmem_kb = meminfo.get('Shmem', 0)
            used_kb = max(0, total_kb - free_kb - buffers_kb - cached_kb - sreclaim_kb + shmem_kb)

        used_mb = int(used_kb / 1024)
        total_mb = int(total_kb / 1024)
        percent = round((used_kb / total_kb) * 100.0, 1)

        return {
            'ram_used_mb': used_mb,
            'ram_total_mb': total_mb,
            'ram_percent': percent
        }
    except Exception:
        return {'ram_used_mb': 0, 'ram_total_mb': 0, 'ram_percent': 0.0}

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

_CPU_TEMP_PATH = None

def find_best_cpu_temp_path():
    # 1. Check hwmon for dedicated CPU temperature drivers (coretemp, k10temp, zenpower, etc.)
    cpu_hwmon_names = {'coretemp', 'k10temp', 'zenpower', 'cpu_thermal', 'soc_thermal'}
    for hwmon in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
        try:
            with open(os.path.join(hwmon, 'name'), 'r') as f:
                h_name = f.read().strip().lower()
            if h_name in cpu_hwmon_names:
                # Prefer 'Package id 0' or 'Tdie' or 'Tctl' or 'Core 0'
                for label_file in sorted(glob.glob(os.path.join(hwmon, 'temp*_label'))):
                    try:
                        with open(label_file, 'r') as lf:
                            lbl = lf.read().strip().lower()
                        if any(k in lbl for k in ('package', 'tdie', 'tctl', 'core 0')):
                            inp_file = label_file.replace('_label', '_input')
                            if os.path.isfile(inp_file):
                                return inp_file
                    except Exception:
                        pass
                t1 = os.path.join(hwmon, 'temp1_input')
                if os.path.isfile(t1):
                    return t1
        except Exception:
            pass

    # 2. Check thermal zones for designated CPU types (x86_pkg_temp, cpu-thermal, etc.)
    cpu_zone_keywords = ('x86_pkg_temp', 'cpu', 'pkg', 'k10temp', 'coretemp', 'soc')
    for zone in sorted(glob.glob('/sys/class/thermal/thermal_zone*')):
        try:
            with open(os.path.join(zone, 'type'), 'r') as f:
                z_type = f.read().strip().lower()
            if any(k in z_type for k in cpu_zone_keywords):
                t_file = os.path.join(zone, 'temp')
                if os.path.isfile(t_file):
                    return t_file
        except Exception:
            pass

    # 3. Check vendor-specific platform monitors (e.g. dell_smm, thinkpad)
    for hwmon in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
        try:
            with open(os.path.join(hwmon, 'name'), 'r') as f:
                h_name = f.read().strip().lower()
            if any(k in h_name for k in ('dell', 'thinkpad', 'asus')):
                t1 = os.path.join(hwmon, 'temp1_input')
                if os.path.isfile(t1):
                    return t1
        except Exception:
            pass

    # 4. Fallback to classic/legacy paths (ensures 100% compatibility with older laptops/kernels)
    legacy_paths = [
        '/sys/class/thermal/thermal_zone0/temp',
        '/sys/class/hwmon/hwmon0/temp1_input',
        '/sys/class/hwmon/hwmon1/temp1_input'
    ]
    for p in legacy_paths:
        if os.path.isfile(p):
            return p

    return None

def get_cpu_temp():
    global _CPU_TEMP_PATH
    if not _CPU_TEMP_PATH or not os.path.isfile(_CPU_TEMP_PATH):
        _CPU_TEMP_PATH = find_best_cpu_temp_path()

    if _CPU_TEMP_PATH:
        try:
            with open(_CPU_TEMP_PATH, 'r') as f:
                val = int(f.read().strip())
                celsius = round(val / 1000.0, 1) if val > 1000 else float(val)
                return f"{celsius}°C", int(celsius)
        except Exception:
            _CPU_TEMP_PATH = None

    return "N/A", 0

APP_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app_config.json')

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

# ─── Dynamic Tailscale Host Owner & RBAC ───
ROLES_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'roles_config.json')
WHOIS_CACHE = {}
_HOST_OWNER_CACHE = {'data': None, 'ts': 0}

def get_tailscale_host_owner():
    """
    Dynamically discovers the Tailscale account that owns/registered this server node.
    Always uses the live DisplayName from Tailscale without hardcoded names.
    Cached for 60 seconds to avoid high-frequency subprocess overhead.
    """
    global _HOST_OWNER_CACHE
    now = time.time()
    if _HOST_OWNER_CACHE['data'] and (now - _HOST_OWNER_CACHE['ts']) < 60:
        return _HOST_OWNER_CACHE['data']

    try:
        res = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout:
            st = json.loads(res.stdout)
            self_user_id = st.get('Self', {}).get('UserID')
            if self_user_id:
                user_info = st.get('User', {}).get(str(self_user_id), {})
                login_name = user_info.get('LoginName', '')
                display_name = user_info.get('DisplayName') or login_name or 'Owner'
                data = {
                    'user_id': self_user_id,
                    'login_name': login_name,
                    'display_name': display_name
                }
                _HOST_OWNER_CACHE = {'data': data, 'ts': now}
                return data
    except Exception as e:
        print(f"Error resolving Tailscale host owner: {e}")
    fallback = {
        'user_id': None,
        'login_name': os.environ.get('OWNER_EMAIL', ''),
        'display_name': 'Owner'
    }
    return fallback

def get_all_service_ids():
    global SERVICES
    try:
        return [s['id'] for s in SERVICES]
    except Exception:
        return ['suwayomi', 'jellyfin', 'tor', 'filebrowser', 'couchdb', 'tailscale-ssh']

def get_roles_config():
    default_cfg = {
        "admin_accounts": [],
        "roles": {},
        "default_role": "viewer",
        "user_permissions": {},
        "default_permissions": get_all_service_ids()
    }
    if os.path.exists(ROLES_CONFIG_FILE):
        try:
            with open(ROLES_CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
                if 'admin_accounts' not in cfg:
                    cfg['admin_accounts'] = []
                if 'roles' not in cfg:
                    cfg['roles'] = {}
                if 'user_permissions' not in cfg:
                    cfg['user_permissions'] = {}
                if 'default_permissions' not in cfg:
                    cfg['default_permissions'] = get_all_service_ids()
                return cfg
        except Exception:
            pass
    return default_cfg

def save_roles_config(cfg):
    try:
        with open(ROLES_CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving roles config: {e}")

def get_user_allowed_services(login_name, role=None):
    if role is None:
        role = get_user_role(login_name)
    # 👑 Owner and 🛡️ Admin ALWAYS have unrestricted access to ALL sites and services!
    if role in ['owner', 'admin']:
        return get_all_service_ids()
    
    cfg = get_roles_config()
    user_perms = cfg.get('user_permissions', {})
    if login_name and login_name in user_perms:
        return user_perms[login_name]
    
    return cfg.get('default_permissions', get_all_service_ids())

def get_user_role(login_name, display_name="", user_id=None):
    host_owner = get_tailscale_host_owner()
    # 1. The Tailscale account hosting the server is ALWAYS dynamically the Owner!
    # Strict matching by unique user_id or unique login_name email (never match on non-unique display name):
    if user_id and host_owner.get('user_id') and str(user_id) == str(host_owner.get('user_id')):
        return 'owner'
    if login_name and host_owner.get('login_name') and login_name.strip().lower() == host_owner.get('login_name').strip().lower():
        return 'owner'

    # 2. Check if the Owner granted Admin permissions
    cfg = get_roles_config()
    roles = cfg.get('roles', {})
    if login_name in roles:
        return roles[login_name]
    
    admins = cfg.get('admin_accounts', [])
    if login_name in admins:
        return 'admin'

    return 'viewer'

def resolve_tailscale_client(ip):
    host_owner = get_tailscale_host_owner()
    # Localhost / loopback / server self
    if ip in ['127.0.0.1', '::1', os.environ.get('TAILSCALE_IP', '127.0.0.1')]:
        return {
            'user_id': host_owner.get('user_id'),
            'login_name': host_owner.get('login_name'),
            'display_name': host_owner.get('display_name'),
            'avatar': 'https://lh3.googleusercontent.com/a/ACg8ocL92RrWfI8Ahb8E_7Rk3UvYWjsMvXusLJQqYicGtM1nm3Yrv5Dm=s96-c',
            'device_name': get_system_hostname(),
            'device_ip': ip,
            'role': 'owner',
            'is_owner': True,
            'is_tailscale': True,
            'allowed_services': get_all_service_ids()
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
            user_id = u.get('ID')
            login_name = u.get('LoginName', '')
            display_name = u.get('DisplayName', login_name)
            avatar = u.get('ProfilePicURL', '')
            device = node.get('ComputedName', '')

            role = get_user_role(login_name, display_name, user_id=user_id)
            user_info = {
                'user_id': user_id,
                'login_name': login_name,
                'display_name': display_name,
                'avatar': avatar,
                'device_name': device,
                'device_ip': ip,
                'role': role,
                'is_owner': (role == 'owner'),
                'is_tailscale': True,
                'allowed_services': get_user_allowed_services(login_name, role)
            }
            WHOIS_CACHE[ip] = {'data': user_info, 'ts': now}
            return user_info
    except Exception as e:
        print(f"Tailscale whois error: {e}")

    # Fallback for LAN Wi-Fi / Local Subnet (e.g. 10.14.143.x)
    is_lan = ip.startswith(('10.', '192.168.', '172.'))
    lan_role = 'owner' if is_lan else 'viewer'
    fallback = {
        'login_name': 'lan_client',
        'display_name': f'Local LAN ({ip})',
        'avatar': '',
        'device_name': ip,
        'device_ip': ip,
        'role': lan_role,
        'is_owner': is_lan,
        'is_tailscale': False,
        'allowed_services': get_all_service_ids() if is_lan else get_user_allowed_services('lan_client', 'viewer')
    }
    return fallback

def get_tailscale_users():
    """
    Dynamically aggregates all Tailscale users and devices (including all shared peers/nodes)
    using generic loops and whois inspection without any hardcoded names.
    """
    try:
        res = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=2)
        if res.returncode != 0 or not res.stdout:
            return []
        data = json.loads(res.stdout)
        users_map = data.get('User', {})
        peers = data.get('Peer', {})
        self_node = data.get('Self', {})
        
        all_nodes = list(peers.values())
        if self_node:
            all_nodes.append(self_node)
            
        # 1. Loop through all nodes to dynamically discover any shared/external users via whois
        node_details = {}
        for node in all_nodes:
            node_id = str(node.get('ID'))
            uid = node.get('UserID')
            ips = node.get('TailscaleIPs', [])
            primary_ip = ips[0] if ips else ''
            
            # If this node belongs to an unknown/shared user, discover via whois
            if primary_ip and (not uid or str(uid) not in users_map):
                try:
                    wout = subprocess.check_output(['tailscale', 'whois', '--json', primary_ip], timeout=2)
                    wdata = json.loads(wout)
                    uprof = wdata.get('UserProfile', {})
                    wnode = wdata.get('Node', {})
                    if uprof and uprof.get('ID'):
                        user_uid = str(uprof.get('ID'))
                        users_map[user_uid] = uprof
                        node['UserID'] = uprof.get('ID')
                    if wnode:
                        node_details[node_id] = wnode
                except Exception as e:
                    print(f"Whois discovery error for {primary_ip}: {e}")

        # 2. Group nodes by UserID using a generic loop
        ts_users = []
        for uid_str, uinfo in users_map.items():
            try:
                uid = int(uid_str)
            except Exception:
                uid = uid_str
                
            user_devices = []
            for node in all_nodes:
                if node.get('UserID') == uid:
                    node_id = str(node.get('ID'))
                    ips = node.get('TailscaleIPs', [])
                    wnode = node_details.get(node_id, {})
                    
                    # Dynamically resolve hostname
                    is_shared = bool(node.get('ShareeNode') or wnode.get('Hostinfo', {}).get('ShareeNode'))
                    raw_hname = node.get('HostName') or wnode.get('Name') or wnode.get('ComputedName') or ''
                    
                    if not raw_hname or raw_hname == 'device-of-shared-to-user':
                        if is_shared:
                            h_name = "Shared Node"
                        else:
                            h_name = "Device"
                    else:
                        h_name = raw_hname
                    
                    # Dynamically resolve OS (avoid assuming Windows for shared peers)
                    os_name = (node.get('OS') or wnode.get('Hostinfo', {}).get('OS') or '').lower()
                    if not os_name:
                        os_name = 'unknown'

                    user_devices.append({
                        'name': h_name,
                        'dns_name': (node.get('DNSName', '')).rstrip('.'),
                        'os': os_name,
                        'ip': ips[0] if ips else '',
                        'online': node.get('Online', False),
                        'active': node.get('Active', False),
                        'is_self': bool(self_node and node.get('ID') == self_node.get('ID')),
                        'is_shared': bool(node.get('ShareeNode') or wnode.get('Hostinfo', {}).get('ShareeNode'))
                    })
            
            l_name = uinfo.get('LoginName', '')
            d_name = uinfo.get('DisplayName') or l_name or 'User'
            role = get_user_role(l_name, d_name, user_id=uid)
            
            ts_users.append({
                'id': uid,
                'display_name': d_name,
                'login_name': l_name,
                'avatar': uinfo.get('ProfilePicURL', ''),
                'role': role,
                'is_owner': (role == 'owner'),
                'allowed_services': get_user_allowed_services(l_name, role),
                'devices': user_devices
            })
            
        role_priority = {'owner': 0, 'admin': 1, 'viewer': 2}
        ts_users.sort(key=lambda u: (
            role_priority.get(u.get('role', 'viewer'), 99),
            (u.get('display_name') or u.get('login_name') or '').lower()
        ))
        return ts_users
    except Exception as e:
        print(f"Tailscale status error: {e}")
        return []

def is_tailscale_ssh_active():
    try:
        res = subprocess.run(['tailscale', 'debug', 'prefs'], capture_output=True, text=True, timeout=1)
        if res.returncode == 0:
            return '"RunSSH": true' in res.stdout
    except Exception:
        pass
    return False

PORT = int(os.environ.get('PORT', 8085))
PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')
WALLPAPER_DIR = os.path.join(os.path.expanduser('~'), 'Wall') if os.path.isdir(os.path.join(os.path.expanduser('~'), 'Wall')) else os.path.join(PUBLIC_DIR, 'Wallpapers')

PRIMARY_USER = os.environ.get('SSH_USER') or ('tin' if os.path.isdir('/home/tin') else ('pineapple' if os.path.isdir('/home/pineapple') else (os.environ.get('SUDO_USER') or os.environ.get('USER', 'tin'))))

SERVICES = [
    {'id': 'suwayomi', 'name': 'Suwayomi Server', 'port': int(os.environ.get('SUWAYOMI_PORT', 4567)), 'systemd': 'suwayomi-server', 'icon': '📚', 'description': 'Manga library and reader'},
    {'id': 'jellyfin', 'name': 'Jellyfin Media Server', 'port': int(os.environ.get('JELLYFIN_PORT', 8096)), 'systemd': 'jellyfin', 'icon': '🍿', 'description': 'Movies, TV shows & media streaming'},
    {'id': 'tor', 'name': 'Tor Proxy', 'port': int(os.environ.get('TOR_SOCKS_PORT', 9050)), 'systemd': 'tor', 'icon': '🧅', 'description': 'SOCKS5 anonymity proxy'},
    {'id': 'filebrowser', 'name': 'File Manager', 'port': int(os.environ.get('FILEBROWSER_PORT', 8081)), 'systemd': 'filebrowser-quantum', 'icon': '📂', 'description': 'Modern web-based file manager'},
    {'id': 'couchdb', 'name': 'Obsidian LiveSync', 'port': int(os.environ.get('COUCHDB_PORT', 5984)), 'systemd': 'couchdb', 'icon': '🔮', 'description': 'Real-time E2EE sync backend for Obsidian vaults'},
    {'id': 'tailscale-ssh', 'name': 'Tailscale SSH', 'port': int(os.environ.get('SSH_PORT', 22)), 'systemd': 'tailscaled', 'systemd_name': 'tailscale ssh', 'icon': '🔑', 'description': 'Keyless mesh shell access via Tailscale', 'link': '/ssh', 'link_text': '/ssh'},
    {'id': 'syncthing', 'name': 'Syncthing', 'port': int(os.environ.get('SYNCTHING_PORT', 8384)), 'systemd': f"syncthing@{PRIMARY_USER}", 'icon': '🔄', 'description': 'Continuous, encrypted folder sync for personal devices', 'link': '/syncthing', 'link_text': '/syncthing'},
    {'id': 'syncyomi', 'name': 'SyncYomi', 'port': int(os.environ.get('SYNCYOMI_PORT', 8282)), 'systemd': 'syncyomi', 'icon': '📖', 'description': 'Tachiyomi, Mihon & Suwayomi manga reading progress sync', 'link': '/syncyomi', 'link_text': ':8282'},
]

# Load optional machine-specific services (untracked in git, e.g. Navidrome)
LOCAL_SERVICES_FILE = os.path.join(os.path.dirname(__file__), 'services.local.json')
if os.path.exists(LOCAL_SERVICES_FILE):
    try:
        with open(LOCAL_SERVICES_FILE, 'r') as f:
            local_svcs = json.load(f)
            if isinstance(local_svcs, list):
                SERVICES.extend(local_svcs)
    except Exception as e:
        print(f'Error loading local services: {e}')

def trigger_drive_sync():
    sync_bin = os.environ.get('DRIVE_SYNC_BIN')
    if not sync_bin:
        for candidate in [
            '/usr/local/bin/tinarchy-drive-sync',
            '/usr/local/bin/pinedash-drive-sync',
            '/usr/bin/tinarchy-drive-sync',
            '/usr/bin/pinedash-drive-sync',
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'configs/scripts/pinedash-drive-sync')
        ]:
            if os.path.exists(candidate):
                sync_bin = candidate
                break
    if sync_bin:
        subprocess.Popen([sync_bin])
    else:
        raise FileNotFoundError("Drive sync binary not found")

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
        # Extract path without query or fragment, strip trailing slashes
        raw_path = self.path.split('?')[0].split('#')[0]
        clean_path = raw_path.rstrip('/').lower() if raw_path != '/' else '/'
        if not clean_path or clean_path == '/':
            return False

        # Support backward-compatible /links/ prefix (e.g. /links/files -> /files)
        if clean_path.startswith('/links'):
            sub = clean_path[6:].strip('/')
            if not sub:
                self.send_response(302)
                self.send_header('Location', '/')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                return True
            clean_path = '/' + sub

        # Canonical URL redirects to hide .html from URL bar
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

        # Clean /settings route: directly serve settings.html without URL change
        if clean_path == '/settings':
            return self.serve_html_file('settings.html')

        session = self.check_auth()
        role = session.get('role', 'viewer')
        login_name = session.get('login_name', '')
        allowed_services = get_user_allowed_services(login_name, role)

        # 1. Dedicated Static Guide Pages for non-HTTP / setup services
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

        if clean_path in ['/obsidian', '/livesync', '/notes', '/guides/obsidian', '/guides/obsidian.html']:
            if 'couchdb' not in allowed_services:
                return self.serve_access_denied('Obsidian LiveSync')
            return self.serve_guide_page('obsidian.html')

        if clean_path in ['/syncthing', '/sync', '/guides/syncthing', '/guides/syncthing.html']:
            if 'syncthing' not in allowed_services:
                return self.serve_access_denied('Syncthing')
            return self.serve_guide_page('syncthing.html')

        if clean_path in ['/syncyomi', '/manga-sync', '/guides/syncyomi', '/guides/syncyomi.html']:
            if 'syncyomi' not in allowed_services:
                return self.serve_access_denied('SyncYomi')
            return self.serve_guide_page('syncyomi.html')

        # 2. Top-Level Web Application Redirects
        raw_host = self.headers.get('Host', '')
        host = raw_host.split(':')[0] if raw_host else get_system_hostname()

        target_url = None
        if clean_path in ['/files', '/file', '/drive', '/quantum', '/filebrowser']:
            if 'filebrowser' not in allowed_services:
                return self.serve_access_denied('File Manager')
            target_url = f"https://{host}:8081/"
        elif clean_path in ['/manga', '/reader', '/tachiyomi', '/suwayomi']:
            if 'suwayomi' not in allowed_services:
                return self.serve_access_denied('Suwayomi Server')
            target_url = f"https://{host}:4567/"
        elif clean_path in ['/jellyfin', '/media', '/movies', '/stream']:
            if 'jellyfin' not in allowed_services:
                return self.serve_access_denied('Jellyfin Media Server')
            target_url = f"https://{host}:8096/"
        elif clean_path in ['/navidrome', '/music', '/audio']:
            if 'navidrome' not in allowed_services:
                return self.serve_access_denied('Navidrome Music')
            svc = next((s for s in SERVICES if 'navidrome' in s.get('id', '')), None)
            port = svc.get('port', 4533) if svc else 4533
            scheme = svc.get('scheme') or svc.get('protocol') or 'http' if svc else 'http'
            target_url = f"{scheme}://{host}:{port}/"
        elif clean_path == '/couchdb':
            if 'couchdb' not in allowed_services:
                return self.serve_access_denied('Obsidian LiveSync')
            target_url = "/couchdb/_utils/"

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

    def do_GET(self):
        # Allow static assets and public endpoints
        if self.path.startswith('/Wallpapers/') or self.path.startswith('/thumbnails/') or self.path.endswith(('.css', '.js', '.png', '.jpg', '.ico', '.woff', '.woff2', '.mp4', '.crt', '.svg', '.webp')):
            super().do_GET()
            return

        if self.handle_service_routes():
            return
            
        session = self.check_auth()

        if self.path == '/api/services':
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
                suwayomi_conf = '/var/lib/suwayomi/.local/share/Tachidesk/server.conf'
                try:
                    if os.path.isfile(suwayomi_conf):
                        with open(suwayomi_conf, 'r') as sf:
                            tor_proxy_enabled = ('server.socksProxyEnabled = true' in sf.read())
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
                        elif s['id'] == 'suwayomi':
                            service_link = '/manga'
                        elif s['id'] == 'couchdb':
                            service_link = '/obsidian'
                        elif s['id'] == 'tor':
                            service_link = '/tor'
                        elif 'navidrome' in s['id']:
                            service_link = '/navidrome'
                    status_obj['link'] = service_link
                    base_results.append(status_obj)

                _SERVICES_STATUS_CACHE = {'data': base_results, 'ts': now}

            role = session.get('role', 'viewer')
            login_name = session.get('login_name', '')
            allowed_services = get_user_allowed_services(login_name, role)
            filtered_results = [s for s in _SERVICES_STATUS_CACHE['data'] if s['id'] in allowed_services]

            self.send_compressed(json.dumps(filtered_results).encode(), "application/json")
            
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
                "allowed_services": get_user_allowed_services(login_name, role)
            }).encode(), "application/json")

        elif self.path == '/api/users':
            role = session.get('role', 'viewer')
            ts_users = [] if role == 'guest' else get_tailscale_users()
            self.send_compressed(json.dumps({
                "current_user": session,
                "tailscale_users": ts_users,
                "roles_config": get_roles_config(),
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
                trigger_drive_sync()
                self.send_compressed(b'{"success": true, "message": "Drive sync triggered"}', 'application/json')
            except Exception as e:
                self.send_compressed(json.dumps({"success": False, "error": str(e)}).encode(), 'application/json', code=500)

        elif self.path == '/api/system':
            stats = {}
            stats.update(get_ram_stats())

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
            
            global _TAILSCALE_IP_CACHE
            now_t = time.time()
            if _TAILSCALE_IP_CACHE['ip'] and (now_t - _TAILSCALE_IP_CACHE['ts']) < 60:
                stats['tailscale_ip'] = _TAILSCALE_IP_CACHE['ip']
            else:
                try:
                    res = subprocess.run(['tailscale', 'ip', '-4'], capture_output=True, text=True, timeout=2)
                    ip = res.stdout.strip() if res.returncode == 0 else "Offline"
                    _TAILSCALE_IP_CACHE = {'ip': ip, 'ts': now_t}
                    stats['tailscale_ip'] = ip
                except Exception:
                    stats['tailscale_ip'] = _TAILSCALE_IP_CACHE.get('ip') or "Offline"

            now_t = time.time()
            try:
                with _NET_LOCK:
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
                    dt = now_t - PREV_NET['time']
                    if dt >= 0.5:
                        rx_spd = max(0, (rx_tot - PREV_NET['rx']) / dt) if PREV_NET['rx'] > 0 and rx_tot >= PREV_NET['rx'] else 0
                        tx_spd = max(0, (tx_tot - PREV_NET['tx']) / dt) if PREV_NET['tx'] > 0 and tx_tot >= PREV_NET['tx'] else 0
                        PREV_NET = {'time': now_t, 'rx': rx_tot, 'tx': tx_tot, 'rx_spd': rx_spd, 'tx_spd': tx_spd, 'rx_tot': rx_tot, 'tx_tot': tx_tot}
                    else:
                        rx_spd = PREV_NET.get('rx_spd', 0)
                        tx_spd = PREV_NET.get('tx_spd', 0)

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

            sys_name = get_system_hostname()
            app_cfg = get_app_config()
            stats['display_name'] = app_cfg.get('display_name') or sys_name
            stats['server_name'] = stats['display_name']
            stats['project_name'] = app_cfg.get('project_name', sys_name)
            stats['app_icon'] = app_cfg.get('app_icon', '🍍')
            stats['branding_subtitle'] = app_cfg.get('branding_subtitle', 'Server Control Center')
            stats['ssh_user'] = app_cfg.get('ssh_user', '')
            stats['tailscale_domain'] = app_cfg.get('tailscale_domain', '')
            stats['hostname'] = sys_name
            # Drive sync status
            sync_last_file = '/run/tinarchy-drive/sync-last' if os.path.exists('/run/tinarchy-drive/sync-last') else '/run/pinedash-drive/sync-last'
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
            role = session.get('role', 'viewer')
            if role == 'guest':
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Guest access restricted"}')
                return

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
                self.wfile.write(b'{"error": "Forbidden: Only the Owner can change user roles"}')
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
            if target_user.lower() == str(host_owner.get('login_name', '')).lower():
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

            if not target_user:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Missing user parameter"}')
                return

            if not isinstance(allowed_services, list):
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "allowed_services must be a list of service IDs"}')
                return

            host_owner = get_tailscale_host_owner()
            if target_user.lower() == str(host_owner.get('login_name', '')).lower():
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Cannot modify site permissions for the host Owner"}')
                return

            valid_ids = get_all_service_ids()
            sanitized = [s for s in allowed_services if s in valid_ids]

            cfg = get_roles_config()
            if 'user_permissions' not in cfg:
                cfg['user_permissions'] = {}

            cfg['user_permissions'][target_user] = sanitized
            save_roles_config(cfg)
            WHOIS_CACHE.clear()

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "user": target_user,
                "allowed_services": sanitized
            }).encode())
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
                trigger_drive_sync()
                self.send_compressed(b'{"success": true, "message": "Drive sync triggered"}', "application/json")
            except Exception as e:
                self.send_compressed(json.dumps({"success": False, "error": str(e)}).encode(), "application/json", code=500)
            return

        # ─── Service Toggle: ADMIN & OWNER ───
        elif self.path.startswith('/api/services/') and self.path.endswith('/toggle'):
            service_id = self.path.split('/')[3]
            role = session.get('role', 'viewer')
            
            allowed = False
            if role in ['owner', 'admin']:
                allowed = True
                
            if not allowed:
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
                if service_id == 'tailscale-ssh':
                    ssh_val = 'true' if action == 'start' else 'false'
                    subprocess.run(['tailscale', 'set', f'--ssh={ssh_val}', '--accept-risk=lose-ssh'], check=True, timeout=5)
                else:
                    subprocess.run(['sudo', 'systemctl', action, service['systemd']], check=True)
                global _SERVICES_STATUS_CACHE
                _SERVICES_STATUS_CACHE['ts'] = 0
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            except (subprocess.CalledProcessError, Exception) as e:
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
                    if enable:
                        # Auto-toggle ON the Tor proxy if not already on
                        chk_tor = subprocess.run(['systemctl', 'is-active', 'tor'], capture_output=True, text=True)
                        if chk_tor.stdout.strip() != 'active':
                            subprocess.run(['sudo', 'systemctl', 'start', 'tor'], check=True)

                    cmd = f"sudo {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tor_exit_node.sh')} {action}"
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
    bind_host = os.environ.get('HOST', '127.0.0.1')
    app_cfg = get_app_config()
    with ThreadingSimpleServer((bind_host, PORT), DashboardHandler) as httpd:
        print(f"Serving {app_cfg.get('project_name', 'Tinarchy')} backend ({app_cfg.get('display_name')}) on {bind_host}:{PORT}")
        httpd.serve_forever()
