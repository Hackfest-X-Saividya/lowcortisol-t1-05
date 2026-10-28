"""
Build Nishaan's replacement head + accessories from MakeHuman (MPFB) assets.

Run:  blender -b -P mh_build.py -- <out_dir>

Everything is generated in one coordinate frame: the new head is scaled and
centred onto the ORIGINAL head.glb bounding box (Y-up, +Z = face front), and
every accessory gets the same transform, so it stays fitted to the head.
A manifest.json records each file's bbox so app defaults can be computed.
"""
import bpy, bmesh, json, math, os, sys
from mathutils import Matrix, Vector
from bl_ext.blender_org.mpfb.services.humanservice import HumanService
from bl_ext.blender_org.mpfb.services.locationservice import LocationService

OUT = sys.argv[sys.argv.index('--') + 1]
os.makedirs(OUT, exist_ok=True)
DATA = LocationService.get_user_data()

# Original head.glb bbox (glTF Y-up). Blender is Z-up with -Y = front, so
# glTF (x, y, z) == Blender (x, -z_gl... ) -> Blender (x, -gz, gy).
ORIG_SIZE_X = 1.9132360219955444
ORIG_CENTER_GL = Vector((0.0, -0.17590200901031494, 0.1823984980583191))
ORIG_CENTER_BL = Vector((ORIG_CENTER_GL.x, -ORIG_CENTER_GL.z, ORIG_CENTER_GL.y))
ORIG_TOP_GL_Y = 1.3854320049285889

HAIR = [  # (export name, asset dir under data/hair, author, license)
    ("Hair1", "short02", "MakeHuman system assets", "CC0"),
    ("Hair2", "short01", "MakeHuman system assets", "CC0"),
    ("Hair3", "short03", "MakeHuman system assets", "CC0"),
    ("Hair4", "short04", "MakeHuman system assets", "CC0"),
    ("Hair5", "culturalibre_hair_05", "culturalibre", "CC0"),
    ("Hair6", "elvs_short_side_do", "Elvaerwyn", "CC-BY 4.0"),
    ("Hair7", "afro01", "MakeHuman system assets", "CC0"),
    ("Hair8", "elvs_micky_afro", "Elvaerwyn", "CC-BY 4.0"),
    ("Hair9", "elvs_braided_rows", "Elvaerwyn", "CC-BY 4.0"),
    ("Hair10", "elvs_maxwell_hair", "Elvaerwyn", "CC-BY 4.0"),
    ("Hair11", "bob01", "MakeHuman system assets", "CC0"),
    ("Hair12", "long01", "MakeHuman system assets", "CC0"),
    ("Hair13", "ponytail01", "MakeHuman system assets", "CC0"),
    ("Hair14", "braid01", "MakeHuman system assets", "CC0"),
]
FACIAL = [  # (export name, data-relative mhclo dir, author, license)
    ("Beard1", "clothes/grinsegold_full_beard", "grinsegold", "CC-BY 4.0"),
    ("Beard2", "clothes/wdg_scruffy_beard", "WDG", "CC0"),
    ("Beard3", "clothes/rehmanpolanski_beard_viking", "RehmanPolanski", "CC0"),
    ("Beard4", "clothes/elvs_scruffy_beard1", "Elvaerwyn", "CC-BY 4.0"),
    ("Beard5", "clothes/culturalibre_faun_beard", "culturalibre", "CC0"),
    ("Beard6", "clothes/grinsegold_beard_sigmund_wip", "grinsegold", "CC0"),
    ("Moustache1", "clothes/grinsegold_moustache", "grinsegold", "CC-BY 4.0"),
    ("eyebrows", "eyebrows/eyebrow001", "MakeHuman system assets", "CC0"),
    ("eyelashes", "eyelashes/eyelashes01", "MakeHuman system assets", "CC0"),
]
GLASSES = [  # exported as OBJ (GlassesSystem uses OBJLoader)
    ("Glasses_01", "clothes/kwnet_at_optical_glasses", "kwnet_at", "CC0"),
    ("glasses", "clothes/elvs_ladies_sunglass1", "Elvaerwyn", "CC-BY 4.0"),
    ("Glasses_03", "clothes/toigo_round_glasses_leopard", "MargaretToigo", "CC0"),
    ("Glasses_04", "clothes/punkduck_glasses_modern_form", "punkduck", "CC-BY 4.0"),
]

manifest = {"frame": "glTF Y-up, +Z = face front, matched to original head.glb bbox", "files": {}}


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def find_mhclo(rel_dir):
    d = os.path.join(DATA, rel_dir)
    for f in os.listdir(d):
        if f.endswith('.mhclo'):
            return os.path.join(d, f)
    raise FileNotFoundError(d)


def world_mesh_copy(obj, name, matrix):
    """Evaluated (modifiers + shape keys) copy of obj in world space, transformed by matrix."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=False, depsgraph=dg)
    me.transform(matrix @ obj.matrix_world)
    me.materials.clear()
    new = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(new)
    return new


def bbox_gl(obj):
    """Bounding box of obj's vertices in glTF coordinates."""
    pts = [Vector((v.co.x, v.co.z, -v.co.y)) for v in obj.data.vertices]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return {"min": list(mn), "max": list(mx), "center": list((mn + mx) / 2), "size": list(mx - mn)}


def export(obj, rel_path, fmt="glb", meta=None):
    path = os.path.join(OUT, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if fmt == "glb":
        bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', use_selection=True,
                                  export_yup=True, export_materials='NONE', export_apply=True,
                                  export_animations=False, export_skins=False, export_morph=False)
    else:
        # fmt "obj": standard Y-up OBJ (what Blender's importer expects by default).
        # fmt "obj_zup": raw Blender axes; GlassesSystem's OBJ loader bakes the -90° X fix itself.
        zup = fmt == "obj_zup"
        bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True,
                              forward_axis='Y' if zup else 'NEGATIVE_Z', up_axis='Z' if zup else 'Y', export_materials=False, export_uv=True, export_normals=True,
                              apply_modifiers=True)
    entry = {"vertices": len(obj.data.vertices), **bbox_gl(obj), **(meta or {})}
    manifest["files"][rel_path] = entry
    print(f"EXPORTED {rel_path} verts={entry['vertices']} size={[round(v, 3) for v in entry['size']]}")


def disable_extra_masks(human):
    for m in human.modifiers:
        if m.type == 'MASK' and m.name != "Hide helpers":
            m.show_viewport = False
            m.show_render = False


# ─── Human ────────────────────────────────────────────────────────────────
clear_scene()
macro = {"gender": 1.0, "age": 0.5, "muscle": 0.5, "weight": 0.5, "proportions": 0.5,
         "height": 0.5, "cupsize": 0.5, "firmness": 0.5,
         "race": {"asian": 0.33, "caucasian": 0.34, "african": 0.33}}
human = HumanService.create_human(macro_detail_dict=macro, feet_on_ground=True, scale=0.1)
human.name = "Human"

# Head + neck cut just above where the shoulders flare (measured: ~0.235 m
# below the crown for this body; the neck is narrowest ~0.21 m down).
raw = world_mesh_copy(human, "raw_head", Matrix.Identity(4))
top = max(v.co.z for v in raw.data.vertices)
cut_z = top - 0.235
CUT_IDX = [v.index for v in raw.data.vertices if v.co.z < cut_z]
bm = bmesh.new()
bm.from_mesh(raw.data)
bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < cut_z], context='VERTS')
bm.to_mesh(raw.data)
bm.free()

# Normalisation matrix: uniform scale to original width, centre on original bbox centre
vs = [v.co for v in raw.data.vertices]
mn = Vector((min(c.x for c in vs), min(c.y for c in vs), min(c.z for c in vs)))
mx = Vector((max(c.x for c in vs), max(c.y for c in vs), max(c.z for c in vs)))
scale = ORIG_SIZE_X / (mx.x - mn.x)   # ear-to-ear width == original width
# Align X centre, depth centre and the crown with the original head (its neck
# was longer, so matching the full bbox centre would push the face too high).
anchor = Vector(((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, mx.z))
target = Vector((ORIG_CENTER_BL.x, ORIG_CENTER_BL.y, ORIG_TOP_GL_Y))
NORM = Matrix.Translation(target) @ Matrix.Scale(scale, 4) @ Matrix.Translation(-anchor)
raw.data.transform(NORM)
raw.name = "Head"
print(f"HEAD cut_z={cut_z:.4f} scale={scale:.4f} verts={len(raw.data.vertices)}")

# Smooth the head once so face morphs have enough vertices to work with
sub = raw.modifiers.new("Subsurf", 'SUBSURF')
sub.levels = 1
sub.render_levels = 1
sub.boundary_smooth = 'PRESERVE_CORNERS'
head = world_mesh_copy(raw, "Head", Matrix.Identity(4))
bpy.data.objects.remove(raw, do_unlink=True)
for p in head.data.polygons:
    p.use_smooth = True
export(head, "models/base/head.glb", meta={"source": "MakeHuman base mesh (MPFB)", "license": "CC0"})
export(head, "models/base/base_face.obj", fmt="obj", meta={"source": "MakeHuman base mesh (MPFB)", "license": "CC0"})
head_bbox = bbox_gl(head)
manifest["head_scale"] = scale


def fit_and_export(rel_dir, export_name, rel_path, author, license_, fmt="glb", kind="Clothes"):
    obj = HumanService.add_mhclo_asset(find_mhclo(rel_dir), human, asset_type=kind, subdiv_levels=0,
                                       set_up_rigging=False, interpolate_weights=False,
                                       import_subrig=False, import_weights=False)
    disable_extra_masks(human)
    out = world_mesh_copy(obj, export_name, NORM)
    for p in out.data.polygons:
        p.use_smooth = True
    export(out, rel_path, fmt, meta={"source": os.path.basename(rel_dir), "asset_dir": rel_dir,
                                     "author": author, "license": license_})
    bpy.data.objects.remove(out, do_unlink=True)
    bpy.data.objects.remove(obj, do_unlink=True)
    return rel_path


# ─── Eyes: MakeHuman high-poly eyes (UV-mapped eyeball + clear cornea) ────
def mesh_islands(me):
    """Connected vertex sets of a mesh."""
    adj = {v.index: [] for v in me.vertices}
    for e in me.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)
    seen, islands = set(), []
    for start_v in adj:
        if start_v in seen:
            continue
        stack, isl = [start_v], set()
        while stack:
            v = stack.pop()
            if v in seen:
                continue
            seen.add(v)
            isl.add(v)
            stack.extend(adj[v])
        islands.append(isl)
    return islands


def island_object(src, keep, name, offset):
    me = src.data.copy()
    me.name = name
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index not in keep], context='VERTS')
    bmesh.ops.translate(bm, verts=bm.verts, vec=-offset)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


eyes_src = HumanService.add_mhclo_asset(find_mhclo("eyes/high-poly"), human, asset_type="Eyes", subdiv_levels=0,
                                        set_up_rigging=False, interpolate_weights=False,
                                        import_subrig=False, import_weights=False)
eyes = world_mesh_copy(eyes_src, "eyes_tmp", NORM)
bpy.data.objects.remove(eyes_src, do_unlink=True)
islands = [i for i in mesh_islands(eyes.data) if len(i) > 20]      # drop tiny helper quads
for side, sign in (("EyeLeft", -1), ("EyeRight", 1)):
    mine = [i for i in islands if eyes.data.vertices[next(iter(i))].co.x * sign > 0]
    assert len(mine) == 2, (side, [len(i) for i in mine])

    def size_of(isl):
        xs = [eyes.data.vertices[i].co.x for i in isl]
        return max(xs) - min(xs)
    cornea_isl, ball_isl = sorted(mine, key=size_of, reverse=True)   # cornea shell is the larger one
    pts = [eyes.data.vertices[i].co for i in ball_isl]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    c = (lo + hi) / 2
    parts = [island_object(eyes, ball_isl, "eyeball", c), island_object(eyes, cornea_isl, "cornea", c)]
    allp = [v.co for o in parts for v in o.data.vertices]
    maxdim = max(max(p[k] for p in allp) - min(p[k] for p in allp) for k in range(3))
    bpy.ops.object.select_all(action='DESELECT')
    for o in parts:
        o.select_set(True)
    path = os.path.join(OUT, f"models/facial/{side}.glb")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', use_selection=True, export_yup=True,
                              export_materials='NONE', export_animations=False)
    c_gl = [c.x, c.z, -c.y]
    manifest["files"][f"models/facial/{side}.glb"] = {
        "vertices": sum(len(o.data.vertices) for o in parts), "center": c_gl,
        "radius": (hi.x - lo.x) / 2, "maxdim": maxdim, "asset_dir": "eyes/high-poly",
        "source": "high-poly", "author": "MakeHuman team", "license": "CC0"}
    print(f"EXPORTED models/facial/{side}.glb center={[round(x, 3) for x in c_gl]} maxdim={maxdim:.4f}")
    for o in parts:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.data.objects.remove(eyes, do_unlink=True)

# ─── Hair, facial hair, glasses ───────────────────────────────────────────
if '--only-hair' in sys.argv:
    for d in sys.argv[sys.argv.index('--only-hair') + 1].split(','):
        fit_and_export(f"hair/{d}", d, f"candidates/{d}.glb", "?", "?", kind="Hair")
    sys.exit(0)
for name, d, author, lic in HAIR:
    fit_and_export(f"hair/{d}", name, f"models/hair/{name}.glb", author, lic, kind="Hair")
for name, d, author, lic in FACIAL:
    kind = "Eyebrows" if d.startswith("eyebrows") else "Eyelashes" if d.startswith("eyelashes") else "Clothes"
    fit_and_export(d, name, f"models/facial/{name}.glb", author, lic, kind=kind)
for name, d, author, lic in GLASSES:
    fit_and_export(d, name, f"Glasses/{name}.obj", author, lic, fmt="obj_zup")

manifest["head"] = head_bbox

# ─── Morph data ───────────────────────────────────────────────────────────
# Every MakeHuman target the app uses is applied in turn and the head is
# re-measured through the same cut + subdivision as head.glb, so the deltas
# line up vertex-for-vertex. scripts/assets/pack_morphs.py turns them into
# assets/models/base/head_morphs.{json,bin}.
import numpy as np
from bl_ext.blender_org.mpfb.services.targetservice import TargetService
from bl_ext.blender_org.mpfb.entities.objectproperties import HumanObjectProperties


def LR(name, w=1.0):
    return [(f"l-{name}", w), (f"r-{name}", w)]


def one(name, w=1.0):
    return [(name, w)]


# App slider -> (targets toward 0, targets toward 100). 50 = neutral.
PARAM_TARGETS = {
    "faceWidth": (one("head-scale-horiz-decr"), one("head-scale-horiz-incr")),
    "faceLength": (one("head-scale-vert-decr"), one("head-scale-vert-incr")),
    "headWidth": (one("head-scale-horiz-decr", 0.6) + one("forehead-temple-decr", 0.6),
                  one("head-scale-horiz-incr", 0.6) + one("forehead-temple-incr", 0.6)),
    "headLength": (one("head-back-scale-depth-decr"), one("head-back-scale-depth-incr")),
    "faceTaper": (one("head-square"), one("head-invertedtriangular")),
    "foreheadHeight": (one("forehead-scale-vert-decr"), one("forehead-scale-vert-incr")),
    "foreheadSlope": (one("forehead-trans-forward"), one("forehead-trans-backward")),
    "foreheadWidth": (one("forehead-temple-decr"), one("forehead-temple-incr")),
    "templeWidth": (one("forehead-temple-decr", 0.7), one("forehead-temple-incr", 0.7)),
    "foreheadBulge": (one("forehead-nubian-decr"), one("forehead-nubian-incr")),
    "browHeight": (one("eyebrows-trans-down"), one("eyebrows-trans-up")),
    "browProminence": (one("eyebrows-trans-backward"), one("eyebrows-trans-forward")),
    "browArch": (one("eyebrows-angle-down"), one("eyebrows-angle-up")),
    "eyeSpacing": (LR("eye-trans-in"), LR("eye-trans-out")),
    "eyeHeight": (LR("eye-trans-down"), LR("eye-trans-up")),
    "eyeDepth": (LR("eye-push1-out") + LR("eye-push2-out", 0.5), LR("eye-push1-in") + LR("eye-push2-in", 0.5)),
    "eyeSize": (LR("eye-scale-decr"), LR("eye-scale-incr")),
    "eyeTilt": (LR("eye-corner2-down"), LR("eye-corner2-up")),
    "eyeOpenness": (LR("eye-height2-decr"), LR("eye-height2-incr")),
    "eyeBags": (LR("eye-bag-decr"), LR("eye-bag-incr")),
    "epicanthicFold": (LR("eye-epicanthus-out"), LR("eye-epicanthus-in")),
    "noseLength": (one("nose-scale-vert-decr"), one("nose-scale-vert-incr")),
    "noseWidth": (one("nose-scale-horiz-decr"), one("nose-scale-horiz-incr")),
    "noseBridgeWidth": (one("nose-width1-decr"), one("nose-width1-incr")),
    "noseBridgeHeight": (one("nose-hump-decr"), one("nose-hump-incr")),
    "noseCurve": (one("nose-curve-concave"), one("nose-curve-convex")),
    "noseTipHeight": (one("nose-point-down"), one("nose-point-up")),
    "noseTipWidth": (one("nose-point-width-decr"), one("nose-point-width-incr")),
    "nostrilFlare": (one("nose-flaring-decr") + one("nose-nostrils-width-decr", 0.5),
                     one("nose-flaring-incr") + one("nose-nostrils-width-incr", 0.5)),
    "cheekFullness": (LR("cheek-volume-decr"), LR("cheek-volume-incr")),
    "cheekboneProminence": (LR("cheek-bones-decr"), LR("cheek-bones-incr")),
    "cheekHeight": (LR("cheek-trans-down"), LR("cheek-trans-up")),
    "nasolabialDepth": (one("mouth-laugh-lines-out"), one("mouth-laugh-lines-in")),
    "mouthWidth": (one("mouth-scale-horiz-decr"), one("mouth-scale-horiz-incr")),
    "mouthHeight": (one("mouth-trans-down"), one("mouth-trans-up")),
    "lipProtrusion": (one("mouth-trans-backward"), one("mouth-trans-forward")),
    "upperLipThickness": (one("mouth-upperlip-volume-decr") + one("mouth-upperlip-height-decr", 0.5),
                          one("mouth-upperlip-volume-incr") + one("mouth-upperlip-height-incr", 0.5)),
    "lowerLipThickness": (one("mouth-lowerlip-volume-decr") + one("mouth-lowerlip-height-decr", 0.5),
                          one("mouth-lowerlip-volume-incr") + one("mouth-lowerlip-height-incr", 0.5)),
    "cupidBow": (one("mouth-cupidsbow-decr"), one("mouth-cupidsbow-incr")),
    "philtrumDepth": (one("mouth-philtrum-volume-incr"), one("mouth-philtrum-volume-decr")),
    "philtrumWidth": (one("mouth-cupidsbow-width-decr"), one("mouth-cupidsbow-width-incr")),
    "lipCornerAngle": (one("mouth-angles-down"), one("mouth-angles-up")),
    "jawWidth": (one("chin-bones-decr"), one("chin-bones-incr")),
    "chinHeight": (one("chin-height-decr"), one("chin-height-incr")),
    "chinWidth": (one("chin-width-decr"), one("chin-width-incr")),
    "chinProtrusion": (one("chin-prominent-decr") + one("chin-prognathism-decr", 0.3),
                       one("chin-prominent-incr") + one("chin-prognathism-incr", 0.3)),
    "chinCleft": ([], one("chin-cleft-incr")),
    "doubleChin": (one("neck-double-decr"), one("neck-double-incr")),
    "earSize": (LR("ear-scale-decr"), LR("ear-scale-incr")),
    "earProtrusion": (LR("ear-wing-decr"), LR("ear-wing-incr")),
    "earHeight": (LR("ear-trans-down"), LR("ear-trans-up")),
    "earlobeSize": (LR("ear-lobe-decr"), LR("ear-lobe-incr")),
}
MDIR = os.path.join(OUT, "morphs")
os.makedirs(MDIR, exist_ok=True)


def head_positions():
    """Head vertex positions (app frame, Blender axes) for the human's current shape."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(human.evaluated_get(dg), depsgraph=dg)
    me.transform(human.matrix_world)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.verts[i] for i in CUT_IDX], context='VERTS')
    bm.to_mesh(me)
    bm.free()
    me.transform(NORM)
    probe = bpy.data.objects.new("probe", me)
    bpy.context.scene.collection.objects.link(probe)
    sub = probe.modifiers.new("Subsurf", 'SUBSURF')
    sub.levels = 1
    sub.boundary_smooth = 'PRESERVE_CORNERS'
    dg = bpy.context.evaluated_depsgraph_get()
    ev = probe.evaluated_get(dg)
    em = ev.to_mesh()
    arr = np.empty(len(em.vertices) * 3, dtype=np.float32)
    em.vertices.foreach_get("co", arr)
    ev.to_mesh_clear()
    bpy.data.objects.remove(probe, do_unlink=True)
    bpy.data.meshes.remove(me)
    return arr.reshape(-1, 3)


for m in list(human.modifiers):
    if m.type == 'MASK' and m.name != "Hide helpers":
        human.modifiers.remove(m)
neutral = head_positions()
check = np.array([v.co[:] for v in head.data.vertices], dtype=np.float32)
assert neutral.shape == check.shape, (neutral.shape, check.shape)
print(f"MORPH neutral matches exported head: max diff {np.abs(neutral - check).max():.2e}")
np.save(os.path.join(MDIR, "neutral.npy"), neutral)

needed = sorted({t for dec, inc in PARAM_TARGETS.values() for t, _ in dec + inc})
for name in needed:
    path = TargetService.target_full_path(name)
    assert path and os.path.basename(path).startswith(name + "."), (name, path)
    TargetService.load_target(human, path, weight=1.0, name="probe_" + name)
    np.save(os.path.join(MDIR, f"t_{name}.npy"), head_positions())
    human.shape_key_remove(human.data.shape_keys.key_blocks["probe_" + name])
print("MORPH detail targets", len(needed))

BASE_MACRO = {"gender": 1.0, "age": 0.5, "weight": 0.5, "muscle": 0.5,
              "african": 0.33, "asian": 0.33, "caucasian": 0.34}


def set_macro(**vals):
    for k, v in {**BASE_MACRO, **vals}.items():
        HumanObjectProperties.set_value(k, v, entity_reference=human)
    TargetService.reapply_macro_details(human)


# MakeHuman's macro system is multilinear in race x gender x age, so these 18
# corner shapes reproduce it exactly when blended with the same weights.
RACES = {"african": (1, 0, 0), "asian": (0, 1, 0), "caucasian": (0, 0, 1)}
AGES = {"child": 0.1875, "young": 0.5, "old": 1.0}
for race, (af, asn, cau) in RACES.items():
    for gname, g in (("female", 0.0), ("male", 1.0)):
        for aname, a in AGES.items():
            set_macro(gender=g, age=a, african=af, asian=asn, caucasian=cau)
            np.save(os.path.join(MDIR, f"m_{race}_{gname}_{aname}.npy"), head_positions())
for key in ("weight", "muscle"):
    for label, v in (("min", 0.0), ("max", 1.0)):
        set_macro(**{key: v})
        np.save(os.path.join(MDIR, f"m_{key}_{label}.npy"), head_positions())
set_macro()
print("MORPH macro shapes done")
with open(os.path.join(MDIR, "param_targets.json"), "w") as f:
    json.dump({p: {"decr": dec, "incr": inc} for p, (dec, inc) in PARAM_TARGETS.items()}, f, indent=1)

with open(os.path.join(OUT, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)
print("DONE", len(manifest["files"]), "files")
