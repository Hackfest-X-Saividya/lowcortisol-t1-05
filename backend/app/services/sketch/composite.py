"""Compositing with the stability guarantee: pixels where mask == 0 equal the old image."""

from __future__ import annotations

import cv2
import numpy as np


def composite(
    old: np.ndarray, new: np.ndarray, mask: np.ndarray, seamless: bool = True
) -> np.ndarray:
    """``final = mask * new + (1 - mask) * old`` in float, then ``cv2.seamlessClone`` for the
    seam. Pixels with ``mask == 0`` are forced back to ``old`` exactly."""
    if old.shape != new.shape:
        new = cv2.resize(new, (old.shape[1], old.shape[0]), interpolation=cv2.INTER_LINEAR)
    m: np.ndarray = np.clip(mask.astype(np.float32), 0.0, 1.0)
    if m.shape[:2] != old.shape[:2]:
        m = cv2.resize(m, (old.shape[1], old.shape[0]), interpolation=cv2.INTER_LINEAR)
    m3 = m[:, :, None]
    blended = m3 * new.astype(np.float32) + (1.0 - m3) * old.astype(np.float32)
    result: np.ndarray = np.clip(blended, 0, 255).astype(np.uint8)
    zero = m <= 0.0
    if seamless:
        binary = (m > 0.02).astype(np.uint8) * 255
        ys, xs = np.nonzero(binary)
        if xs.size > 50:
            x0, x1, y0, y1 = int(np.min(xs)), int(np.max(xs)), int(np.min(ys)), int(np.max(ys))
            # seamlessClone needs the mask strictly inside the image
            inside = x0 > 1 and y0 > 1 and x1 < old.shape[1] - 2 and y1 < old.shape[0] - 2
            if inside:
                center = (int((x0 + x1) // 2), int((y0 + y1) // 2))
                try:
                    cloned = cv2.seamlessClone(result, old, binary, center, cv2.NORMAL_CLONE)
                    if cloned.shape == old.shape:
                        result = cloned
                except cv2.error:
                    pass
    result[zero] = old[zero]
    return result
