"""Optional cloud inpainting for hair, skin and texture edits.

Crop the mask's bounding box plus 15% padding, resize to 512x512, call the provider,
resize the result back, paste it into the full image and composite through the mask.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.providers.base import InpaintRequest
from app.providers.registry import ProviderRegistry
from app.services.sketch.composite import composite
from app.services.sketch.masks import mask_bbox
from app.services.sketch.render import decode_png, encode_png

NEGATIVE = "smiling, tilted head, profile, text, watermark, multiple people, cartoon, drawing"
INPAINT_PX = 512


async def inpaint_region(
    registry: ProviderRegistry,
    img: np.ndarray,
    mask: np.ndarray,
    prompt: str,
    seed: int | None,
    pad_frac: float = 0.15,
    negative_prompt: str = NEGATIVE,
) -> tuple[np.ndarray, str, str]:
    """Return (new image, provider, model).

    ``pad_frac`` widens the crop around the mask so the model sees surrounding face context
    (a tight strip like the eyes otherwise gets filled with blank skin).
    """
    x0, y0, x1, y1 = mask_bbox(mask, pad_frac=pad_frac)
    crop = img[y0:y1, x0:x1]
    mcrop = mask[y0:y1, x0:x1]
    ch, cw = crop.shape[:2]
    crop_s = cv2.resize(crop, (INPAINT_PX, INPAINT_PX), interpolation=cv2.INTER_AREA)
    mask_s = cv2.resize(
        (mcrop > 0.5).astype(np.uint8) * 255,
        (INPAINT_PX, INPAINT_PX),
        interpolation=cv2.INTER_NEAREST,
    )
    ok, mbuf = cv2.imencode(".png", mask_s)
    res = await registry.inpaint(
        InpaintRequest(
            image_png=encode_png(crop_s),
            mask_png=mbuf.tobytes(),
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
        )
    )
    out_s = decode_png(res.png)
    out_crop = cv2.resize(out_s, (cw, ch), interpolation=cv2.INTER_LANCZOS4)
    pasted = img.copy()
    pasted[y0:y1, x0:x1] = out_crop
    final = composite(img, pasted, mask, seamless=True)
    return final, res.provider, res.model
