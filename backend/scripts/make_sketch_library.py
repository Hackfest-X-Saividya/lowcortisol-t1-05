"""Build the forensic sketch library used for the instant first drawing of a live sketch.

Every entry is a UNIQUE hand-drawn-style graphite sketch generated from a text description
(no real person, and none of the reference images is used as input). The descriptions mix
features the way a witness gives them, e.g. "long face, wavy hair, skinny, wrinkles". The
live sketch starts from the entry whose description best matches what the witness has said
(see ``app/services/interview/live_render.py``), then is replaced by a sketch generated from
the witness's own description.

    python scripts/make_sketch_library.py              # missing entries only
    python scripts/make_sketch_library.py --force      # regenerate all
    python scripts/make_sketch_library.py --landmarks  # only write missing landmark files

Output: ``assets/sketch_library/sketch_XX.jpg`` + ``catalog.json`` (+ ``sketch_XX.lm.json``).
Pollinations' free tier allows one image every 45 s per IP, so a full run takes ~25 minutes.
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

OUT = Path(__file__).resolve().parents[1] / "assets" / "sketch_library"

STYLE = (
    "hand-drawn forensic police composite sketch, graphite pencil drawing on white paper, "
    "visible pencil strokes and cross-hatching, detailed realistic face, frontal view, eyes "
    "looking straight ahead, neutral expression, mouth closed, head and shoulders, plain "
    "white background, black and white, of an Indian "
)

# key: (description used in the prompt, attributes used for matching)
ENTRIES: list[dict[str, object]] = [
    {"d": "man about 25, long narrow face, messy wavy hair, skinny, light stubble",
     "a": {"gender": "male", "age": "young", "face": "long narrow thin", "hair": "wavy messy medium", "facial_hair": "stubble", "build": "thin skinny"}},
    {"d": "man about 30, oval face, short side-parted hair, clean-shaven, small mole on left cheek",
     "a": {"gender": "male", "age": "young", "face": "oval", "hair": "short side parted straight", "facial_hair": "clean", "marks": "mole"}},
    {"d": "man about 35, broad square face, short curly hair, full thick beard, heavy eyebrows",
     "a": {"gender": "male", "age": "middle", "face": "broad square wide", "hair": "short curly", "facial_hair": "full beard thick", "brows": "thick heavy"}},
    {"d": "man about 40, round chubby face, double chin, receding hairline, thick moustache",
     "a": {"gender": "male", "age": "middle", "face": "round chubby fat", "hair": "receding short", "facial_hair": "thick moustache", "build": "heavy fat stout"}},
    {"d": "man about 28, thin face, bowl cut with fringe, big ears, thin moustache",
     "a": {"gender": "male", "age": "young", "face": "thin narrow small", "hair": "bowl cut fringe straight", "facial_hair": "thin moustache", "ears": "big large"}},
    {"d": "man about 45, long face, short cropped grey hair, deep forehead wrinkles, stubble, sunken cheeks",
     "a": {"gender": "male", "age": "middle older", "face": "long thin", "hair": "short cropped grey", "facial_hair": "stubble", "marks": "wrinkles", "build": "thin"}},
    {"d": "man about 65, bald head with grey hair at the sides, heavy wrinkles, grey stubble, drooping eyes",
     "a": {"gender": "male", "age": "older old", "face": "oval wrinkled", "hair": "bald balding grey", "facial_hair": "grey stubble", "marks": "wrinkles"}},
    {"d": "man about 30, angular face, wearing a baseball cap, goatee beard and thin moustache",
     "a": {"gender": "male", "age": "young", "face": "angular sharp", "hair": "short", "facial_hair": "goatee moustache", "headwear": "cap baseball cap"}},
    {"d": "man about 35, shaved bald head, thick handlebar moustache, small scar under right eye, stud earring",
     "a": {"gender": "male", "age": "middle", "face": "oval", "hair": "bald shaved", "facial_hair": "thick moustache", "marks": "scar", "other": "earring"}},
    {"d": "man about 40, square face, short straight hair, rectangular spectacles, trimmed beard",
     "a": {"gender": "male", "age": "middle", "face": "square", "hair": "short straight", "facial_hair": "short beard trimmed", "eyewear": "spectacles glasses square"}},
    {"d": "man about 50, Sikh turban, long full grey beard, broad face, thick eyebrows",
     "a": {"gender": "male", "age": "older middle", "face": "broad wide", "hair": "covered", "facial_hair": "long full beard grey", "headwear": "turban pagdi", "brows": "thick"}},
    {"d": "man about 22, slim face, curly shoulder-length hair, acne marks on cheeks, clean-shaven",
     "a": {"gender": "male", "age": "young", "face": "slim thin", "hair": "curly long shoulder", "facial_hair": "clean", "marks": "acne pockmarks spots"}},
    {"d": "man about 38, heavy-set, round face, short spiky hair, thick neck, light moustache",
     "a": {"gender": "male", "age": "middle", "face": "round fat", "hair": "short spiky", "facial_hair": "moustache", "build": "heavy fat stout"}},
    {"d": "man about 33, long face, long wavy hair to the shoulders, long full beard",
     "a": {"gender": "male", "age": "middle young", "face": "long", "hair": "long wavy", "facial_hair": "long full beard"}},
    {"d": "man about 27, oval face, short hair, woollen beanie cap, stubble, small eyes",
     "a": {"gender": "male", "age": "young", "face": "oval", "hair": "short", "facial_hair": "stubble", "headwear": "beanie woollen cap monkey cap", "eyes": "small"}},
    {"d": "man about 55, oval face, thinning combed-back hair, round spectacles, clean-shaven, wrinkles",
     "a": {"gender": "male", "age": "older", "face": "oval", "hair": "thinning combed back", "facial_hair": "clean", "eyewear": "round spectacles glasses", "marks": "wrinkles"}},
    {"d": "young woman about 22, oval face, long straight hair with centre parting, small nose",
     "a": {"gender": "female", "age": "young", "face": "oval", "hair": "long straight centre parting", "nose": "small"}},
    {"d": "woman about 30, round face, curly shoulder-length hair with fringe, mole near the lip",
     "a": {"gender": "female", "age": "young", "face": "round", "hair": "curly shoulder fringe", "marks": "mole"}},
    {"d": "woman about 25, oval face, headscarf covering the hair, thick eyebrows",
     "a": {"gender": "female", "age": "young", "face": "oval", "hair": "covered", "headwear": "headscarf hijab scarf dupatta", "brows": "thick"}},
    {"d": "woman about 40, long face, hair tied in a bun, small bindi, thin lips",
     "a": {"gender": "female", "age": "middle", "face": "long", "hair": "bun tied back", "marks": "bindi", "mouth": "thin lips"}},
    {"d": "woman about 60, wrinkled face, grey hair tied back, spectacles, sunken cheeks",
     "a": {"gender": "female", "age": "older old", "face": "wrinkled thin", "hair": "grey tied back", "eyewear": "spectacles glasses", "marks": "wrinkles"}},
    {"d": "woman about 35, square face, short bob cut hair, big eyes, small scar on chin",
     "a": {"gender": "female", "age": "middle", "face": "square", "hair": "short bob cut", "eyes": "big large", "marks": "scar"}},
    {"d": "man about 30, face partly covered by a cloth over the nose and mouth, short hair, thick eyebrows",
     "a": {"gender": "male", "age": "young middle", "face": "covered", "hair": "short", "headwear": "", "face_cover": "cloth mask covered handkerchief", "brows": "thick"}},
    {"d": "man about 45, wearing a motorcycle helmet with open visor, moustache, broad face",
     "a": {"gender": "male", "age": "middle", "face": "broad", "hair": "covered", "facial_hair": "moustache", "headwear": "helmet"}},
]  # fmt: skip


def prompt_for(desc: str) -> str:
    return STYLE + desc


async def main(force: bool) -> None:
    settings = get_settings()
    gens: list[object] = [PollinationsImageGen(settings)]
    if settings.cloudflare_configured:
        gens.insert(0, CloudflareImageGen(settings))
    OUT.mkdir(parents=True, exist_ok=True)
    cat_path = OUT / "catalog.json"
    catalog = json.loads(cat_path.read_text(encoding="utf-8")) if cat_path.exists() else {}
    for i, e in enumerate(ENTRIES, start=1):
        name = f"sketch_{i:02d}.jpg"
        path = OUT / name
        catalog[name] = {"description": e["d"], "attributes": e["a"]}
        cat_path.write_text(json.dumps(catalog, indent=1, ensure_ascii=False), encoding="utf-8")
        if path.exists() and not force:
            continue
        for attempt in range(4):
            t = time.time()
            req = ImageRequest(prompt=prompt_for(str(e["d"])), width=768, height=768,
                               seed=4000 + i * 7 + attempt)  # fmt: skip
            res = None
            for gen in gens:
                try:
                    res = await gen.generate(req)  # type: ignore[attr-defined]
                    break
                except Exception as exc:  # noqa: BLE001
                    print(name, getattr(gen, "name", "?"), "failed", type(exc).__name__, flush=True)
            if res is None:
                await asyncio.sleep(46)
                continue
            img = cv2.imdecode(np.frombuffer(res.png, np.uint8), cv2.IMREAD_COLOR)
            img = cv2.resize(img, (768, 768), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            catalog[name]["provider"] = res.provider
            cat_path.write_text(json.dumps(catalog, indent=1, ensure_ascii=False), encoding="utf-8")
            print(name, "ok", res.provider, round(time.time() - t, 1), flush=True)
            await asyncio.sleep(46)  # Pollinations free tier: one image per 45 s
            break


def write_landmarks() -> None:
    from app.services.sketch.landmarks import Landmarker, landmarks_to_json

    lmk = Landmarker(get_settings())
    for path in sorted(OUT.glob("sketch_*.jpg")):
        out = path.with_suffix(".lm.json")
        if out.exists():
            continue
        img = cv2.resize(cv2.imread(str(path)), (1024, 1024), interpolation=cv2.INTER_CUBIC)
        faces = lmk.detect(img)
        if faces:
            out.write_text(json.dumps(landmarks_to_json(faces[0])), encoding="utf-8")
            print(path.stem, "landmarks ok", flush=True)
        else:
            print(path.stem, "no face found (warps disabled for this entry)", flush=True)


if __name__ == "__main__":
    if "--landmarks" not in sys.argv:
        asyncio.run(main("--force" in sys.argv))
    write_landmarks()
