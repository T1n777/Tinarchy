import os
import json
import logging
from tinarchy.config import BASE_DIR
from tinarchy.services import SERVICES, CATEGORIES

logger = logging.getLogger(__name__)
LAYOUT_FILE = os.path.join(BASE_DIR, 'dashboard_layout.json')

def get_default_layout():
    cat_map = {c['id']: {'id': c['id'], 'name': c['name'], 'icon': c['icon'], 'collapsed': False, 'items': []} for c in CATEGORIES}
    cat_map['bookmarks'] = {'id': 'bookmarks', 'name': 'Custom Bookmarks', 'icon': '⭐', 'collapsed': False, 'items': []}

    for s in SERVICES:
        cid = s.get('category', 'media')
        if cid not in cat_map:
            cid = 'media'
        cat_map[cid]['items'].append(s['id'])

    sections = [cat_map[c['id']] for c in CATEGORIES if c['id'] in cat_map]
    if 'bookmarks' in cat_map:
        sections.append(cat_map['bookmarks'])

    return {
        'version': 1,
        'widgets': {
            'stats_bar': {'enabled': True, 'order': 0},
            'qbittorrent': {'enabled': True, 'order': 1},
            'manga_shelf': {'enabled': True, 'order': 2}
        },
        'sections': sections,
        'custom_bookmarks': []
    }

def load_dashboard_layout():
    if not os.path.exists(LAYOUT_FILE):
        return get_default_layout()

    try:
        with open(LAYOUT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, dict) or 'sections' not in data:
            return get_default_layout()

        # Reconcile any newly installed/configured services not in saved layout
        all_section_items = set()
        for sec in data.get('sections', []):
            all_section_items.update(sec.get('items', []))

        for s in SERVICES:
            sid = s['id']
            if sid not in all_section_items:
                target_cat = s.get('category', 'media')
                found = False
                for sec in data['sections']:
                    if sec.get('id') == target_cat:
                        sec.setdefault('items', []).append(sid)
                        found = True
                        break
                if not found and data['sections']:
                    data['sections'][0].setdefault('items', []).append(sid)

        return data
    except Exception as e:
        logger.warning(f"Failed to load {LAYOUT_FILE}: {e}. Falling back to default layout.")
        return get_default_layout()

def save_dashboard_layout(layout_data):
    if not isinstance(layout_data, dict):
        raise ValueError("Invalid layout data: root must be a dict")

    sections = layout_data.get('sections', [])
    if not isinstance(sections, list):
        raise ValueError("Invalid layout data: sections must be a list")

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
