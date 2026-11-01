"""SAM 3.1 hull segmentation. Isolated so the API process never has to import torch."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import Sam3Model, Sam3Processor

MODEL_ID = os.getenv("SAM_MODEL_ID", "facebook/sam3.1")
_model = None
_proc = None


def _ensure_hf_token() -> None:
    if os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN"):
        return
    token_path = Path(os.getenv("HF_TOKEN_FILE", r"D:\ai_cache\huggingface\token"))
    if token_path.is_file():
        os.environ["HF_TOKEN"] = token_path.read_text(encoding="utf-8").strip()


def load():
    global _model, _proc
    if _model is None:
        _ensure_hf_token()
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        dt = torch.float16 if dev == "cuda" else torch.float32
        try:
            m = Sam3Model.from_pretrained(MODEL_ID, dtype=dt)
        except TypeError:
            m = Sam3Model.from_pretrained(MODEL_ID, torch_dtype=dt)
        _model = m.to(dev).eval()
        _proc = Sam3Processor.from_pretrained(MODEL_ID)
    return _model, _proc


def segment_exemplars(chip_rgb, boxes_xyxy, threshold=0.4, mask_threshold=0.5):
    """Positive example boxes -> every matching object in the chip."""
    model, proc = load()
    inputs = proc(
        images=Image.fromarray(chip_rgb),
        input_boxes=[[list(map(float, b)) for b in boxes_xyxy]],
        input_boxes_labels=[[1] * len(boxes_xyxy)],
        return_tensors="pt",
    ).to(model.device)
    sizes = inputs.get("original_sizes").tolist()
    feed = {k: (v.to(model.dtype) if torch.is_floating_point(v) else v) for k, v in inputs.items()}
    with torch.no_grad():
        out = model(**feed)
    res = proc.post_process_instance_segmentation(
        out, threshold=threshold, mask_threshold=mask_threshold, target_sizes=sizes
    )[0]
    masks = res["masks"].cpu().numpy().astype(bool)
    boxes, scores = res["boxes"].cpu().numpy(), res["scores"].cpu().numpy()
    return [{"mask": masks[i], "box": boxes[i], "score": float(scores[i])} for i in range(len(scores))]
