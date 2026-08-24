import http.server
import socketserver
import json
import subprocess
import os
import re

import uuid
import time
import http.cookies

def load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    os.environ[k] = v

load_env()

SESSIONS = {}
USERS = {
    "tin": {"password": os.environ.get("ADMIN_PASSWORD", "changeme"), "role": "admin"},
    "ice.kimi": {"password": os.environ.get("GUEST_PASSWORD", "changeme"), "role": "guest"}
}

PORT = 8080
PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')

SERVICES = [
    {'id': 'suwayomi', 'name': 'Suwayomi Server', 'port': 4567, 'systemd': 'suwayomi-server', 'icon': '📚', 'description': 'Manga library and reader'},
    {'id': 'navidrome-tin', 'name': 'Navidrome (Tin)', 'port': 4534, 'systemd': 'navidrome-tin', 'icon': '🎵', 'description': 'Private music server'},
    {'id': 'navidrome', 'name': 'Navidrome (Kimi)', 'port': 4533, 'systemd': 'navidrome', 'icon': '🎵', 'description': 'Shared music server'},
    {'id': 'tor', 'name': 'Tor Proxy', 'port': 9050, 'systemd': 'tor', 'icon': '🧅', 'description': 'SOCKS5 anonymity proxy'},
    {'id': 'filebrowser', 'name': 'Network Storage', 'port': 8081, 'systemd': 'filebrowser', 'icon': '📂', 'description': 'Web-based file manager'},
    {'id': 'sshd', 'name': 'SSH Server', 'port': 22, 'systemd': 'sshd', 'icon': '🔑', 'description': 'Secure shell access'},
    {'id': 'terminal', 'name': 'Web Terminal', 'port': 7681, 'systemd': 'web-terminal', 'icon': '🖥️', 'description': 'In-browser command line access'},
]

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PUBLIC_DIR, **kwargs)


    def check_auth(self):
        cookie_header = self.headers.get('Cookie')
        if cookie_header:
            cookies = http.cookies.SimpleCookie(cookie_header)
            if 'session' in cookies:
                token = cookies['session'].value
                if token in SESSIONS and time.time() < SESSIONS[token]['expiry']:
                    return SESSIONS[token]
        return None


    def do_GET(self):
        if self.path == '/login.html':
            super().do_GET()
            return
            
        session = self.check_auth()
        if not session:
            if self.path.startswith('/api/'):
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error": "Unauthorized"}')
            else:
                self.send_response(302)
                self.send_header('Location', '/login.html')
                self.end_headers()
            return

        if self.path == '/api/services':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            results = []
            role = session['role']
            for s in SERVICES:
                if role == 'guest' and s['id'] not in ['filebrowser', 'navidrome']:
                    continue
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

            self.wfile.write(json.dumps(results).encode())
            
        elif self.path == '/api/me':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"role": session['role']}).encode())
            
        elif self.path == '/api/logout':
            cookie_header = self.headers.get('Cookie')
            if cookie_header:
                import http.cookies
                cookies = http.cookies.SimpleCookie(cookie_header)
                if 'session' in cookies:
                    token = cookies['session'].value
                    if token in SESSIONS:
                        del SESSIONS[token]
            self.send_response(200)
            self.send_header('Set-Cookie', 'session=; Max-Age=0; Path=/')
            self.end_headers()
            self.wfile.write(b'{"success": true}')
            
        elif self.path == '/api/system':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            stats = {}
            try:
                stats['hostname'] = subprocess.check_output('hostname', text=True).strip()
            except:
                stats['hostname'] = 'Unknown'
            
            try:
                with open('/proc/uptime', 'r') as f:
                    uptime_seconds = float(f.readline().split()[0])
                    days = int(uptime_seconds // 86400)
                    hours = int((uptime_seconds % 86400) // 3600)
                    mins = int((uptime_seconds % 3600) // 60)
                    if days > 0:
                        stats['uptime'] = f"{days}d {hours}h {mins}m"
                    else:
                        stats['uptime'] = f"{hours}h {mins}m"
            except:
                stats['uptime'] = 'Unknown'
                
            try:
                with open('/proc/meminfo', 'r') as f:
                    meminfo = f.read()
                    total = int(re.search(r'MemTotal:\s+(\d+)', meminfo).group(1))
                    available = int(re.search(r'MemAvailable:\s+(\d+)', meminfo).group(1))
                    used = total - available
                    stats['ram_used_mb'] = used // 1024
                    stats['ram_total_mb'] = total // 1024
                    stats['ram_percent'] = int((used / total) * 100)
            except:
                stats['ram_percent'] = 0
                stats['ram_used_mb'] = 0
                stats['ram_total_mb'] = 0
                
            try:
                df = subprocess.check_output(['df', '-h', '/'], text=True).split('\n')[1].split()
                stats['disk_total'] = df[1]
                stats['disk_used'] = df[2]
                stats['disk_percent'] = int(df[4].replace('%', ''))
            except:
                stats['disk_total'] = '0G'
                stats['disk_used'] = '0G'
                stats['disk_percent'] = 0
                
            try:
                with open('/proc/loadavg', 'r') as f:
                    stats['loadavg'] = f.read().split()[:3]
                nproc = subprocess.check_output(['nproc'], text=True).strip()
                stats['cores'] = int(nproc)
                stats['cpu_percent'] = min(100, int((float(stats['loadavg'][0]) / stats['cores']) * 100))
            except:
                stats['loadavg'] = ['0.00', '0.00', '0.00']
                stats['cores'] = 1
                stats['cpu_percent'] = 0
                
            try:
                ts_ip = subprocess.check_output(['tailscale', 'ip', '-4'], text=True, stderr=subprocess.DEVNULL).strip()
                stats['tailscale_ip'] = ts_ip if ts_ip else 'Not running'
            except:
                stats['tailscale_ip'] = 'Not running'
                
            self.wfile.write(json.dumps(stats).encode())
            
        elif self.path == '/api/system/tor-exit':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            try:
                res = subprocess.run(['sudo', 'iptables', '-t', 'nat', '-L', 'TOR_EXIT'], capture_output=True)
                active = (res.returncode == 0)
            except:
                active = False
            self.wfile.write(json.dumps({"active": active}).encode())

        else:
            super().do_GET()


    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
        try:
            data = json.loads(body)
        except:
            data = {}

        if self.path == '/api/login':
            username = data.get('username')
            password = data.get('password')
            if username in USERS and USERS[username]['password'] == password:
                token = str(uuid.uuid4())
                SESSIONS[token] = {"expiry": time.time() + 86400, "role": USERS[username]['role']}
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Set-Cookie', f'session={token}; Max-Age=86400; Path=/')
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            else:
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error": "Invalid credentials"}')
            return

        session = self.check_auth()
        if not session:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error": "Unauthorized"}')
            return



        if session['role'] != 'admin':
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'{"error": "Forbidden"}')
            return

        if self.path.startswith('/api/services/') and self.path.endswith('/toggle'):
            service_id = self.path.split('/')[3]
            service = next((s for s in SERVICES if s['id'] == service_id), None)
            
            if not service:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error": "Service not found"}')
                return

            action = data.get('action')
            if action not in ['start', 'stop']:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Invalid action"}')
                return

            try:
                subprocess.run(['sudo', 'systemctl', action, service['systemd']], check=True)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            except subprocess.CalledProcessError as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

        elif self.path == '/api/suwayomi/tor':
            enable = data.get('enable', False)
            search = 'server.socksProxyEnabled = false' if enable else 'server.socksProxyEnabled = true'
            replace = 'server.socksProxyEnabled = true' if enable else 'server.socksProxyEnabled = false'
            
            try:
                cmd = f"sudo sed -i 's/{search}/{replace}/' /var/lib/suwayomi/.local/share/Tachidesk/server.conf && sudo systemctl restart suwayomi-server"
                subprocess.run(cmd, shell=True, check=True)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            except subprocess.CalledProcessError as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

        elif self.path == '/api/system/tor-exit':
            enable = data.get('enable', False)
            action = 'start' if enable else 'stop'
            
            try:
                cmd = f"sudo /home/tin/server-dashboard/tor_exit_node.sh {action}"
                subprocess.run(cmd, shell=True, check=True)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            except subprocess.CalledProcessError as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

        else:
            self.send_response(404)
            self.end_headers()

class ThreadingSimpleServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

if __name__ == '__main__':
    ThreadingSimpleServer.allow_reuse_address = True
    with ThreadingSimpleServer(("0.0.0.0", PORT), DashboardHandler) as httpd:
        print(f"Serving at port {PORT}")
        httpd.serve_forever()
