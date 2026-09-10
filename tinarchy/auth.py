import os
import json
import time
import socket
import http.client
import subprocess
from tinarchy.config import ROLES_CONFIG_FILE, get_system_hostname
from tinarchy.services import get_all_service_ids

WHOIS_CACHE = {}
_HOST_OWNER_CACHE = {'data': None, 'ts': 0}

class UnixSocketHTTPConnection(http.client.HTTPConnection):
    """Low-overhead HTTP client over Tailscaled's local UNIX domain socket."""
    def __init__(self, socket_path="/run/tailscale/tailscaled.sock", timeout=1.5):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)

def query_tailscaled_localapi(endpoint_path: str, timeout: float = 1.5):
    """Direct query to Tailscaled local API via UNIX domain socket (< 2ms)."""
    sock_path = "/run/tailscale/tailscaled.sock"
    if not os.path.exists(sock_path):
        return None
    conn = None
    try:
        conn = UnixSocketHTTPConnection(sock_path, timeout=timeout)
        conn.request("GET", endpoint_path, headers={"Host": "local-tailscaled.sock"})
        resp = conn.getresponse()
        if resp.status == 200:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return None

def get_tailscale_host_owner():
    global _HOST_OWNER_CACHE
    now = time.time()
    if _HOST_OWNER_CACHE['data'] and (now - _HOST_OWNER_CACHE['ts']) < 60:
        return _HOST_OWNER_CACHE['data']

    try:
        st = query_tailscaled_localapi("/localapi/v0/status")
        if not st:
            res = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout:
                st = json.loads(res.stdout)
        if st:
            self_user_id = st.get('Self', {}).get('UserID')
            if self_user_id:
                user_info = st.get('User', {}).get(str(self_user_id), {})
                login_name = user_info.get('LoginName', '')
                display_name = user_info.get('DisplayName') or login_name or 'Owner'
                avatar = user_info.get('ProfilePicURL', '')
                data = {
                    'user_id': self_user_id,
                    'login_name': login_name,
                    'display_name': display_name,
                    'avatar': avatar
                }
                _HOST_OWNER_CACHE = {'data': data, 'ts': now}
                return data
    except Exception as e:
        print(f"Error resolving Tailscale host owner: {e}")
    fallback = {
        'user_id': None,
        'login_name': os.environ.get('OWNER_EMAIL', ''),
        'display_name': 'Owner',
        'avatar': ''
    }
    return fallback

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
    if role in ['owner', 'admin']:
        return get_all_service_ids()

    cfg = get_roles_config()
    user_perms = cfg.get('user_permissions', {})
    if login_name and login_name in user_perms:
        return user_perms[login_name]

    return cfg.get('default_permissions', get_all_service_ids())

def get_user_role(login_name, display_name="", user_id=None):
    host_owner = get_tailscale_host_owner()
    if user_id and host_owner.get('user_id') and str(user_id) == str(host_owner.get('user_id')):
        return 'owner'
    if login_name and host_owner.get('login_name') and login_name.strip().lower() == host_owner.get('login_name').strip().lower():
        return 'owner'

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
    if ip in ['127.0.0.1', '::1', os.environ.get('TAILSCALE_IP', '127.0.0.1')]:
        return {
            'user_id': host_owner.get('user_id'),
            'login_name': host_owner.get('login_name'),
            'display_name': host_owner.get('display_name'),
            'avatar': host_owner.get('avatar', ''),
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
        raw = query_tailscaled_localapi(f"/localapi/v0/whois?addr={ip}")
        if not raw:
            res = subprocess.run(['tailscale', 'whois', '--json', ip], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout:
                raw = json.loads(res.stdout)
        if raw:
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
    try:
        data = query_tailscaled_localapi("/localapi/v0/status")
        if not data:
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

        node_details = {}
        for node in all_nodes:
            node_id = str(node.get('ID'))
            uid = node.get('UserID')
            ips = node.get('TailscaleIPs', [])
            primary_ip = ips[0] if ips else ''

            if primary_ip and (not uid or str(uid) not in users_map):
                try:
                    wdata = query_tailscaled_localapi(f"/localapi/v0/whois?addr={primary_ip}")
                    if not wdata:
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
                    pass

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

                    is_shared = bool(node.get('ShareeNode') or wnode.get('Hostinfo', {}).get('ShareeNode'))
                    raw_hname = node.get('HostName') or wnode.get('Name') or wnode.get('ComputedName') or ''

                    if not raw_hname or raw_hname == 'device-of-shared-to-user':
                        h_name = "Shared Node" if is_shared else "Device"
                    else:
                        h_name = raw_hname

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

def update_user_role(target_user: str, new_role: str):
    if new_role not in ['admin', 'viewer']:
        raise ValueError("Invalid role. Permitted: admin, viewer")

    host_owner = get_tailscale_host_owner()
    if target_user.lower() == str(host_owner.get('login_name', '')).lower():
        raise ValueError("Cannot modify the host Owner role")

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

def update_user_permissions(target_user: str, allowed_services: list):
    host_owner = get_tailscale_host_owner()
    if target_user.lower() == str(host_owner.get('login_name', '')).lower():
        raise ValueError("Cannot modify site permissions for the host Owner")

    valid_ids = get_all_service_ids()
    sanitized = [s for s in allowed_services if s in valid_ids]

    cfg = get_roles_config()
    if 'user_permissions' not in cfg:
        cfg['user_permissions'] = {}

    cfg['user_permissions'][target_user] = sanitized
    save_roles_config(cfg)
    WHOIS_CACHE.clear()
    return sanitized
