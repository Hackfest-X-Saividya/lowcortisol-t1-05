"""
Convert MakeHuman textures into the WebP files the app loads.

Usage: python mh_textures.py <mpfb_data_dir> <build_out_dir>
Reads <build_out_dir>/manifest.json (written by mh_build.py) to know which
asset each exported model came from, and writes textures next to the models:

  models/skins/<skin>.webp        18 photo skins (age x sex x ancestry), 1024 px
  models/facial/eye_base.webp     eye texture with a neutral-grey iris
  models/facial/eye_iris_mask.webp  where the iris is (the app tints it)
  <model>.webp                    strand textures for hair, beards, brows, lashes:
                                  brightness only (the app multiplies in the
                                  colour picked by the user) + the original alpha
"""
import json
import os
import re
import sys

import numpy as np
from PIL import Image, ImageFilter

DATA, OUT = sys.argv[1], sys.argv[2]
manifest = json.load(open(os.path.join(OUT, "manifest.json")))


def save_webp(img, rel, quality=88):
    path = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "WEBP", quality=quality, method=6)
    print(f"  {rel:42s} {img.size[0]}x{img.size[1]} {os.path.getsize(path) // 1024} KB")


def mhmat_texture(asset_dir):
    """Path of the diffuse texture named in an asset's .mhmat, or None."""
    d = os.path.join(DATA, asset_dir)
    for f in os.listdir(d):
        if f.endswith(".mhmat"):
            for line in open(os.path.join(d, f), encoding="utf-8", errors="ignore"):
                m = re.match(r"\s*diffuseTexture\s+(\S+)", line)
                if m:
                    p = os.path.join(d, m.group(1))
                    return p if os.path.exists(p) else os.path.join(d, os.path.basename(m.group(1)))
    return None


def luminance(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def strand_texture(src, max_size=1024, flat=False, lower_fade=None):
    """Brightness-only RGBA: the app tints it with the chosen hair colour."""
    im = Image.open(src).convert("RGBA")
    if max(im.size) > max_size:
        im = im.resize((max_size, max_size * im.size[1] // im.size[0]), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32)
    alpha = a[..., 3]
    if flat:
        gray = np.full(alpha.shape, 255.0)
        alpha = (alpha / 255.0) ** 1.4 * 255.0           # finer strands
        if lower_fade:
            # eyelashes01 packs the lower lashes in the bottom half; real lower lashes are sparse
            alpha[alpha.shape[0] // 2:] *= lower_fade
    else:
        lum = luminance(a[..., :3])
        ref = np.percentile(lum[alpha > 128], 95) if (alpha > 128).any() else 255.0
        gray = np.clip(lum / max(ref, 1.0), 0, 1) ** 0.8 * 255.0
    out = np.dstack([gray, gray, gray, alpha]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


print("Skins")
skins = []
for name in sorted(os.listdir(os.path.join(DATA, "skins"))):
    if not re.match(r"(young|middleage|old)_(african|asian|caucasian)_(male|female)$", name):
        continue
    d = os.path.join(DATA, "skins", name)
    png = [f for f in os.listdir(d) if f.endswith(".png")][0]
    img = Image.open(os.path.join(d, png)).convert("RGB").resize((1024, 1024), Image.LANCZOS)
    # MakeHuman's darker skins are strongly red; pull saturation toward natural skin
    desat = 0.30 if "african" in name else 0.12
    arr = np.asarray(img).astype(np.float32)
    gray = luminance(arr)[..., None]
    img = Image.fromarray(np.clip(arr + (gray - arr) * desat, 0, 255).astype(np.uint8))
    save_webp(img, f"models/skins/{name}.webp", quality=86)
    skins.append(name)
assert len(skins) == 18, skins

print("Eyes")
eyes = os.path.join(DATA, "eyes", "materials")
brown = np.asarray(Image.open(os.path.join(eyes, "brown_eye.png")).convert("RGB")).astype(np.float32)
blue = np.asarray(Image.open(os.path.join(eyes, "blue_eye.png")).convert("RGB")).astype(np.float32)
diff = np.linalg.norm(brown - blue, axis=2)
mask = Image.fromarray((np.clip(diff / 40.0, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))
m = np.asarray(mask).astype(np.float32) / 255.0
m = np.clip((m - 0.45) / 0.35, 0, 1)          # tight edge: keep the white untouched outside the iris
lum = luminance(brown)
# The blue reference iris is slightly larger; only keep pixels that are iris-dark in the brown eye
m = m * np.clip((125.0 - lum) / 30.0, 0, 1)
m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1))).astype(np.float32) / 255.0
mask = Image.fromarray((m * 255).astype(np.uint8))
# Median iris brightness -> ~170 so the tint keeps fibre detail without going dark
iris_med = np.median(lum[m > 0.9])
gray = np.clip(lum / max(iris_med, 1.0) * 170.0, 0, 200)
# Darker limbal ring where the iris meets the white (mask edge), as in real eyes
edge = np.clip(1.0 - np.abs(m - 0.5) * 2.0, 0, 1)
gray = gray * (1.0 - 0.55 * edge)
base = brown * (1 - m[..., None]) + np.dstack([gray] * 3) * m[..., None]
save_webp(Image.fromarray(base.astype(np.uint8)), "models/facial/eye_base.webp", quality=90)
save_webp(mask.convert("L"), "models/facial/eye_iris_mask.webp", quality=90)

print("Strands (hair, beards, brows, lashes)")
for rel, info in manifest["files"].items():
    asset_dir = info.get("asset_dir")
    if not asset_dir or not rel.endswith(".glb") or asset_dir.startswith("eyes/"):
        continue
    src = mhmat_texture(asset_dir)
    if not src:
        print(f"  {rel}: no diffuse texture in {asset_dir}, left untextured")
        continue
    flat = asset_dir.startswith(("eyebrows/", "eyelashes/"))
    fade = 0.35 if asset_dir.startswith("eyelashes/") else None
    save_webp(strand_texture(src, flat=flat, lower_fade=fade), rel[:-4] + ".webp", quality=85)
