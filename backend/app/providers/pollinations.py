"""Pollinations.ai image fallback (no API key).

GET {POLLINATIONS_BASE_URL}/{url-encoded prompt}?width=1024&height=1024&seed=N&nologo=true
"""

from __future__ import annotations

from urllib.parse import quote

import httpx

from app.config import Settings
from app.core.errors import ProviderError
from app.providers.base import ImageRequest, ImageResult
from app.providers.http import request_with_retries


class PollinationsImageGen:
    name = "pollinations"
    model = "pollinations-default"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = settings.pollinations_base_url.rstrip("/")
        self.max_retries = settings.max_retries
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=max(settings.http_timeout_s, 90), follow_redirects=True
        )

    async def generate(self, req: ImageRequest) -> ImageResult:
        prompt = req.prompt
        if req.negative_prompt:
            prompt = f"{prompt}. Avoid: {req.negative_prompt}"
        params = {"width": req.width, "height": req.height, "nologo": "true"}
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
        return ImageResult(png=resp.content, provider=self.name, model=self.model, seed=req.seed)

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()
