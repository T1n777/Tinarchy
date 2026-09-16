import os
import io
import urllib.request
import tempfile

try:
    from tinarchy import config
except ImportError:
    import config

try:
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

OPTIMIZED_DIR = "/var/lib/suwayomi/cache/optimized_thumbnails"
RAW_CACHE_DIR = "/var/lib/suwayomi/cache/Tachidesk/thumbnails"
import json
import time

_PRIVATE_CACHE = {"ids": set(), "ts": 0}

def get_private_manga_ids() -> set[int]:
    """Returns set of manga IDs belonging to private category '_'."""
    now = time.time()
    if now - _PRIVATE_CACHE["ts"] < 60 and _PRIVATE_CACHE["ids"]:
        return _PRIVATE_CACHE["ids"]
    try:
        query = json.dumps({
            "query": "{ mangas(filter: { inLibrary: { equalTo: true } }, first: 100) { nodes { id categories { nodes { name } } } } }"
        }).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:4566/api/graphql", data=query, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                nodes = data.get("data", {}).get("mangas", {}).get("nodes", [])
                p_ids = set()
                for m in nodes:
                    cats = [c.get("name", "").strip() for c in m.get("categories", {}).get("nodes", [])]
                    if "_" in cats or "private" in [c.lower() for c in cats]:
                        p_ids.add(m["id"])
                _PRIVATE_CACHE["ids"] = p_ids
                _PRIVATE_CACHE["ts"] = now
                return p_ids
    except Exception:
        pass
    return _PRIVATE_CACHE["ids"]

def is_manga_private(manga_id: int) -> bool:
    return manga_id in get_private_manga_ids()

SUWAYOMI_INTERNAL_URLS = [
    "http://127.0.0.1:4566/api/v1/manga/{manga_id}/thumbnail",
    "http://127.0.0.1:4567/api/v1/manga/{manga_id}/thumbnail",
    "http://127.0.0.1:4567/manga/api/v1/manga/{manga_id}/thumbnail",
]

def optimize_image_data(raw_data: bytes, target_width: int = 340, quality: int = 80) -> tuple[bytes, str]:
    """Downscales raw image bytes to an optimized high-DPI WebP thumbnail."""
    if not HAS_PIL:
        # Fallback to serving raw bytes if Pillow is not installed on host
        return raw_data, "image/jpeg"

    with Image.open(io.BytesIO(raw_data)) as img:
        # Fast draft decoding for JPEGs
        if getattr(img, 'format', '') == 'JPEG':
            try:
                img.draft('RGB', (target_width * 2, int(target_width * 3)))
            except Exception:
                pass

        if img.mode in ('RGBA', 'LA'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        w, h = img.size
        if w > target_width:
            new_w = target_width
            new_h = max(1, int(h * (target_width / w)))
            img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)

        buf = io.BytesIO()
        img.save(buf, format='WEBP', quality=quality, method=2)
        return buf.getvalue(), "image/webp"

def get_or_generate_thumbnail(manga_id: int, query_string: str = "") -> tuple[bytes, str]:
    """
    Returns (image_bytes, content_type).
    If the optimized WebP thumbnail exists, it returns immediately.
    If missing, it fetches the raw cover from Tachidesk cache or Suwayomi core,
    resizes it in ~35ms, persists it to disk, and returns the optimized WebP.
    Gracefully handles environments where Suwayomi is not configured.
    """
    app_cfg = config.get_app_config()
    # If Suwayomi is explicitly disabled in .env, exit immediately
    if app_cfg.get('enable_suwayomi') is False:
        return b"", "text/plain"

    try:
        os.makedirs(OPTIMIZED_DIR, exist_ok=True)
    except Exception:
        pass

    optimized_path = os.path.join(OPTIMIZED_DIR, f"{manga_id}.webp")

    if os.path.isfile(optimized_path) and os.path.getsize(optimized_path) > 0:
        try:
            with open(optimized_path, "rb") as f:
                return f.read(), "image/webp"
        except Exception:
            pass

    # Find raw image in Tachidesk cache
    raw_data = None

    if os.path.isdir(RAW_CACHE_DIR):
        for ext in ('.webp', '.jpg', '.jpeg', '.png'):
            candidate = os.path.join(RAW_CACHE_DIR, f"{manga_id}{ext}")
            if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                try:
                    with open(candidate, "rb") as f:
                        raw_data = f.read()
                    break
                except Exception:
                    pass

    # If not found on disk, fetch from Suwayomi core
    if not raw_data:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        for tmpl in SUWAYOMI_INTERNAL_URLS:
            try:
                url = tmpl.format(manga_id=manga_id)
                if query_string:
                    url = f"{url}?{query_string}"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        raw_data = resp.read()
                        if raw_data:
                            break
            except Exception:
                pass

    if not raw_data:
        return b"", "text/plain"

    # Optimize to WebP
    try:
        opt_bytes, ctype = optimize_image_data(raw_data)
        if ctype == "image/webp":
            # Atomically write to disk
            tmp_path = f"{optimized_path}.tmp.{os.getpid()}"
            with open(tmp_path, "wb") as f:
                f.write(opt_bytes)
            os.chmod(tmp_path, 0o644)
            os.replace(tmp_path, optimized_path)
        return opt_bytes, ctype
    except Exception:
        # Fallback to returning raw data if optimization fails
        return raw_data, "image/jpeg"
