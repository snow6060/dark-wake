"""SAM 3.1 hull segmentation using official Meta checkpoints and runtime."""
from __future__ import annotations

import os
from pathlib import Path
import numpy as np
import torch
from PIL import Image

# Import Meta's official builder
try:
    from sam3.model_builder import build_sam3_image_model
except ImportError:
    build_sam3_image_model = None

_model = None


def load():
    global _model
    if _model is None:
        if build_sam3_image_model is None:
            raise ImportError("Official 'sam3' package is not installed. Run: pip install git+https://github.com/facebookresearch/sam3.1.git")
        
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Point to your downloaded checkpoint path inside _private or cache
        checkpoint_path = os.getenv("SAM_CHECKPOINT_PATH", r"D:\ai_cache\hub\facebook_sam3.1_multiplex.pt")
        
        _model = build_sam3_image_model(
            checkpoint_path=checkpoint_path,
            device=dev,
            eval_mode=True
        )
    return _model


def segment_exemplars(chip_rgb, boxes_xyxy, threshold=0.4, mask_threshold=0.5):
    """Positive example boxes -> matching hulls using official Meta runtime."""
    model = load()
    
    # Convert input chip for Meta's inference format
    image_pil = Image.fromarray(chip_rgb)
    
    with torch.no_grad():
        # Run inference using Meta's native prompt-box API
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