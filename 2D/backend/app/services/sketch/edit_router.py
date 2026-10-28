"""Edit router: turns an API edit body or a witness utterance into a resolved edit.

Amount words: "thoda / swalpa / a little" = 5%, "aur / innu / more" = 10%,
"bahut / tumba / a lot" = 15%. Unclear amounts -> ``needs_choice`` (three previews).
Locked regions -> friendly refusal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.core.errors import ValidationFailed
from app.providers.registry import ProviderRegistry
from app.services.interview import prompts
from app.services.sketch import overlays as overlay_service
from app.services.sketch.regions import (
    HANDLES,
    REGION_PARAMS,
    ROUTER_REGIONS,
    SLIDERS,
    regions_for_handles,
    slider_moves,
)

AMOUNTS = {"little": 0.05, "more": 0.10, "lot": 0.15}
AMOUNT_WORDS: list[tuple[tuple[str, ...], float]] = [
    (("bahut", "बहुत", "tumba", "ತುಂಬಾ", "a lot", "much", "very"), 0.15),
    (("aur", "और", "innu", "ಇನ್ನೂ", "more", "further"), 0.10),
    (
        (
            "thoda",
            "थोड़ा",
            "thodi",
            "थोड़ी",
            "swalpa",
            "ಸ್ವಲ್ಪ",
            "a little",
            "little",
            "a bit",
            "slightly",
        ),
        0.05,
    ),
]
PREVIEW_AMOUNTS = (0.05, 0.10, 0.15)

# Region (router vocabulary) -> lock feature(s) that protect it.
REGION_FEATURE = {
    "jaw": "jaw",
    "eyes": "eyes",
    "nose": "nose",
    "mouth": "mouth",
    "brows": "brows",
    "face_shape": "face_shape",
    "hair": "hair",
    "skin": "skin",
    "ears": "ears",
    "marks": "marks",
    "cheekbones": "face_shape",
}


def locked_message(region: str) -> str:
    return f"The {region.replace('_', ' ')} is locked. Unlock it first."


def parse_amount(text: str) -> float | None:
    t = f" {text.lower()} "
    for words, amt in AMOUNT_WORDS:
        for w in words:
            if f" {w} " in t or (len(w) > 4 and w in t):
                return amt
    return None


@dataclass
class ResolvedEdit:
    type: str  # geometric | overlay | inpaint | needs_choice | refused | unknown
    region: str = ""
    param: str = ""
    amount: float | None = None
    handle_moves: list[dict[str, float | str]] = field(default_factory=list)
    overlay_id: str = ""
    overlay_params: dict[str, Any] = field(default_factory=dict)
    prompt: str = ""
    symmetric: bool = True
    message: str = ""
    router_provider: str = ""
    spec: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "region": self.region,
            "param": self.param,
            "amount": self.amount,
            "handle_moves": self.handle_moves,
            "overlay_id": self.overlay_id,
            "overlay_params": self.overlay_params,
            "prompt": self.prompt,
            "symmetric": self.symmetric,
            "message": self.message,
            "router_provider": self.router_provider,
        }


def _check_lock(region: str, locks: set[str]) -> str | None:
    feat = REGION_FEATURE.get(region, region)
    if feat in locks:
        return locked_message(feat)
    return None


def resolve_structured(
    settings: Settings, edit: dict[str, Any], locks: set[str], utterance: str = ""
) -> ResolvedEdit:
    """Resolve an explicit ``edit`` object from the API body."""
    etype = str(edit.get("type") or "")
    region = str(edit.get("region") or "")
    symmetric = bool(edit.get("symmetric", True))
    moves = edit.get("handle_moves") or []
    if moves:
        for m in moves:
            if str(m.get("handle")) not in HANDLES:
                raise ValidationFailed(f"Unknown handle {m.get('handle')}")
        touched = regions_for_handles(moves)
        for r in touched:
            msg = _check_lock(r, locks)
            if msg:
                return ResolvedEdit("refused", region=r, message=msg)
        return ResolvedEdit(
            "geometric",
            region=region or ",".join(sorted(touched)),
            handle_moves=[
                {
                    "handle": str(m["handle"]),
                    "dx": float(m.get("dx", 0)),
                    "dy": float(m.get("dy", 0)),
                }
                for m in moves
            ],
            symmetric=symmetric,
        )
    if etype == "overlay" or edit.get("overlay_id"):
        oid = str(edit.get("overlay_id") or "")
        if not oid:
            raise ValidationFailed("overlay_id required for overlay edits")
        oregion = overlay_service.overlay_region(settings, oid)
        # Accessories and marks sit on top of the face and never move landmarks, so
        # feature locks do not block them (only the "marks" lock blocks mark overlays).
        if oregion == "marks" and "marks" in locks:
            return ResolvedEdit("refused", region=oregion, message=locked_message("marks"))
        return ResolvedEdit(
            "overlay",
            region=oregion,
            overlay_id=oid,
            overlay_params=dict(edit.get("overlay_params") or {}),
        )
    if etype == "inpaint":
        if not region:
            region = "hair"
        msg = _check_lock(region, locks)
        if msg:
            return ResolvedEdit("refused", region=region, message=msg)
        prompt = str(edit.get("prompt") or utterance or "").strip()
        if not prompt:
            raise ValidationFailed("prompt required for inpaint edits")
        return ResolvedEdit("inpaint", region=region, prompt=prompt)
    param = str(edit.get("param") or "")
    if param:
        if param not in SLIDERS:
            # allow short names like "width" with a region ("jaw" + "width" -> jaw_width)
            candidate = f"{region}_{param}"
            if candidate in SLIDERS:
                param = candidate
            else:
                raise ValidationFailed(f"Unknown slider param {param}")
        sregion = SLIDERS[param][0]
        msg = _check_lock(sregion, locks)
        if msg:
            return ResolvedEdit("refused", region=sregion, message=msg)
        amount = edit.get("amount")
        if amount is None:
            amount = parse_amount(utterance) if utterance else None
        if amount is None:
            return ResolvedEdit(
                "needs_choice",
                region=sregion,
                param=param,
                symmetric=symmetric,
                message="How much? Pick one of the three previews.",
            )
        amount = float(amount)
        if abs(amount) > 0.5:
            raise ValidationFailed("amount must be between -0.5 and 0.5 (fraction of face width)")
        return ResolvedEdit(
            "geometric",
            region=sregion,
            param=param,
            amount=amount,
            handle_moves=slider_moves(param, amount),
            symmetric=symmetric,
        )
    if etype == "geometric" and region:
        return ResolvedEdit(
            "unknown", region=region, message="A geometric edit needs a param or handle_moves."
        )
    raise ValidationFailed("edit must contain handle_moves, param, overlay_id or an inpaint prompt")


async def route_utterance(
    registry: ProviderRegistry,
    settings: Settings,
    utterance_original: str,
    utterance_en: str,
    language: str,
    locks: set[str],
) -> ResolvedEdit:
    """Use the LLM (or mock rules) to turn an utterance into a resolved edit."""
    cat = overlay_service.load_catalog(str(settings.assets_path / "overlays"))
    res = await registry.llm_json(
        prompts.route_edit(
            utterance_original,
            utterance_en,
            language,
            sorted(locks),
            list(ROUTER_REGIONS),
            REGION_PARAMS,
            sorted(cat.keys()),
        )
    )
    spec = res.data
    region = str(spec.get("region") or "")
    etype = str(spec.get("type") or "none")
    text = f"{utterance_original} {utterance_en}"
    if etype == "none":
        msg = spec.get("message") or "Sorry, I could not understand that edit."
        kind = "refused" if "locked" in str(msg).lower() else "unknown"
        return ResolvedEdit(
            kind, region=region, message=str(msg), router_provider=res.provider, spec=spec
        )
    if etype == "overlay":
        edit = {
            "type": "overlay",
            "overlay_id": spec.get("overlay_id"),
            "overlay_params": spec.get("overlay_params") or {},
        }
        out = resolve_structured(settings, edit, locks, text)
    elif etype == "inpaint":
        out = resolve_structured(
            settings,
            {
                "type": "inpaint",
                "region": region or "hair",
                "prompt": spec.get("prompt") or utterance_en or utterance_original,
            },
            locks,
            text,
        )
    else:
        amount = spec.get("amount")
        if amount is None:
            amount = parse_amount(text)
        direction = int(spec.get("direction") or 1)
        edit = {
            "type": "geometric",
            "region": region,
            "param": spec.get("param"),
            "amount": None if amount is None else float(amount) * (1 if direction >= 0 else -1),
            "symmetric": bool(spec.get("symmetric", True)),
        }
        if not edit["param"]:
            return ResolvedEdit(
                "unknown",
                region=region,
                router_provider=res.provider,
                message="I understood the region but not the change.",
                spec=spec,
            )
        out = resolve_structured(settings, edit, locks, text)
    out.router_provider = res.provider
    out.spec = spec
    return out
