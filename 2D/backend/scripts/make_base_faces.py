"""Build the base-face library used for the instant first drawing of a live sketch.

Each entry is an AI-generated, frontal, neutral portrait (no real person). The live sketch
starts from the closest entry (gender, age, facial hair) the moment the witness describes
the person, and is replaced by a portrait generated from the full description when the
image provider answers. Run once (or again to refresh):

    python scripts/make_base_faces.py            # missing entries only
    python scripts/make_base_faces.py --force    # regenerate all
    python scripts/make_base_faces.py --landmarks  # only (re)write missing landmark files
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.providers.base import ImageRequest  # noqa: E402
from app.providers.cloudflare import CloudflareImageGen  # noqa: E402
from app.providers.pollinations import PollinationsImageGen  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "assets" / "base_faces"
AGES = {
    "young": "about 25 years old",
    "middle": "about 40 years old",
    "older": "about 60 years old",
}
HAIR = {
    "clean": "clean-shaven",
    "moustache": "with a moustache",
    "beard": "with a short full beard",
}


def entries() -> list[dict[str, str]]:
    out = []
    for age, age_txt in AGES.items():
        for hair, hair_txt in HAIR.items():
            out.append(
                {
                    "key": f"male_{age}_{hair}",
                    "gender": "male",
                    "age": age,
                    "facial_hair": hair,
                    "prompt": f"man {age_txt}, short black hair, {hair_txt}",
                }
            )
        out.append(
            {
                "key": f"female_{age}_clean",
                "gender": "female",
                "age": age,
                "facial_hair": "clean",
                "prompt": f"woman {age_txt}, black hair tied back",
            }
        )
    return out


def prompt_for(desc: str) -> str:
    return (
        f"realistic passport photograph, sharp focus, of an Indian {desc}, medium brown skin, "
        "front view, face and eyes looking directly into the camera, symmetrical, neutral "
        "expression, mouth closed, bare face, plain shirt, head and shoulders, plain light grey "
        "background, even studio lighting, natural skin texture"
    )


async def main(force: bool) -> None:
    settings = get_settings()
    gens = [PollinationsImageGen(settings)]
    if settings.cloudflare_configured:
        gens.insert(0, CloudflareImageGen(settings))
    index_path = OUT / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    for e in entries():
        path = OUT / f"{e['key']}.jpg"
        if path.exists() and not force:
            continue
        for attempt in range(3):
            t = time.time()
            req = ImageRequest(
                prompt=prompt_for(e["prompt"]),
                negative_prompt="smiling, glasses, jewellery, text, watermark, cartoon, painting",
                width=768,
                height=768,
                seed=1000 + attempt,
            )
            res = None
            for gen in gens:
                try:
                    res = await gen.generate(req)
                    break
                except Exception as exc:  # noqa: BLE001
                    print(e["key"], gen.name, "failed", type(exc).__name__, flush=True)
            if res is None:
                await asyncio.sleep(20)
                continue
            img = cv2.imdecode(np.frombuffer(res.png, np.uint8), cv2.IMREAD_COLOR)
            img = cv2.resize(img, (768, 768), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
            index[e["key"]] = {k: e[k] for k in ("gender", "age", "facial_hair")} | {
                "provider": res.provider,
                "model": res.model,
            }
            index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
            print(e["key"], "ok", res.provider, round(time.time() - t, 1), flush=True)
            await asyncio.sleep(4)
            break


def write_landmarks() -> None:
    """``<key>.lm.json`` next to each face (normalized MediaPipe landmarks at 1024 px), so the
    live sketch never has to run detection on a library face."""
    from app.services.sketch.landmarks import Landmarker, landmarks_to_json

    lmk = Landmarker(get_settings())
    for path in sorted(OUT.glob("*.jpg")):
        out = path.with_suffix(".lm.json")
        if out.exists():
            continue
        img = cv2.resize(cv2.imread(str(path)), (1024, 1024), interpolation=cv2.INTER_CUBIC)
        faces = lmk.detect(img)
        if faces:
            out.write_text(json.dumps(landmarks_to_json(faces[0])), encoding="utf-8")
            print(path.stem, "landmarks ok", flush=True)
        else:
            print(path.stem, "NO FACE FOUND - regenerate this one with --force", flush=True)


if __name__ == "__main__":
    if "--landmarks" not in sys.argv:
        asyncio.run(main("--force" in sys.argv))
    write_landmarks()
