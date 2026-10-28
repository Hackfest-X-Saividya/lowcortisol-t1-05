"""RFC 6902 patches on scene JSON with validation and locked-object protection.

A patch is rejected if any object with ``locked: true`` in the current scene differs in
the result (moved, resized, retyped or removed). The one exception is a patch whose only
effect on that object is the ``locked`` flag itself (an explicit unlock by the officer).
"""

from __future__ import annotations

import copy
from typing import Any

import jsonpatch

from app.core.errors import ValidationFailed
from app.services.scene.builder import clamp_scene, snap_scene, validate
from app.services.scene.schema import Scene


def apply_patch(scene_dict: dict[str, Any], patch_ops: list[dict[str, Any]]) -> Scene:
    if not isinstance(patch_ops, list) or not patch_ops:
        raise ValidationFailed("patch must be a non-empty list of RFC 6902 operations")
    try:
        patched = jsonpatch.JsonPatch(patch_ops).apply(copy.deepcopy(scene_dict), in_place=False)
    except (
        jsonpatch.JsonPatchException,
        jsonpatch.JsonPointerException,
        TypeError,
        KeyError,
        IndexError,
    ) as exc:
        raise ValidationFailed(f"Patch could not be applied: {exc}"[:300])
    new_scene = validate(patched)
    old_scene = validate(scene_dict)
    _check_locked(old_scene, new_scene)
    return clamp_scene(snap_scene(new_scene))


def _check_locked(old: Scene, new: Scene) -> None:
    new_by_id = {o.id: o for o in new.objects}
    for o in old.objects:
        if not o.locked:
            continue
        n = new_by_id.get(o.id)
        if n is None:
            raise ValidationFailed(
                f"Object {o.id} is locked and cannot be removed", code="object_locked"
            )
        before = o.model_dump(exclude={"locked"})
        after = n.model_dump(exclude={"locked"})
        if before != after:
            raise ValidationFailed(
                f"Object {o.id} is locked. Unlock it first.", code="object_locked"
            )


def diff_patch(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    return list(jsonpatch.make_patch(old, new))
