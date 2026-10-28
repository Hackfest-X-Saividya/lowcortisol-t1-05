"""Turntable preview clips for the hair picker. blender -b -P render_previews.py -- <repo> <out_dir>"""
import bpy, math, os, sys
from mathutils import Vector

REPO, OUT = sys.argv[sys.argv.index('--') + 1:][:2]
A = os.path.join(REPO, 'assets', 'models')
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = 'BLENDER_WORKBENCH'
scene.display.shading.light = 'STUDIO'
scene.display.shading.color_type = 'OBJECT'
scene.display.shading.show_cavity = True
scene.render.resolution_x, scene.render.resolution_y = 484, 540
scene.render.fps = 24
scene.frame_start, scene.frame_end = 1, 120
scene.render.image_settings.media_type = 'VIDEO'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
scene.render.ffmpeg.constant_rate_factor = 'MEDIUM'
world = bpy.data.worlds.new('bg')
scene.world = world
scene.display.shading.background_type = 'VIEWPORT'
scene.display.shading.background_color = (0.04, 0.04, 0.06)


def srgb(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c) + (1,)


def load(path, color):
    bpy.ops.import_scene.gltf(filepath=path)
    objs = list(bpy.context.selected_objects)
    for o in objs:
        o.color = color
        o.parent = pivot
    return objs


pivot = bpy.data.objects.new('pivot', None)
scene.collection.objects.link(pivot)
load(os.path.join(A, 'base', 'head.glb'), srgb('d4a574'))
for side in ('EyeLeft', 'EyeRight'):
    for o in load(os.path.join(A, 'facial', f'{side}.glb'), srgb('f2f2f2')):
        if 'Iris' in o.name:
            o.color = srgb('5a3a22')
        elif 'Pupil' in o.name:
            o.color = srgb('050505')
load(os.path.join(A, 'facial', 'eyebrows.glb'), srgb('2c1b0e'))
load(os.path.join(A, 'facial', 'eyelashes.glb'), srgb('0a0a0a'))

# Turntable: one full turn about the vertical axis (Blender Z)
pivot.rotation_euler = (0, 0, 0)
pivot.keyframe_insert('rotation_euler', frame=1)
pivot.rotation_euler = (0, 0, math.radians(360))
pivot.keyframe_insert('rotation_euler', frame=scene.frame_end + 1)
for fc in pivot.animation_data.action.layers[0].strips[0].channelbag(pivot.animation_data.action.slots[0]).fcurves \
        if hasattr(pivot.animation_data.action, 'layers') else pivot.animation_data.action.fcurves:
    for k in fc.keyframe_points:
        k.interpolation = 'LINEAR'

cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
scene.collection.objects.link(cam)
scene.camera = cam
cam.data.lens = 100
cam.location = (0, -11.5, 0.0)
cam.rotation_euler = (math.radians(90), 0, 0)

styles = [(f'Hair {i}', f'Hair{i}.glb') for i in range(1, 15)] + [('Bald', None)]
for label, f in styles:
    hair = load(os.path.join(A, 'hair', f), srgb('2c1b0e')) if f else []
    scene.render.filepath = os.path.join(OUT, f'{label}.mp4')
    bpy.ops.render.render(animation=True)
    print('RENDERED', label)
    for o in hair:
        bpy.data.objects.remove(o, do_unlink=True)
