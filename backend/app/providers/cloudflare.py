"""Cloudflare Workers AI: text-to-image and inpainting.

POST https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}
Authorization: Bearer {token}

Response formats differ by model: SDXL-lightning returns raw PNG bytes
(Content-Type image/png); other models return JSON ``{"result": {"image": "<base64>"}}``.
Both are handled by looking at the Content-Type. See DECISIONS.md for the exact input
fields used for inpainting (``image_b64`` + ``mask`` as a byte array).
"""

from __future__ import annotations

import base64

import httpx

from app.config import Settings
from app.core.errors import ProviderError
from app.providers.base import ImageRequest, ImageResult, InpaintRequest
from app.providers.http import request_with_retries


def _decode_image_response(resp: httpx.Response, provider: str) -> bytes:
    ctype = resp.headers.get("Content-Type", "").lower()
    if ctype.startswith("image/"):
        return resp.content
    try:
        body = resp.json()
    except ValueError:
        raise ProviderError("Cloudflare returned an unknown response type", provider=provider)
    if body.get("success") is False:
        errs = body.get("errors") or []
        raise ProviderError(f"Cloudflare error: {errs[:1]}", provider=provider)
    result = body.get("result", body)
    img_b64 = None
    if isinstance(result, dict):
        img_b64 = result.get("image") or result.get("image_b64")
    elif isinstance(result, str):
        img_b64 = result
    if not img_b64:
        raise ProviderError("Cloudflare JSON response had no image", provider=provider)
    try:
        return base64.b64decode(img_b64)
    except ValueError:
        raise ProviderError("Cloudflare image was not valid base64", provider=provider)


class CloudflareBase:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        account = settings.cloudflare_account_id.get_secret_value()
        self.base_url = f"{settings.cloudflare_base_url.rstrip('/')}/accounts/{account}/ai/run/"
        self.max_retries = settings.max_retries
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.http_timeout_s,
            headers={"Authorization": f"Bearer {settings.cloudflare_api_token.get_secret_value()}"},
        )

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()


class CloudflareImageGen(CloudflareBase):
    name = "cloudflare"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(settings, client)
        self.model = settings.cf_image_model

    async def generate(self, req: ImageRequest) -> ImageResult:
        body: dict[str, object] = {
            "prompt": req.prompt,
            "width": req.width,
            "height": req.height,
        }
        if req.negative_prompt:
            body["negative_prompt"] = req.negative_prompt
        if req.seed is not None:
            body["seed"] = int(req.seed)
        if req.num_steps is not None:
            body["num_steps"] = int(req.num_steps)
        body.update(req.extra)
        resp = await request_with_retries(
            self._client,
            "POST",
            self.base_url + self.model,
            provider=self.name,
            max_retries=self.max_retries,
            json=body,
        )
        png = _decode_image_response(resp, self.name)
        return ImageResult(png=png, provider=self.name, model=self.model, seed=req.seed)


class CloudflareInpainter(CloudflareBase):
    name = "cloudflare"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(settings, client)
        self.model = settings.cf_inpaint_model

    async def inpaint(self, req: InpaintRequest) -> ImageResult:
        body: dict[str, object] = {
            "prompt": req.prompt,
            "image_b64": base64.b64encode(req.image_png).decode(),
            "mask": list(req.mask_png),  # PNG bytes as uint8 array (documented input form)
            "width": 512,
            "height": 512,
            "strength": req.strength,
        }
        if req.negative_prompt:
            body["negative_prompt"] = req.negative_prompt
        if req.seed is not None:
            body["seed"] = int(req.seed)
        resp = await request_with_retries(
            self._client,
            "POST",
            self.base_url + self.model,
            provider=self.name,
            max_retries=self.max_retries,
            json=body,
        )
        png = _decode_image_response(resp, self.name)
        return ImageResult(png=png, provider=self.name, model=self.model, seed=req.seed)
