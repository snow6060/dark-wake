import math

import numpy as np

from src import vessel_census as vc

CHIP = 288


def _box(c, half=None):
    th = math.radians(c.angle_deg)
    hx = c.length_px / 2 * abs(math.sin(th)) + c.width_px / 2 * abs(math.cos(th)) + 1
    hy = c.length_px / 2 * abs(math.cos(th)) + c.width_px / 2 * abs(math.sin(th)) + 1
    x0, x1 = c.cx - hx, c.cx + hx
    if half == "left":
        x1 = c.cx
    return [x0, c.cy - hy, x1, c.cy + hy]


def refine_candidates(rgb, cands, segment, sample=0):
    """Run SAM on every fused pair blob (+ `sample` ordinary ships). Sets c.sam on those candidates.
    contact: one SAM mask covers BOTH hulls of a pair. Masks not sitting on a candidate are ignored."""
    todo = [c for c in cands if c.wide]
    singles = [c for c in cands if not c.wide]
    if sample and singles:
        step = max(1, len(singles) // sample)
        todo += singles[::step][:sample]
    H, W = rgb.shape[:2]
    for c in todo:
        x0 = int(min(max(c.cx - CHIP / 2, 0), W - CHIP))
        y0 = int(min(max(c.cy - CHIP / 2, 0), H - CHIP))
        b = _box(c, "left" if c.wide else None)
        found = segment(rgb[y0:y0 + CHIP, x0:x0 + CHIP], [[b[0] - x0, b[1] - y0, b[2] - x0, b[3] - y0]])
        cx, cy = int(round(c.cx - x0)), int(round(c.cy - y0))
        th = math.radians(c.angle_deg)
        px, py = math.cos(th), math.sin(th)
        d = max(2.0, c.width_px / 4)
        a = (int(round(cy - py * d)), int(round(cx - px * d)))
        bpt = (int(round(cy + py * d)), int(round(cx + px * d)))
        on = [f for f in found if f["mask"][min(max(cy, 0), CHIP - 1), min(max(cx, 0), CHIP - 1)]
              or f["mask"][a] or f["mask"][bpt]]
        if not on:
            c.sam = {"found": False}
            continue
        best = max(on, key=lambda f: f["mask"].sum())
        m = best["mask"]
        _, _, L, Wd, _ = vc.measure_mask(m)
        c.sam = {"found": True, "score": round(best["score"], 2), "length_m": round(L), "width_m": round(Wd),
                 "contact": bool(c.wide and m[a] and m[bpt])}
    return cands