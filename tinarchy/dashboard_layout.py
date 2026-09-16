import os
import json
import logging
from tinarchy.config import BASE_DIR
from tinarchy.services import SERVICES, CATEGORIES

logger = logging.getLogger(__name__)
LAYOUT_FILE = os.path.join(BASE_DIR, 'dashboard_layout.json')

def get_default_layout():
    return {
        'version': 2,
        'widgets': {
            'stats_bar': {'enabled': True, 'order': 0},
            'qbittorrent': {'enabled': True, 'order': 1},
            'manga_shelf': {'enabled': True, 'order': 2}
        },
        'items': [s['id'] for s in SERVICES],
        'custom_bookmarks': []
    }

def load_dashboard_layout():
    if not os.path.exists(LAYOUT_FILE):
        return get_default_layout()

    try:
        with open(LAYOUT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return get_default_layout()

        # Migrate from legacy sections structure if needed
        if 'items' not in data and 'sections' in data:
            flat = []
            for sec in data.get('sections', []):
                flat.extend(sec.get('items', []))
            data['items'] = flat

        if 'items' not in data:
            data['items'] = [s['id'] for s in SERVICES]

        # Reconcile any newly installed/configured services not in saved layout
        existing_items = set(data.get('items', []))
        for s in SERVICES:
            sid = s['id']
            if sid not in existing_items:
                data['items'].append(sid)
                existing_items.add(sid)

        return data
    except Exception as e:
        logger.warning(f"Failed to load {LAYOUT_FILE}: {e}. Falling back to default layout.")
        return get_default_layout()

def save_dashboard_layout(layout_data):
    if not isinstance(layout_data, dict):
        raise ValueError("Invalid layout data: root must be a dict")

    items = layout_data.get('items', [])
    if not isinstance(items, list):
        if 'sections' in layout_data and isinstance(layout_data['sections'], list):
            flat = []
            for sec in layout_data['sections']:
                flat.extend(sec.get('items', []))
            layout_data['items'] = flat
        else:
            raise ValueError("Invalid layout data: items must be a list")

    tmp_file = LAYOUT_FILE + '.tmp'
    with open(tmp_file, 'w', encoding='utf-8') as f:
        json.dump(layout_data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_file, LAYOUT_FILE)
    return True

def reset_dashboard_layout():
    if os.path.exists(LAYOUT_FILE):
        try:
            os.remove(LAYOUT_FILE)
        except Exception:
            pass
    return get_default_layout()
