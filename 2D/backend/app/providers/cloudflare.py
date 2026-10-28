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


def _is_flux2(model: str) -> bool:
    """FLUX.2 [dev] / [klein] take multipart form data (even for a prompt-only call)."""
    return "flux-2" in model


def _form(fields: dict[str, object], image_png: bytes | None = None) -> dict[str, tuple]:  # type: ignore[type-arg]
    """Multipart fields for FLUX.2. ``input_image_0`` is an optional reference image."""
    files: dict[str, tuple] = {k: (None, str(v)) for k, v in fields.items()}  # type: ignore[type-arg]
    if image_png is not None:
        files["input_image_0"] = ("reference.png", image_png, "image/png")
    return files


def _clamp_side(px: int) -> int:
    return max(256, min(1920, int(px)))


def image_body(model: str, req: ImageRequest) -> dict[str, object]:
    """Request body for a Workers AI text-to-image model (input names differ per model)."""
    body: dict[str, object] = {"prompt": req.prompt}
    if "leonardo" in model:
        # Leonardo Lucid Origin / Phoenix: realistic portraits; width/height/seed/negative ok
        body.update({"width": req.width, "height": req.height})
        steps = req.num_steps or 8
        body["steps" if "lucid" in model else "num_steps"] = int(steps)
        if req.negative_prompt:
            body["negative_prompt"] = req.negative_prompt
        if req.seed is not None:
            body["seed"] = int(req.seed)
    elif "flux" in model:
        body["steps"] = int(req.num_steps or 4)  # flux-1-schnell takes no seed / size
    else:
        body.update({"width": req.width, "height": req.height})
        if req.negative_prompt:
            body["negative_prompt"] = req.negative_prompt
        if req.seed is not None:
            body["seed"] = int(req.seed)
        if req.num_steps is not None:
            body["num_steps"] = int(req.num_steps)
    body.update(req.extra)
    return body


class CloudflareImageGen(CloudflareBase):
    """Text-to-image on Workers AI. Tries CF_IMAGE_MODEL, then CF_IMAGE_FALLBACK_MODEL."""

    name = "cloudflare"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(settings, client)
        self.model = settings.cf_image_model
        self.models = [m for m in (settings.cf_image_model, settings.cf_image_fallback_model) if m]

    async def generate(self, req: ImageRequest) -> ImageResult:
        last: ProviderError | None = None
        for model in self.models:
            try:
                if _is_flux2(model):
                    kwargs: dict[str, object] = {
                        "files": _form(
                            {
                                "prompt": req.prompt,
                                "width": _clamp_side(req.width),
                                "height": _clamp_side(req.height),
                            }
                        )
                    }
                else:
                    kwargs = {"json": image_body(model, req)}
                resp = await request_with_retries(
                    self._client,
                    "POST",
                    self.base_url + model,
                    provider=self.name,
                    max_retries=self.max_retries,
                    **kwargs,
                )
                png = _decode_image_response(resp, self.name)
                return ImageResult(png=png, provider=self.name, model=model, seed=req.seed)
            except ProviderError as exc:
                last = exc
                if (exc.details or {}).get("daily_quota"):
                    break  # one allowance for the whole account: the next model fails too
        assert last is not None
        raise last


class CloudflareInpainter(CloudflareBase):
    name = "cloudflare"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(settings, client)
        self.model = settings.cf_inpaint_model

    async def inpaint(self, req: InpaintRequest) -> ImageResult:
        if _is_flux2(self.model):
            # Reference-image edit: FLUX.2 keeps the person's identity from ``input_image_0``.
            # It has no mask input; the caller composites the result back through its mask,
            # so only the masked region of the new image is ever used.
            instruction = (
                "Edit the reference photo of a person. Target appearance: "
                f"{req.prompt}. Keep the same person, face identity, pose, camera framing, "
                "lighting and background exactly as in the reference. Change only what is "
                "described; everything else must stay identical."
            )
            resp = await request_with_retries(
                self._client,
                "POST",
                self.base_url + self.model,
                provider=self.name,
                max_retries=self.max_retries,
                files=_form(
                    {
                        "prompt": instruction,
                        "width": _clamp_side(req.width),
                        "height": _clamp_side(req.height),
                    },
                    req.image_png,
                ),
            )
            png = _decode_image_response(resp, self.name)
            return ImageResult(png=png, provider=self.name, model=self.model, seed=req.seed)
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
