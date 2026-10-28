"""
Pack the morph probes written by mh_build.py into the files the app loads.

Usage: python pack_morphs.py <build_out_dir> <dest_dir>
Writes <dest_dir>/head_morphs.json and <dest_dir>/head_morphs.bin.

Each probe is the head's vertex positions with one MakeHuman target (or one
macro corner) applied. The deltas are re-ordered to head.glb's vertex order
(the glTF exporter splits vertices along UV seams, so several GLB vertices can
share one probe vertex), thresholded to the vertices that actually move, and
stored as int16 with a per-entry scale:

    bin  = for each entry: uint16 index[count] (padded to 4 bytes),
                           int16 delta[count * 3] (padded to 4 bytes)
    json = { vertexCount, entries: { name: {offset, count, scale} }, params, macro }
"""
import glob
import json
import os
import struct
import sys

import numpy as np
from scipy.spatial import cKDTree

SRC, DEST = sys.argv[1], sys.argv[2]
MDIR = os.path.join(SRC, "morphs")
THRESHOLD = 1e-4          # world units; the head is ~1.9 wide


def glb_positions(path):
    data = open(path, "rb").read()
    jlen = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20:20 + jlen])
    binary = data[20 + jlen + 8:]
    acc = gltf["accessors"][gltf["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    view = gltf["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    return np.frombuffer(binary, dtype="<f4", count=acc["count"] * 3, offset=start).reshape(-1, 3)


def to_gl(blender_xyz):
    return np.column_stack([blender_xyz[:, 0], blender_xyz[:, 2], -blender_xyz[:, 1]])


glb = glb_positions(os.path.join(SRC, "models", "base", "head.glb"))
neutral = to_gl(np.load(os.path.join(MDIR, "neutral.npy")))
dist, order = cKDTree(neutral).query(glb)
assert dist.max() < 1e-5, f"GLB/probe vertex mismatch: {dist.max()}"
assert len(glb) < 65536, "uint16 indices need < 65536 vertices"

entries, chunks, offset = {}, [], 0
for path in sorted(glob.glob(os.path.join(MDIR, "*.npy"))):
    name = os.path.basename(path)[:-4]
    if name == "neutral":
        continue
    delta = to_gl(np.load(path)) - neutral
    if name.startswith("m_"):
        # Macro shapes change the whole body (height, posture), which moves the
        # head; keep only the change in head shape by removing the mean shift.
        delta -= delta.mean(axis=0)
    delta = delta[order]                                     # GLB vertex order
    moving = np.flatnonzero(np.abs(delta).max(axis=1) > THRESHOLD)
    if not len(moving):
        print("skip (no effect):", name)
        continue
    d = delta[moving]
    scale = float(np.abs(d).max()) / 32767.0
    idx = moving.astype("<u2").tobytes()
    idx += b"\0" * (-len(idx) % 4)
    q = np.round(d / scale).astype("<i2").tobytes()
    q += b"\0" * (-len(q) % 4)
    key = name[2:]                                           # strip t_ / m_ prefix
    entries[key] = {"offset": offset, "count": int(len(moving)), "scale": scale}
    chunks += [idx, q]
    offset += len(idx) + len(q)

params = json.load(open(os.path.join(MDIR, "param_targets.json")))
missing = {t for p in params.values() for t, _ in p["decr"] + p["incr"]} - set(entries)
assert not missing, f"targets without data: {sorted(missing)}"

meta = {
    "version": 1,
    "vertexCount": int(len(glb)),
    "entries": entries,
    "params": params,
    "macro": {
        "races": ["african", "asian", "caucasian"],
        "genders": ["female", "male"],
        "ages": {"child": 0.1875, "young": 0.5, "old": 1.0},
        "baseline": {"gender": 1.0, "age": 0.5, "african": 0.33, "asian": 0.33, "caucasian": 0.34},
    },
}
os.makedirs(DEST, exist_ok=True)
with open(os.path.join(DEST, "head_morphs.bin"), "wb") as f:
    for c in chunks:
        f.write(c)
with open(os.path.join(DEST, "head_morphs.json"), "w") as f:
    json.dump(meta, f, separators=(",", ":"))
print(f"packed {len(entries)} entries, {offset / 1e6:.2f} MB")
