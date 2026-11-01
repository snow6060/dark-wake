import argparse
import math
import os
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from src import vessel_census as vc  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
CHIP = 288


def hull_box(c, half=None):
    th = math.radians(c.angle_deg)
    hx = c.length_px / 2 * abs(math.sin(th)) + c.width_px / 2 * abs(math.cos(th)) + 1
    hy = c.length_px / 2 * abs(math.cos(th)) + c.width_px / 2 * abs(math.sin(th)) + 1
    x0, x1 = c.cx - hx, c.cx + hx
    if half == "left":
        x1 = c.cx
    return [x0, c.cy - hy, x1, c.cy + hy]


def pick_centres(cands):
    if not cands:
        return []
    wide = [c for c in cands if c.wide]
    pts = np.array([[c.cx, c.cy] for c in cands])
    dens = [(np.hypot(*(pts - p).T) < CHIP / 2).sum() for p in pts]
    out = []
    if wide:
        out.append(("pair", wide[0]))
    out.append(("dense", cands[int(np.argmax(dens))]))
    out.append(("single", cands[int(np.argmin(dens))]))
    return out


def run(image_path, out_dir, segment):
    rgb = np.asarray(Image.open(image_path).convert("RGB"))
    cands = vc.propose_candidates(rgb)
    os.makedirs(out_dir, exist_ok=True)
    print(f"candidates: {len(cands)}")
    for name, c in pick_centres(cands):
        x0 = int(min(max(c.cx - CHIP / 2, 0), rgb.shape[1] - CHIP))
        y0 = int(min(max(c.cy - CHIP / 2, 0), rgb.shape[0] - CHIP))
        chip = rgb[y0:y0 + CHIP, x0:x0 + CHIP]
        inside = [k for k in cands if x0 <= k.cx < x0 + CHIP and y0 <= k.cy < y0 + CHIP]
        boxes = []
        for k in inside[:6]:
            b = hull_box(k, "left" if k.wide else None)
            boxes.append([b[0] - x0, b[1] - y0, b[2] - x0, b[3] - y0])
        t = time.time()
        found = segment(chip, boxes) if boxes else []
        lens = [vc.measure_mask(f["mask"])[2] for f in found]
        print(
            f"{name}: {len(inside)} candidates, {len(boxes)} example boxes -> SAM found {len(found)} objects "
            f"in {time.time() - t:.1f}s; lengths m: {sorted(round(x) for x in lens)[:12]}"
        )
        ov = chip.copy().astype(np.float32)
        rng = np.random.default_rng(1)
        for f in found:
            ov[f["mask"]] = 0.45 * ov[f["mask"]] + 0.55 * rng.integers(80, 255, 3)
        Image.fromarray(np.hstack([chip, ov.astype(np.uint8)])).resize(
            (CHIP * 2 * 3, CHIP * 3), Image.NEAREST
        ).save(os.path.join(out_dir, f"{name}.png"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", default="_private/sam_probe")
    a = ap.parse_args()
    from src.sam_runtime import segment_exemplars

    run(a.image, a.out, segment_exemplars)
    import torch

    if torch.cuda.is_available():
        print(f"peak GPU memory: {torch.cuda.max_memory_allocated() / 1e9:.2f} GB")
