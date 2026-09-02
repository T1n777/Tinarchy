import os
import sys
import json
import colorsys
from PIL import Image

def rgb_to_hex(r, g, b):
    r_c = max(0, min(255, int(round(r))))
    g_c = max(0, min(255, int(round(g))))
    b_c = max(0, min(255, int(round(b))))
    return f"#{r_c:02x}{g_c:02x}{b_c:02x}"

def adjust_lightness(r, g, b, min_light=0.62, max_light=0.82, min_sat=0.35):
    """
    Guarantees readable, crisp text on dark frosted glass while
    preserving the exact hue and mood of the wallpaper.
    """
    rf, gf, bf = max(0.0, min(1.0, r / 255.0)), max(0.0, min(1.0, g / 255.0)), max(0.0, min(1.0, b / 255.0))
    h, l, s = colorsys.rgb_to_hls(rf, gf, bf)
    
    # Ensure color doesn't look washed out
    if s > 0.05:
        s = max(min_sat, min(0.95, s * 1.25))
    
    # Boost lightness into the readable zone (62% - 82%)
    if l < min_light:
        l = min_light + (l * 0.25)
    elif l > max_light:
        l = max_light
        
    nr, ng, nb = colorsys.hls_to_rgb(h, l, s)
    return int(nr * 255), int(ng * 255), int(nb * 255)

def make_dark_bg(r, g, b):
    """Creates a deep, rich obsidian background retaining the wallpaper tint."""
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    h, l, s = colorsys.rgb_to_hls(rf, gf, bf)
    # Deep slate background (lightness ~8%)
    nr, ng, nb = colorsys.hls_to_rgb(h, 0.08, min(0.30, s))
    return int(nr * 255), int(ng * 255), int(nb * 255)

def generate_pywal_palette(img_path):
    try:
        actual_img = img_path
        base_name = os.path.basename(img_path).rsplit('.', 1)[0]
        
        # 1. Prioritize pre-rendered 2KB .webp thumbnail for instant 10ms execution
        possible_webp = f"/home/pineapple/server-dashboard/public/thumbnails/{base_name}.webp"
        if os.path.exists(possible_webp):
            actual_img = possible_webp
        elif img_path.lower().endswith('.mp4'):
            frame_path = f'/tmp/wal_frame_{base_name}.png'
            if not os.path.exists(frame_path):
                os.system(f"ffmpeg -y -ss 00:00:01 -i '{img_path}' -vframes 1 '{frame_path}' >/dev/null 2>&1")
            if os.path.exists(frame_path):
                actual_img = frame_path

        img = Image.open(actual_img).convert('RGB')
        img.thumbnail((200, 200), Image.Resampling.LANCZOS)
        
        quantized = img.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette()[:48]
        
        raw_colors = []
        for i in range(0, len(palette), 3):
            raw_colors.append((palette[i], palette[i+1], palette[i+2]))
            
        def lum(c): return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
        def sat(c):
            max_c, min_c = max(c), min(c)
            return (max_c - min_c) / (max_c if max_c > 0 else 1)
            
        raw_colors.sort(key=lum)
        
        # Base dark background (tinted obsidian)
        bg_rgb = make_dark_bg(*raw_colors[0])
        
        # Extract vivid saturated accents with guaranteed high readability on dark glass
        candidates = sorted(raw_colors[1:-1], key=sat, reverse=True)
        if not candidates:
            candidates = [(105, 180, 195), (174, 158, 92), (120, 139, 153)]
            
        acc1 = adjust_lightness(*candidates[0], min_light=0.74, max_light=0.86) # Primary Accent
        acc2 = adjust_lightness(*candidates[1] if len(candidates) > 1 else candidates[0], min_light=0.70, max_light=0.82)
        acc3 = adjust_lightness(*candidates[2] if len(candidates) > 2 else candidates[0], min_light=0.72, max_light=0.84)
        acc4 = adjust_lightness(*candidates[3] if len(candidates) > 3 else candidates[0], min_light=0.68, max_light=0.80)

        # Pure crisp high-contrast foreground text (#f0f6fc)
        fg_rgb = (240, 246, 252) # Clean bright white-silver #f0f6fc
        muted_rgb = (163, 179, 194) # Readable soft slate #a3b3c2
        
        # Build standard 16-color Pywal dictionary
        c0 = rgb_to_hex(*bg_rgb)
        c1 = rgb_to_hex(*acc2)
        c2 = rgb_to_hex(*acc3)
        c3 = rgb_to_hex(*acc4)
        c4 = rgb_to_hex(*acc1) # Primary Accent (color4)
        c5 = rgb_to_hex(*acc2)
        c6 = rgb_to_hex(*acc3)
        c7 = rgb_to_hex(*fg_rgb) # Foreground
        c8 = rgb_to_hex(*muted_rgb)
        
        pywal_dict = {
            "wallpaper": img_path,
            "alpha": "100",
            "special": {
                "background": c0,
                "foreground": c7,
                "cursor": c7
            },
            "colors": {
                "color0": c0,
                "color1": c1,
                "color2": c2,
                "color3": c3,
                "color4": c4,
                "color5": c5,
                "color6": c6,
                "color7": c7,
                "color8": c8,
                "color9": c1,
                "color10": c2,
                "color11": c3,
                "color12": c4,
                "color13": c5,
                "color14": c6,
                "color15": c7
            }
        }
        return pywal_dict
    except Exception as e:
        print(f"Error generating pywal: {e}", file=sys.stderr)
        return {
            "wallpaper": img_path,
            "alpha": "100",
            "special": {"background": "#0f1419", "foreground": "#f0f6fc", "cursor": "#f0f6fc"},
            "colors": {
                "color0": "#0f1419", "color1": "#79b8ff", "color2": "#b392f0", "color3": "#f97583",
                "color4": "#79b8ff", "color5": "#ffab70", "color6": "#7ee787", "color7": "#f0f6fc",
                "color8": "#a3b3c2", "color9": "#79b8ff", "color10": "#b392f0", "color11": "#f97583",
                "color12": "#79b8ff", "color13": "#ffab70", "color14": "#7ee787", "color15": "#f0f6fc"
            }
        }
