"""SAM 3.1 hull segmentation using official Meta package."""
from __future__ import annotations

import os
import numpy as np
import torch
from PIL import Image

# Import Meta's official model builder from the installed sam3 package
try:
    from sam3.model_builder import build_sam3_image_model
except ImportError:
    build_sam3_image_model = None

_model = None


def load():
    global _model
    if _model is None:
        if build_sam3_image_model is None:
            raise ImportError("The official 'sam3' package is not accessible in this environment.")
        
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Initialize the official Meta model instance
        _model = build_sam3_image_model(device=dev, eval_mode=True)
    return _model


def segment_exemplars(chip_rgb, boxes_xyxy, threshold=0.4, mask_threshold=0.5):
    """Positive example boxes -> matching hulls using Meta's native runtime."""
    model = load()
    image_pil = Image.fromarray(chip_rgb)
    
    with torch.no_grad():
        # Execute prediction using Meta's native box-prompt API
        results = model.predict_box(image_pil, boxes_xyxy)
        
    masks = results.get("masks", np.array([]))
    boxes = results.get("boxes", np.array([]))
    scores = results.get("scores", np.array([]))
    
    return [
        {
            "mask": masks[i].astype(bool), 
            "box": boxes[i], 
            "score": float(scores[i])
        } 
        for i in range(len(scores)) if scores[i] >= threshold
    ]