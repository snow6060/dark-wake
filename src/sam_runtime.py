"""SAM 3 hull segmentation via Meta's official sam3 package (image model + box exemplars)."""
import glob
import os

import numpy as np
import torch
from PIL import Image
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.model_builder import build_sam3_image_model

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _bpe_path():
    hits = glob.glob(os.path.join(_REPO, "sam3", "**", "bpe_simple_vocab_16e6.txt.gz"), recursive=True)
    if not hits:
        raise FileNotFoundError("bpe_simple_vocab_16e6.txt.gz not found under the sam3 folder")
    return hits[0]


_proc = None


def load(threshold=0.4):
    global _proc
    if _proc is None:
        model = build_sam3_image_model(bpe_path=_bpe_path())  # downloads weights on first run (gated: needs your HF login)
        _proc = Sam3Processor(model, confidence_threshold=threshold)
    return _proc


def _np(x):
    return x.detach().float().cpu().numpy() if hasattr(x, "detach") else np.asarray(x)


def segment_exemplars(chip_rgb, boxes_xyxy, threshold=0.4, mask_threshold=0.5):
    """Positive example boxes (chip pixels, x0 y0 x1 y1) -> every matching object SAM finds."""
    proc = load(threshold)
    h, w = chip_rgb.shape[:2]
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16, enabled=torch.cuda.is_available()):
        state = proc.set_image(Image.fromarray(chip_rgb))
        proc.reset_all_prompts(state)
        for x0, y0, x1, y1 in boxes_xyxy:
            norm = [((x0 + x1) / 2) / w, ((y0 + y1) / 2) / h, (x1 - x0) / w, (y1 - y0) / h]
            state = proc.add_geometric_prompt(box=norm, label=True, state=state)
    masks, boxes, scores = _np(state.get("masks", [])), _np(state.get("boxes", [])), _np(state.get("scores", []))
    if masks.size == 0:
        return []
    if masks.ndim == 4:
        masks = masks[:, 0]
    return [{"mask": masks[i] > mask_threshold, "box": boxes[i], "score": float(scores[i])}
            for i in range(len(scores))]