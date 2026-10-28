"""
Compute app calibration for the MakeHuman-built assets in <out_dir>.

Usage: python fit.py <out_dir> <OBJMorpher.js>
Writes <out_dir>/calibration.json and rewrites Glasses/*.obj with split lenses.
All formulas mirror the app code (see comments for file references).
"""
import json, os, re, sys
import numpy as np
import trimesh

OUT, MORPHER_JS = sys.argv[1], sys.argv[2]
P = lambda *a: os.path.join(OUT, *a)


def verts(path):
    return np.asarray(trimesh.load(path, force='mesh', process=False).vertices)


def bbox(v):
    mn, mx = v.min(0), v.max(0)
    return {"min": mn, "max": mx, "center": (mn + mx) / 2, "size": mx - mn}


head_v = verts(P("models/base/head.glb"))
H = bbox(head_v)
W = H["size"][0]
cal = {"head_bbox": {k: np.round(v, 4).tolist() for k, v in H.items()}}

# ─── Facial profile anchors (centre line, front-most z per height) ─────────
mid = head_v[np.abs(head_v[:, 0]) < 0.03]
ys = np.arange(H["min"][1] + 0.1, H["max"][1], 0.01)
prof = []
for y in ys:
    band = mid[np.abs(mid[:, 1] - y) < 0.012]
    prof.append(band[:, 2].max() if len(band) else np.nan)
prof = np.array(prof)
ok = ~np.isnan(prof)
prof = np.interp(ys, ys[ok], prof[ok])
prof = np.convolve(prof, np.ones(3) / 3, mode='same')

i_tip = int(np.argmax(np.where(ys < 0.2, prof, -9)))     # nose tip: front-most point below the eyes


def next_extremum(i, kind):
    """Walk downwards (decreasing y) from index i to the next local min/max of the profile."""
    j = i - 1
    while j > 1:
        a, b, c = prof[j + 1], prof[j], prof[j - 1]
        if kind == 'min' and b <= a and b <= c:
            return j
        if kind == 'max' and b >= a and b >= c:
            return j
        j -= 1
    return j


i_sub = next_extremum(i_tip - 2, 'min')       # subnasale
i_ulip = next_extremum(i_sub - 1, 'max')      # upper lip
i_stom = next_extremum(i_ulip - 1, 'min')     # mouth slit
i_llip = next_extremum(i_stom - 1, 'max')     # lower lip
i_fold = next_extremum(i_llip - 1, 'min')     # labiomental fold
i_chin = next_extremum(i_fold - 1, 'max')     # chin
anat = {n: float(ys[i]) for n, i in [("nose_tip", i_tip), ("subnasale", i_sub), ("upper_lip", i_ulip),
                                     ("mouth", i_stom), ("lower_lip", i_llip), ("chin", i_chin)]}

man = json.load(open(P("manifest.json")))
eyeL = np.array(man["files"]["models/facial/EyeLeft.glb"]["center"])
eye_r = man["files"]["models/facial/EyeLeft.glb"]["radius"]
brow = bbox(verts(P("models/facial/eyebrows.glb")))
anat["eye"] = float(eyeL[1])
anat["brow"] = float(brow["center"][1])
anat["top"] = float(H["max"][1])
cal["anatomy_y"] = {k: round(v, 4) for k, v in anat.items()}
print("ANATOMY", cal["anatomy_y"])

# ─── Landmark remap: old table → new head ─────────────────────────────────
OLD_Y = [-0.60, -0.35, -0.30, -0.25, -0.08, 0.02, 0.22, 0.40, 1.35]
NEW_Y = [anat["chin"], anat["lower_lip"], anat["mouth"], anat["upper_lip"], anat["subnasale"],
         anat["nose_tip"], anat["eye"], anat["brow"], anat["top"]]
assert all(np.diff(NEW_Y) > 0), ("anchors not monotonic", NEW_Y)


def map_y(y):
    if y < OLD_Y[0]:
        s = (NEW_Y[1] - NEW_Y[0]) / (OLD_Y[1] - OLD_Y[0])
        return NEW_Y[0] + (y - OLD_Y[0]) * s
    if y > OLD_Y[-1]:
        return NEW_Y[-1] + (y - OLD_Y[-1])
    return float(np.interp(y, OLD_Y, NEW_Y))


SX = abs(eyeL[0]) / 0.30
src = open(MORPHER_JS, encoding='utf-8').read()
block = src[src.index("static get LANDMARKS()"):]
block = block[:block.index("};") + 2]
old_lm = {m.group(1): [float(x) for x in m.group(2).split(',')]
          for m in re.finditer(r"(\w+):\s*\[([^\]]+)\]", block)}
new_lm = {}
for name, (x, y, z) in old_lm.items():
    tx, ty = x * SX, map_y(y)
    if z >= 0.85 and abs(x) <= 0.5:
        # Front-of-face point: take the front-most skin vertex at this (x, y)
        col = head_v[(np.abs(head_v[:, 0] - tx) < 0.04) & (np.abs(head_v[:, 1] - ty) < 0.04)]
        if len(col):
            new_lm[name] = col[col[:, 2].argmax()]
            continue
    target = np.array([tx, ty, z])
    new_lm[name] = head_v[np.argmin(np.linalg.norm(head_v - target, axis=1))]
cal["landmarks"] = {k: [round(float(c), 3) for c in v] for k, v in new_lm.items()}
cal["model_config"] = {"face_y_min": round(map_y(-0.80), 3), "face_y_max": round(map_y(1.30), 3)}
LM = {k: np.array(v) for k, v in cal["landmarks"].items()}

# ─── Hair (HairSystem._alignAndAdjust) ────────────────────────────────────
scalp_target = np.array([H["center"][0], H["max"][1] - H["size"][1] * 0.12, H["center"][2]])
cal["hair"] = {}
for i in range(1, 15):
    b = bbox(verts(P(f"models/hair/Hair{i}.glb")))
    base = W / max(b["size"][0], b["size"][2])
    scaleF = 1 / base                                    # want container scale == 1
    off = b["center"] - scalp_target
    d = {"posx": 50 + off[0] / 0.8 * 50, "posy": 50 + off[1] / 0.8 * 50, "posz": 50 + off[2] / 0.8 * 50,
         "roty": 50, "scale": (scaleF - 0.3) / 1.7 * 100}
    cal["hair"][f"hair{i}"] = {k: round(v, 1) for k, v in d.items()}

# ─── Beards (HairSystem._alignAndAdjustBeard) ─────────────────────────────
cal["beard"] = {}
for name in ["Beard1", "Beard2", "Beard3", "Beard4", "Beard5", "Beard6", "Moustache1"]:
    b = bbox(verts(P(f"models/facial/{name}.glb")))
    base = W / max(b["size"][0], b["size"][2])
    c = b["center"]
    d = {"scale": 200 / base, "posX": 100 + (c[0] - H["center"][0]) / 0.3 * 100,
         "posY": 100 + (c[1] - 0.15) / 0.8 * 100, "posZ": 100 + (c[2] - 0.95) / 0.8 * 100,
         "rotX": 100, "rotY": 100, "rotZ": 100}
    cal["beard"][name.lower()] = {k: round(v) for k, v in d.items()}

# ─── Eyebrows / eyelashes: models are in head space; code constants = their bbox ──
lash = bbox(verts(P("models/facial/eyelashes.glb")))
cal["eyebrows"] = {"regionWidth": round(float(brow["size"][0]), 4), "regionY": round(float(brow["center"][1]), 4),
                   "regionZ": round(float(brow["center"][2]), 4), "centerX": round(float(brow["center"][0]), 4)}
cal["eyelashes"] = {"regionWidth": round(float(lash["size"][0]), 4), "regionY": round(float(lash["center"][1]), 4),
                    "regionZ": round(float(lash["center"][2]), 4), "centerX": round(float(lash["center"][0]), 4)}

# ─── Eyes (EyeSystem._computeHeadMetrics/_applyAdjustments; Box3 treated as Z-height, Y-front) ──
eyeOffsetX = W * 0.16
eyeY = H["max"][1] - H["size"][1] * 0.12
eyeZ = H["min"][2] + H["size"][2] * 0.57
eye_maxdim = man["files"]["models/facial/EyeLeft.glb"].get("maxdim", 2.008 * eye_r)  # eyeball + cornea
cal["eyes"] = {
    "BASE_SPACING": round(float(eyeOffsetX - abs(eyeL[0])), 4),
    "BASE_OFFSET_Y": round(float(eyeL[1] - eyeY), 4),
    "BASE_OFFSET_Z": round(float(eyeL[2] - eyeZ), 4),
    "SCALE_K": round(float(eye_maxdim / (W * 0.11)), 4),
    "center": np.round(eyeL, 4).tolist(), "radius": round(eye_r, 4),
}

# ─── Glasses: split lenses, then GlassesSystem._alignAndAdjust calibration ──
def write_obj(path, parts):
    lines, base = ["# Nishaan glasses (MakeHuman asset, split into frame/lens objects)"], 1
    for name, mesh in parts:
        n = mesh.vertex_normals
        lines.append(f"o {name}")
        lines += [f"v {a:.6f} {b:.6f} {c:.6f}" for a, b, c in mesh.vertices]
        lines += [f"vn {a:.5f} {b:.5f} {c:.5f}" for a, b, c in n]
        lines += [f"f {a + base}//{a + base} {b + base}//{b + base} {c + base}//{c + base}" for a, b, c in mesh.faces]
        base += len(mesh.vertices)
    open(path, "w").write("\n".join(lines) + "\n")


bridge = LM["nose_bridge_top"]
span = abs(LM["temple_right"][0] - LM["temple_left"][0])
cal["glasses"] = {}
for style, fname in [("glasses1", "Glasses_01"), ("glasses2", "glasses"), ("glasses3", "Glasses_03"), ("glasses4", "Glasses_04")]:
    path = P("Glasses", fname + ".obj")
    m = trimesh.load(path, force='mesh', process=False)
    m.merge_vertices()
    parts = m.split(only_watertight=False)
    to_gl = lambda v: np.column_stack([v[:, 0], v[:, 2], -v[:, 1]])   # Blender Z-up -> app Y-up
    lens_idx = {}
    for i, p in enumerate(parts):
        b = bbox(to_gl(np.asarray(p.vertices)))
        cx, (sx, sy, sz) = b["center"][0], b["size"]
        if 0.15 < abs(cx) < 0.6 and 0.35 < sx < 0.75 and 0.18 < sy < 0.6 and sz < 0.3:
            side = 'left' if cx < 0 else 'right'
            if side not in lens_idx or sx < lens_idx[side][1]:
                lens_idx[side] = (i, sx)
    assert set(lens_idx) == {'left', 'right'}, (fname, lens_idx)
    lens_ids = {v[0] for v in lens_idx.values()}
    frame = trimesh.util.concatenate([p for i, p in enumerate(parts) if i not in lens_ids])
    write_obj(path, [("frame", frame)] + [(f"lens_{s}", parts[lens_idx[s][0]]) for s in ("left", "right")])
    b = bbox(to_gl(np.asarray(m.vertices)))
    base = span / b["size"][0]
    user_scale = 1 / base
    c = b["center"]
    d = {"scale": user_scale * 100, "lensScale": 100, "armSplay": 0, "armLength": 100,
         "posX": (c[0] - bridge[0]) / 0.01, "posY": (c[1] - bridge[1]) / 0.01,
         "posZ": (c[2] - bridge[2] - b["size"][2] * base * 0.5 - 0.012) / 0.01,
         "rotX": 0, "rotY": 0, "rotZ": 0}
    cal["glasses"][style] = {k: round(v) for k, v in d.items()}
    print("GLASSES", style, fname, "parts", len(parts), "lenses", lens_idx, cal["glasses"][style])

json.dump(cal, open(P("calibration.json"), "w"), indent=1)
print(json.dumps({k: cal[k] for k in ("model_config", "hair", "beard", "eyebrows", "eyelashes", "eyes")}, indent=1))
