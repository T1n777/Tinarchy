import os
import re
import json
import time
import threading
import subprocess
import xml.etree.ElementTree as ET
from tinarchy.config import PRIMARY_USER, BASE_DIR

_SYNCTHING_DEVICE_ID_CACHE = {'id': None, 'ts': 0}

def get_syncthing_home_dir():
    candidates = [
        f"/home/{PRIMARY_USER}/.local/state/syncthing",
        f"/home/{PRIMARY_USER}/.config/syncthing",
        os.path.expanduser('~/.local/state/syncthing'),
        os.path.expanduser('~/.config/syncthing'),
    ]
    for c in candidates:
        if os.path.exists(os.path.join(c, 'config.xml')):
            return c
    return None

def get_syncthing_cli_cmd():
    home_dir = get_syncthing_home_dir()
    if home_dir:
        return ['syncthing', '--home', home_dir, 'cli']
    return ['syncthing', 'cli']

def get_syncthing_device_id():
    global _SYNCTHING_DEVICE_ID_CACHE
    now = time.time()
    if _SYNCTHING_DEVICE_ID_CACHE['id'] and (now - _SYNCTHING_DEVICE_ID_CACHE['ts'] < 3600):
        return _SYNCTHING_DEVICE_ID_CACHE['id']
    home_dir = get_syncthing_home_dir()
    cmd = ['syncthing', '--home', home_dir, 'device-id'] if home_dir else ['syncthing', 'device-id']
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout.strip():
            dev_id = res.stdout.strip()
            _SYNCTHING_DEVICE_ID_CACHE = {'id': dev_id, 'ts': now}
            return dev_id
    except Exception:
        pass
    if home_dir:
        cp = os.path.join(home_dir, 'config.xml')
        if os.path.exists(cp):
            try:
                tree = ET.parse(cp)
                root = tree.getroot()
                for dev in root.findall('device'):
                    dev_id = dev.get('id')
                    if dev_id:
                        _SYNCTHING_DEVICE_ID_CACHE = {'id': dev_id, 'ts': now}
                        return dev_id
            except Exception:
                pass
    return ""

def trigger_drive_sync():
    sync_bin = os.environ.get('DRIVE_SYNC_BIN')
    if not sync_bin:
        for candidate in [
            '/usr/local/bin/tinarchy-drive-sync',
            '/usr/local/bin/pinedash-drive-sync',
            '/usr/bin/tinarchy-drive-sync',
            '/usr/bin/pinedash-drive-sync',
            os.path.join(BASE_DIR, 'configs', 'scripts', 'tinarchy-drive-sync'),
            os.path.join(BASE_DIR, 'configs', 'scripts', 'pinedash-drive-sync')
        ]:
            if os.path.exists(candidate):
                sync_bin = candidate
                break
    if sync_bin:
        subprocess.Popen([sync_bin])
    else:
        raise FileNotFoundError("Drive sync binary not found")

def start_syncthing_auto_pair_thread():
    def _worker():
        time.sleep(3)
        cli_cmd = get_syncthing_cli_cmd()
        auto_share_env = os.environ.get('SYNCTHING_AUTO_SHARE_FOLDERS', 'shared,shared-drive')
        auto_share_folders = [f.strip() for f in auto_share_env.split(',') if f.strip()]
        while True:
            try:
                # 1. Check pending devices
                res = subprocess.run(cli_cmd + ['show', 'pending', 'devices'], capture_output=True, text=True, timeout=5)
                if res.returncode == 0 and res.stdout:
                    pending = json.loads(res.stdout)
                    for dev_id, dev_info in pending.items():
                        name = dev_info.get('name') or 'Client Device'
                        subprocess.run(cli_cmd + ['config', 'devices', 'add', '--device-id', dev_id, '--name', name], capture_output=True)
                        subprocess.run(cli_cmd + ['config', 'devices', dev_id, 'compression', 'set', 'always'], capture_output=True)
                        for fid in auto_share_folders:
                            if subprocess.run(cli_cmd + ['config', 'folders', fid, 'dump-json'], capture_output=True).returncode == 0:
                                subprocess.run(cli_cmd + ['config', 'folders', fid, 'devices', 'add', '--device-id', dev_id], capture_output=True)

                # 2. Check pending folders
                res_f = subprocess.run(cli_cmd + ['show', 'pending', 'folders'], capture_output=True, text=True, timeout=5)
                if res_f.returncode == 0 and res_f.stdout:
                    pending_f = json.loads(res_f.stdout)
                    for folder_id, f_info in pending_f.items():
                        if folder_id in auto_share_folders:
                            dev_id = f_info.get('deviceID')
                            if dev_id:
                                subprocess.run(cli_cmd + ['config', 'folders', folder_id, 'devices', 'add', '--device-id', dev_id], capture_output=True)
            except Exception:
                pass
            time.sleep(5)

    t = threading.Thread(target=_worker, daemon=True, name="SyncthingAutoPair")
    t.start()
