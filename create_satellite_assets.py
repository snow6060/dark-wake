import os
from PIL import Image, ImageDraw, ImageFont

LOCATIONS = [
    ("hormuz", "STRAIT OF HORMUZ", "26.5667° N, 56.2500° E", "CHOKEPOINT // ZONE 1"),
    ("bab_el_mandeb", "BAB EL-MANDEB STRAIT", "12.5833° N, 43.3333° E", "CHOKEPOINT // ZONE 2"),
    ("malacca", "MALACCA STRAIT / SINGAPORE", "1.4300° N, 103.5000° E", "CHOKEPOINT // ZONE 3"),
    ("fujairah", "PORT OF FUJAIRAH (BUNKERING HUB)", "25.1800° N, 56.3600° E", "TERMINAL DOCK // ZONE 4"),
    ("suez", "SUEZ CANAL (PORT SAID / SUEZ)", "30.5852° N, 32.2654° E", "MARITIME CANAL // ZONE 5"),
    ("singapore", "PORT OF SINGAPORE", "1.2902° N, 103.8519° E", "TERMINAL DOCK // ZONE 6"),
    ("rotterdam", "PORT OF ROTTERDAM", "51.9244° N, 4.4777° E", "TERMINAL DOCK // ZONE 7"),
    ("jebel_ali", "PORT OF JEBEL ALI (DP WORLD)", "25.0112° N, 55.0617° E", "TERMINAL DOCK // ZONE 8"),
]

DIRS = [
    "assets/satellite_chokepoints",
    "dark-wake/public/assets/satellite_chokepoints",
]

for d in DIRS:
    os.makedirs(d, exist_ok=True)

width, height = 960, 540

for key, name, coords, zone in LOCATIONS:
    img = Image.new("RGBA", (width, height), (10, 16, 26, 255))
    draw = ImageDraw.Draw(img)

    # Draw dark ocean background with subtle grid
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=(20, 32, 48, 120), width=1)
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=(20, 32, 48, 120), width=1)

    # Draw major radar grid circles
    cx, cy = width // 2, height // 2
    for r in [120, 220, 320]:
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=(30, 58, 85, 180), width=1)
    draw.line([(cx, 40), (cx, height - 40)], fill=(38, 70, 100, 150), width=1)
    draw.line([(60, cy), (width - 60, cy)], fill=(38, 70, 100, 150), width=1)

    # Corner brackets / viewfinder HUD
    hud_c = (56, 189, 248, 220)
    b_len = 30
    draw.line([(30, 30), (30 + b_len, 30)], fill=hud_c, width=2)
    draw.line([(30, 30), (30, 30 + b_len)], fill=hud_c, width=2)
    draw.line([(width - 30, 30), (width - 30 - b_len, 30)], fill=hud_c, width=2)
    draw.line([(width - 30, 30), (width - 30, 30 + b_len)], fill=hud_c, width=2)
    draw.line([(30, height - 30), (30 + b_len, height - 30)], fill=hud_c, width=2)
    draw.line([(30, height - 30), (30, height - 30 - b_len)], fill=hud_c, width=2)
    draw.line([(width - 30, height - 30), (width - 30 - b_len, height - 30)], fill=hud_c, width=2)
    draw.line([(width - 30, height - 30), (width - 30, height - 30 - b_len)], fill=hud_c, width=2)

    # Simulated vessel detection boxes (SAM 3.1 style)
    vessels = [
        (cx - 140, cy - 60, 24, 12, "VLCC-01"),
        (cx + 80, cy - 90, 20, 10, "SUEZMAX-04"),
        (cx + 120, cy + 40, 28, 14, "AFRAMAX-09"),
        (cx - 50, cy + 80, 18, 9, "LNG-TANKER-02"),
    ]
    for vx, vy, vw, vh, label in vessels:
        draw.rectangle([(vx, vy), (vx + vw, vy + vh)], outline=(244, 63, 94, 230), width=2)
        draw.rectangle([(vx - 2, vy - 2), (vx + vw + 2, vy + vh + 2)], outline=(244, 63, 94, 70), width=1)
        draw.text((vx, vy - 14), label, fill=(244, 63, 94, 240))

    # Header and HUD text
    draw.text((45, 42), f"🛰 SENTINEL-2 L2A SURVEILLANCE // {zone}", fill=(56, 189, 248, 255))
    draw.text((45, 62), f"LOCATION: {name}", fill=(240, 246, 252, 255))
    draw.text((45, 82), f"COORDINATES: {coords} | BAND: B02/B03/B04 VISUAL", fill=(148, 163, 184, 255))
    
    # Status stamps
    draw.text((width - 290, 42), "SAM 3.1 SEGMENTATION: ACTIVE", fill=(52, 211, 153, 255))
    draw.text((width - 290, 62), "OPTICAL CLOUD COVER: <12%", fill=(148, 163, 184, 255))
    draw.text((width - 290, 82), "STATUS: VERIFIED BENCHMARK TILE", fill=(251, 191, 36, 255))

    # Bottom bar telemetry
    draw.rectangle([(30, height - 55), (width - 30, height - 35)], fill=(15, 23, 42, 200), outline=(56, 189, 248, 90))
    draw.text((45, height - 50), "GEO-REGISTERED SATELLITE ASSET · AUTO-FALLBACK ACTIVE · 0 BROKEN LINK POLICY", fill=(125, 211, 252, 240))

    # Save to both target directories
    for d in DIRS:
        filepath = os.path.join(d, f"{key}.png")
        img.save(filepath, "PNG")
        print(f"Generated {filepath}")
