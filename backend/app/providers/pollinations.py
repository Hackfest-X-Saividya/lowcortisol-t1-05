"""Pollinations.ai image fallback (no API key).

GET {POLLINATIONS_BASE_URL}/{url-encoded prompt}?width=1024&height=1024&seed=N&nologo=true
"""

from __future__ import annotations

from urllib.parse import quote

import cv2
import httpx
import numpy as np

from app.config import Settings
from app.core.errors import ProviderError
from app.providers.base import ImageRequest, ImageResult
from app.providers.http import request_with_retries


def strip_logo(data: bytes) -> bytes:
    """Anonymous requests get a small logo in the bottom-right corner (``nologo`` is ignored):
    crop the bottom 7% (and the same from the sides, to stay square) and return PNG."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return data
    h, w = img.shape[:2]
    cut = int(round(h * 0.07))
    side = cut // 2
    out = img[: h - cut, side : w - (cut - side)]
    ok, buf = cv2.imencode(".png", out)
    return buf.tobytes() if ok else data


class PollinationsImageGen:
    name = "pollinations"
    model = "pollinations-flux"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = settings.pollinations_base_url.rstrip("/")
        self.max_retries = settings.max_retries
        self.model_param = settings.pollinations_model
        self.model = f"pollinations-{self.model_param}"
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.pollinations_timeout_s, follow_redirects=True
        )

    async def generate(self, req: ImageRequest) -> ImageResult:
        # no negative prompt: the model reads "avoid glasses" as "glasses"
        prompt = req.prompt
        params: dict[str, str | int] = {
            "width": req.width,
            "height": req.height,
            "nologo": "true",
            "model": self.model_param,
        }
        if req.seed is not None:
            params["seed"] = int(req.seed)
        url = f"{self.base_url}/{quote(prompt, safe='')}"
        resp = await request_with_retries(
            self._client,
            "GET",
            url,
            provider=self.name,
            max_retries=self.max_retries,
            params=params,
        )
        if not resp.headers.get("Content-Type", "").lower().startswith("image/"):
            raise ProviderError("Pollinations did not return an image", provider=self.name)
        png = strip_logo(resp.content)
        return ImageResult(png=png, provider=self.name, model=self.model, seed=req.seed)

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()
