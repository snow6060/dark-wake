"""Hull census: find ships in a Sentinel-2 true-colour crop and measure them.

Works on the stored full-resolution JPEG (10 m per pixel). propose_candidates() gives cheap
local-contrast proposals; measure_mask() turns a hull mask (SAM or classical) into metres.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from scipy import ndimage as ndi

GSD_M = 10.0  # Sentinel-2 true-colour pixel size
WIDE_RATIO = 0.34  # width/length above this is too beamy for one hull (typical 0.15-0.25)


@dataclass
class Candidate:
    cx: float
    cy: float
    length_px: float
    width_px: float
    angle_deg: float     # long-axis orientation, degrees clockwise from north (0-180)
    area_px: int
    contrast: float
    wide: bool = False   # unusually wide for its length: two hulls side by side


@dataclass
class Hull:
    cx: float
    cy: float
    length_m: float
    width_m: float
    axis_deg: float
    size_class: str
    score: float = 1.0
    method: str = "classical"
    mask: np.ndarray | None = field(default=None, repr=False)


def water_mask(rgb: np.ndarray, max_lum: float = 75.0) -> np.ndarray:
    lum = rgb.astype(np.float32).mean(axis=2)
    small = ndi.zoom(lum, 0.125, order=1)
    smooth = ndi.gaussian_filter(small, 3)
    mask = ndi.zoom(smooth, (lum.shape[0] / smooth.shape[0], lum.shape[1] / smooth.shape[1]), order=1) < max_lum
    mask = mask[: lum.shape[0], : lum.shape[1]]
    return ndi.binary_erosion(mask, iterations=6)


def cloud_mask(rgb: np.ndarray, min_area_px: int = 250) -> np.ndarray:
    img = rgb.astype(np.float32)
    bright = img.max(axis=2)
    chroma = bright - img.min(axis=2)
    pale = ndi.binary_closing((bright > 105) & (chroma < 45), structure=np.ones((3, 3)))
    labels, n = ndi.label(pale)
    if n == 0:
        return np.zeros(bright.shape, dtype=bool)
    areas = ndi.sum(pale, labels, range(1, n + 1))
    big = np.isin(labels, 1 + np.nonzero(areas >= min_area_px)[0])
    return ndi.binary_dilation(big, iterations=3)


def _local_background(chan: np.ndarray, size: int = 31) -> np.ndarray:
    small = ndi.zoom(chan, 0.25, order=1)
    bg = ndi.median_filter(small, size=max(3, size // 4 * 2 + 1))
    out = ndi.zoom(bg, (chan.shape[0] / bg.shape[0], chan.shape[1] / bg.shape[1]), order=1)
    return out[: chan.shape[0], : chan.shape[1]]


def _pca_axes(ys: np.ndarray, xs: np.ndarray) -> tuple[float, float, float]:
    pts = np.c_[xs, ys].astype(np.float64)
    pts -= pts.mean(axis=0)
    cov = np.cov(pts.T) if len(pts) > 2 else np.eye(2) * 0.25
    vals, vecs = np.linalg.eigh(cov)
    major = vecs[:, 1]
    proj = pts @ major
    minor = vecs[:, 0]
    proj_w = pts @ minor
    length = float(proj.max() - proj.min() + 1)
    width = float(proj_w.max() - proj_w.min() + 1)
    angle = math.degrees(math.atan2(major[0], -major[1])) % 180.0
    return length, width, angle


def propose_candidates(
    rgb: np.ndarray,
    min_len_px: float = 5.0,
    max_len_px: float = 50.0,
    max_width_px: float = 24.0,
    min_elongation: float = 1.7,
    contrast: float = 28.0,
    wide_min_chroma: float = 40.0,
) -> list[Candidate]:
    img = rgb.astype(np.float32)
    water = water_mask(rgb)
    clouds = cloud_mask(rgb)
    bright = img.max(axis=2)
    chroma = bright - img.min(axis=2)
    bg = _local_background(bright)
    diff = bright - bg
    mask = (diff > contrast) & water
    mask = ndi.binary_closing(mask, structure=np.ones((3, 3)))
    labels, n = ndi.label(mask, structure=np.ones((3, 3)))
    out: list[Candidate] = []
    for i, sl in enumerate(ndi.find_objects(labels), start=1):
        if sl is None:
            continue
        ys, xs = np.nonzero(labels[sl] == i)
        if len(ys) < 6:
            continue
        ys = ys + sl[0].start
        xs = xs + sl[1].start
        if clouds[int(ys.mean()), int(xs.mean())]:
            continue
        length, width, angle = _pca_axes(ys, xs)
        if not (min_len_px <= length <= max_len_px) or width > max_width_px:
            continue
        if length / max(width, 1.0) < min_elongation:
            continue
        wide = length * GSD_M >= 150 and width / length > WIDE_RATIO
        if (wide or width > 14.0) and float(chroma[ys, xs].mean()) < wide_min_chroma:
            continue
        out.append(Candidate(float(xs.mean()), float(ys.mean()), length, width, angle, len(ys),
                             float(diff[ys, xs].max()), wide))
    return out


def measure_mask(mask: np.ndarray, gsd_m: float = GSD_M) -> tuple[float, float, float, float, float]:
    """Hull mask -> (cx, cy, length_m, width_m, axis_deg)."""
    ys, xs = np.nonzero(mask)
    if len(ys) < 3:
        return float("nan"), float("nan"), 0.0, 0.0, 0.0
    length, width, angle = _pca_axes(ys, xs)
    return float(xs.mean()), float(ys.mean()), length * gsd_m, width * gsd_m, angle


def size_class(length_m: float) -> str:
    if length_m >= 150:
        return "LARGE"
    if length_m >= 60:
        return "MEDIUM"
    return "SMALL"


def merge_duplicates(hulls: Iterable[Hull], radius_px: float = 4.0) -> list[Hull]:
    kept: list[Hull] = []
    for h in sorted(hulls, key=lambda x: -x.score):
        if all(math.hypot(h.cx - k.cx, h.cy - k.cy) > radius_px for k in kept):
            kept.append(h)
    return kept


def candidate_pairs(hulls: list[Hull], max_gap_m: float = 60.0) -> list[tuple[int, int, float]]:
    pairs = []
    for i in range(len(hulls)):
        for j in range(i + 1, len(hulls)):
            a, b = hulls[i], hulls[j]
            dx, dy = (b.cx - a.cx) * GSD_M, (b.cy - a.cy) * GSD_M
            if math.hypot(dx, dy) > 0.5 * (a.length_m + b.length_m) + max_gap_m:
                continue
            dang = abs(a.axis_deg - b.axis_deg)
            if min(dang, 180 - dang) > 20:
                continue
            ax = math.radians(a.axis_deg)
            ux, uy = math.sin(ax), -math.cos(ax)
            along = abs(dx * ux + dy * uy)
            across = abs(-dx * uy + dy * ux)
            gap = across - 0.5 * (a.width_m + b.width_m)
            if gap <= max_gap_m * 0.5 and along <= 0.6 * max(a.length_m, b.length_m):
                pairs.append((i, j, float(max(gap, 0.0))))
    return pairs