"""
Tinarchy JDownloader 2 Integration Module.
Provides client connectivity, metrics polling with caching, and link submission
to the headless JDownloader 2 daemon via the MyJDownloader API.
"""

import os
import re
import json
import time
import logging
import threading
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Cache configuration
_CACHE_TTL = 3.0  # seconds
_status_cache: Dict[str, Any] = {
    "online": False,
    "dl_speed": 0,
    "state": "OFFLINE",
    "active_downloads": 0,
    "total_downloads": 0,
    "packages": [],
    "last_updated": 0
}
_lock = threading.Lock()

# Persistent client & device handle
_jd_client = None
_jd_device = None

CREDENTIALS_FILE = "/home/tin/.config/jdownloader/credentials.env"
JD_SETTINGS_FILE = "/home/tin/jdownloader/cfg/org.jdownloader.api.myjdownloader.MyJDownloaderSettings.json"


def _load_credentials():
    """Load credentials from environment variables, credentials.env, or JD settings."""
    email = os.environ.get("MYJDOWNLOADER_EMAIL")
    password = os.environ.get("MYJDOWNLOADER_PASSWORD")
    device_name = os.environ.get("MYJDOWNLOADER_DEVICE", "tinarchy")

    if email and password:
        return email, password, device_name

    # Try credentials.env
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k == "MYJDOWNLOADER_EMAIL":
                        email = v
                    elif k == "MYJDOWNLOADER_PASSWORD":
                        password = v
                    elif k == "MYJDOWNLOADER_DEVICE":
                        device_name = v
            if email and password:
                return email, password, device_name
        except Exception as e:
            logger.warning(f"Failed to read {CREDENTIALS_FILE}: {e}")

    # Fallback to JDownloader config json
    if os.path.exists(JD_SETTINGS_FILE):
        try:
            with open(JD_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                email = data.get("email")
                password = data.get("password")
                device_name = data.get("devicename", device_name)
                if email and password:
                    return email, password, device_name
        except Exception as e:
            logger.warning(f"Failed to read {JD_SETTINGS_FILE}: {e}")

    return None, None, device_name


def _get_device(force_reconnect: bool = False):
    """Obtain an authenticated, connected Jddevice instance."""
    global _jd_client, _jd_device

    import myjdapi

    email, password, target_device = _load_credentials()
    if not email or not password:
        raise ValueError("MyJDownloader credentials not configured.")

    if not force_reconnect and _jd_client is not None and _jd_device is not None:
        try:
            if _jd_client.is_connected():
                return _jd_device
        except Exception:
            pass

    # Create new client and connect
    client = myjdapi.Myjdapi()
    client.set_app_key("TinarchyDashboard")
    client.connect(email, password)
    client.update_devices()

    device = client.get_device(target_device)
    if not device:
        # Fallback to first available device if target_device name differs
        devices = client.list_devices()
        if devices:
            first_name = devices[0].get("name")
            device = client.get_device(first_name)

    if not device:
        raise ValueError(f"JDownloader device '{target_device}' not found in MyJDownloader account.")

    _jd_client = client
    _jd_device = device
    return _jd_device


def get_jdownloader_status(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Retrieve real-time JDownloader status with low latency caching.
    Returns:
        {
            "online": bool,
            "dl_speed": int,
            "state": str,
            "active_downloads": int,
            "total_downloads": int,
            "packages": list[dict]
        }
    """
    global _status_cache

    now = time.time()
    if not force_refresh and (now - _status_cache.get("last_updated", 0) < _CACHE_TTL):
        return {k: v for k, v in _status_cache.items() if k != "last_updated"}

    with _lock:
        now = time.time()
        if not force_refresh and (now - _status_cache.get("last_updated", 0) < _CACHE_TTL):
            return {k: v for k, v in _status_cache.items() if k != "last_updated"}

        try:
            dev = _get_device()
            try:
                speed = dev.downloadcontroller.get_speed_in_bytes() or 0
                state = dev.downloadcontroller.get_current_state() or "IDLE"
            except Exception:
                # Connection might be stale, retry once with force reconnect
                dev = _get_device(force_reconnect=True)
                speed = dev.downloadcontroller.get_speed_in_bytes() or 0
                state = dev.downloadcontroller.get_current_state() or "IDLE"

            # Query recent download packages
            raw_packages = []
            try:
                raw_packages = dev.downloads.query_packages([{"bytesLoaded": True, "bytesTotal": True, "childCount": True, "enabled": True, "eta": True, "finished": True, "hosts": True, "maxResults": 10, "packageUUIDs": [], "priority": True, "running": True, "saveTo": True, "speed": True, "startAt": 0, "status": True}]) or []
            except Exception as e:
                logger.debug(f"Downloads query_packages error: {e}")

            # Also query linkgrabber packages (collecting/pending confirmation)
            raw_linkgrabber = []
            try:
                raw_linkgrabber = dev.linkgrabber.query_packages([{"availableOnlineCount": True, "bytesTotal": True, "childCount": True, "enabled": True, "hosts": True, "maxResults": 10, "packageUUIDs": [], "saveTo": True, "startAt": 0, "status": True}]) or []
            except Exception as e:
                logger.debug(f"Linkgrabber query_packages error: {e}")

            packages = []
            active_count = 0

            for p in raw_packages:
                is_running = bool(p.get("running") or (p.get("speed", 0) > 0))
                if is_running:
                    active_count += 1
                packages.append({
                    "uuid": str(p.get("uuid", "")),
                    "name": p.get("name", "Unknown Package"),
                    "bytesLoaded": p.get("bytesLoaded", 0),
                    "bytesTotal": p.get("bytesTotal", 0),
                    "speed": p.get("speed", 0),
                    "status": p.get("status") or ("Running" if is_running else ("Finished" if p.get("finished") else "Stopped")),
                    "finished": bool(p.get("finished", False)),
                    "running": is_running,
                    "eta": p.get("eta", -1),
                    "childCount": p.get("childCount", 1),
                    "type": "download"
                })

            for lp in raw_linkgrabber:
                packages.append({
                    "uuid": str(lp.get("uuid", "")),
                    "name": lp.get("name", "Grabbed Package"),
                    "bytesLoaded": 0,
                    "bytesTotal": lp.get("bytesTotal", 0),
                    "speed": 0,
                    "status": "LinkGrabber (" + (lp.get("status") or "Processing") + ")",
                    "finished": False,
                    "running": False,
                    "eta": -1,
                    "childCount": lp.get("childCount", 1),
                    "type": "linkgrabber"
                })

            total_count = len(packages)

            _status_cache = {
                "online": True,
                "dl_speed": speed,
                "state": state,
                "active_downloads": active_count,
                "total_downloads": total_count,
                "packages": packages[:10],
                "last_updated": time.time()
            }
            return {k: v for k, v in _status_cache.items() if k != "last_updated"}

        except Exception as e:
            logger.error(f"Error fetching JDownloader status: {e}")
            _status_cache = {
                "online": False,
                "dl_speed": 0,
                "state": "OFFLINE",
                "active_downloads": 0,
                "total_downloads": 0,
                "packages": [],
                "error": str(e),
                "last_updated": time.time()
            }
            return {k: v for k, v in _status_cache.items() if k != "last_updated"}


def _auto_confirm_worker():
    """Background helper to move parsed links from Linkgrabber to Downloads and start them."""
    for _ in range(8):
        time.sleep(1.2)
        try:
            dev = _get_device()
            pkgs = dev.linkgrabber.query_packages() or []
            uuids = [p['uuid'] for p in pkgs if p.get('uuid') and p.get('onlineCount', 0) > 0]
            if uuids:
                dev.linkgrabber.move_to_downloadlist([], uuids)
                dev.downloadcontroller.start_downloads()
                with _lock:
                    _status_cache["last_updated"] = 0
                break
            elif not dev.linkgrabber.is_collecting() and pkgs:
                # Collector finished but all count might be non-zero
                all_uuids = [p['uuid'] for p in pkgs if p.get('uuid')]
                if all_uuids:
                    dev.linkgrabber.move_to_downloadlist([], all_uuids)
                    dev.downloadcontroller.start_downloads()
                    with _lock:
                        _status_cache["last_updated"] = 0
                    break
        except Exception as e:
            logger.debug(f"Auto-confirm worker check: {e}")


def add_download_links(links: str, autostart: bool = True, package_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Submit download links/URLs/magnets to JDownloader.
    """
    if not links or not isinstance(links, str) or not links.strip():
        raise ValueError("No download links provided.")

    dev = _get_device()
    params = [{
        "autostart": autostart,
        "links": links.strip(),
        "packageName": package_name.strip() if package_name else None,
        "overwritePackagizerRules": False
    }]

    try:
        res = dev.linkgrabber.add_links(params=params)
    except Exception:
        # Reconnect and retry
        dev = _get_device(force_reconnect=True)
        res = dev.linkgrabber.add_links(params=params)

    if autostart:
        try:
            dev.downloadcontroller.start_downloads()
        except Exception as e:
            logger.debug(f"Failed to start_downloads after add_links: {e}")

        # Launch background auto-confirmation worker
        threading.Thread(target=_auto_confirm_worker, daemon=True).start()

    # Invalidate cache so UI sees instant update
    with _lock:
        _status_cache["last_updated"] = 0

    return {"success": True, "result": res}

