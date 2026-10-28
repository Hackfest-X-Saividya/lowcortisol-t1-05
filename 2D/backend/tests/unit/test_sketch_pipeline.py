"""Face check, alignment, warp, masks, overlays, compositing, stability, rendering."""

from __future__ import annotations

import math
import time

import cv2
import numpy as np
import pytest

from app.config import Settings
from app.core.errors import ValidationFailed
from app.providers.mock.image import draw_face
from app.services.sketch import stability
from app.services.sketch.composite import composite
from app.services.sketch.generation import (
    align,
    apply_transform_points,
    build_prompt,
    estimate_pose,
    face_check,
)
from app.services.sketch.landmarks import eye_mouth_points, load_template
from app.services.sketch.masks import region_binary, region_mask
from app.services.sketch.overlays import apply_overlays, load_catalog
from app.services.sketch.regions import (
    HANDLES,
    MIRROR_PAIRS,
    SLIDERS,
    face_width,
    feature_regions,
    mediapipe_regions,
    slider_moves,
)
from app.services.sketch.render import pencil_sketch
from app.services.sketch.warp import compute_displacement, warp_image

SIZE = 1024


@pytest.fixture(scope="module")
def face() -> np.ndarray:
    return draw_face(SIZE, "medium brown skin", 1)


@pytest.fixture(scope="module")
def lm() -> np.ndarray:
    return load_template().landmarks


# ---- regions ------------------------------------------------------------------------------


def test_regions_from_mediapipe_connections() -> None:
    mp = mediapipe_regions()
    assert len(mp["face_oval"]) == 36 and len(mp["lips"]) == 40 and len(mp["nose"]) >= 20
    fr = feature_regions()
    assert set(fr["eyes"]) >= {33, 133, 362, 263}
    assert 152 in fr["jaw"] and 172 in fr["jaw"] and 397 in fr["jaw"]
    assert not (set(fr["jaw"]) & set(fr["eyes"]))
    assert len(HANDLES) >= 20 and len(MIRROR_PAIRS) >= 8
    assert set(SLIDERS) == {
        "jaw_width",
        "face_length",
        "eye_size",
        "eye_spacing",
        "nose_length",
        "nose_width",
        "lip_fullness",
        "brow_height",
    }


# ---- face check + alignment ----------------------------------------------------------------


def test_face_check_passes_template_and_fails_bad_cases(settings: Settings) -> None:
    t = load_template()
    ok = face_check([t.landmarks], settings)
    assert ok.ok and abs(ok.yaw_deg) < 3 and abs(ok.pitch_deg) < 3 and ok.width_ratio > 0.35
    assert not face_check([], settings).ok
    assert not face_check([t.landmarks, t.landmarks], settings).ok
    small = (t.landmarks - 0.5) * 0.5 + 0.5  # face shrunk to half width
    res = face_check([small], settings)
    assert not res.ok and any("width" in r for r in res.reasons)
    turned = t.landmarks.copy()
    turned[1, 0] += 0.08  # nose tip pushed sideways -> yaw
    res = face_check([turned], settings)
    assert not res.ok and any("yaw" in r for r in res.reasons)
    yaw, _ = estimate_pose(turned)
    assert abs(yaw) > settings.face_check_max_yaw_deg


def test_alignment_lands_eyes_on_canonical_within_2px(face: np.ndarray, lm: np.ndarray) -> None:
    t = load_template()
    # synthesize a rotated, scaled, shifted face + landmarks
    angle, scale, tx, ty = 7.0, 0.85, 40.0, -25.0
    M = cv2.getRotationMatrix2D((SIZE / 2, SIZE / 2), angle, scale)
    M[:, 2] += [tx, ty]
    img2 = cv2.warpAffine(face, M, (SIZE, SIZE), borderMode=cv2.BORDER_REPLICATE)
    lm2 = apply_transform_points(M, lm * SIZE) / SIZE
    aligned, new_lm, _ = align(img2, lm2, t, SIZE)
    assert aligned.shape == (SIZE, SIZE, 3)
    pts = eye_mouth_points(new_lm) * SIZE
    targets = t.targets * SIZE
    err = np.linalg.norm(pts - targets, axis=1)
    assert err.max() < 2.0, err


def test_prompt_template_and_skin_default() -> None:
    p = build_prompt({})
    assert p.prompt.startswith("frontal passport-style photograph of a person")
    assert "medium brown skin" in p.prompt and p.notes
    assert "plain light grey background" in p.prompt and "neutral expression" in p.prompt
    p2 = build_prompt(
        {
            "gender": {"value": "male"},
            "age_range": {"value": "30_40"},
            "skin_tone": {"value": "fair"},
            "nose": {"value": "hooked"},
            "other_marks": {"value": "knife scar"},
        }
    )
    assert "about 35 years old" in p2.prompt and "fair skin" in p2.prompt
    assert "hooked nose" in p2.prompt and "knife" not in p2.prompt and not p2.notes
    assert "smiling" in p2.negative_prompt


# ---- warp -----------------------------------------------------------------------------------


def test_warp_jaw_with_eyes_locked(face: np.ndarray, lm: np.ndarray) -> None:
    moves = slider_moves("jaw_width", 0.10)
    disp = compute_displacement(lm, moves, {"eyes"})
    t0 = time.perf_counter()
    warped, lm2 = warp_image(face, lm, disp.delta, 512)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, elapsed
    eyes = feature_regions()["eyes"]
    assert np.abs((lm2[eyes] - lm[eyes]) * SIZE).max() == 0.0
    eye_px = region_binary(lm, "eyes", (SIZE, SIZE), 0.0) > 0
    diff = np.abs(warped.astype(int) - face.astype(int))[eye_px].mean()
    assert diff < 1.0, diff
    jaw = feature_regions()["jaw"]
    assert np.linalg.norm((lm2[jaw] - lm[jaw]) * SIZE, axis=1).mean() > 5.0
    # jaw widened symmetrically: left corner moves +x, right corner -x
    assert lm2[397][0] > lm[397][0] and lm2[172][0] < lm[172][0]
    assert math.isclose(lm2[397][0] - lm[397][0], lm[172][0] - lm2[172][0], rel_tol=1e-6)


def test_warp_border_pinned_and_identity_when_no_move(face: np.ndarray, lm: np.ndarray) -> None:
    disp = compute_displacement(lm, slider_moves("nose_length", 0.08), set())
    warped, _ = warp_image(face, lm, disp.delta, 512)
    assert np.array_equal(warped[0], face[0]) and np.array_equal(warped[-1], face[-1])
    assert np.array_equal(warped[:, 0], face[:, 0]) and np.array_equal(warped[:, -1], face[:, -1])
    same, lm_same = warp_image(face, lm, np.zeros_like(lm), 512)
    assert np.array_equal(same, face) and np.array_equal(lm_same, lm)


def test_symmetric_drag_mirrors(lm: np.ndarray) -> None:
    disp = compute_displacement(
        lm, [{"handle": "jaw_left", "dx": 0.05, "dy": 0.0}], set(), symmetric=True
    )
    assert disp.delta[397][0] > 0 and disp.delta[172][0] < 0
    assert math.isclose(disp.delta[397][0], -disp.delta[172][0], rel_tol=1e-6)
    disp_one = compute_displacement(
        lm, [{"handle": "jaw_left", "dx": 0.05, "dy": 0.0}], set(), symmetric=False
    )
    # without symmetry the far corner only gets the tail of the Gaussian falloff
    assert abs(disp_one.delta[172][0]) < 0.1 * abs(disp_one.delta[397][0])


def test_locked_region_pinned_in_displacement(lm: np.ndarray) -> None:
    disp = compute_displacement(lm, slider_moves("jaw_width", 0.1), {"jaw"})
    assert not np.any(disp.delta)


# ---- masks ------------------------------------------------------------------------------------


@pytest.mark.parametrize("region", ["jaw", "nose", "mouth", "hair", "skin"])
def test_mask_zero_inside_locked_regions(lm: np.ndarray, region: str) -> None:
    locked = {"eyes", "brows", "mouth"} - {region}
    m = region_mask(lm, region, locked, (SIZE, SIZE))
    assert m.dtype == np.float32 and 0.0 <= m.min() and m.max() <= 1.0 and m.max() > 0.5
    for feat in locked:
        inside = region_binary(lm, feat, (SIZE, SIZE), 0.0) > 0
        assert m[inside].max() == 0.0, feat


# ---- overlays -------------------------------------------------------------------------------


def test_overlay_follows_landmarks_and_reapplies_after_warp(
    settings: Settings, face: np.ndarray, lm: np.ndarray
) -> None:
    cat = load_catalog(str(settings.assets_path / "overlays"))
    assert {
        "spectacles_round",
        "cap",
        "turban",
        "helmet",
        "face_cloth",
        "moustache_thin",
        "beard_full",
        "scar",
        "mole",
        "tilak",
        "earring",
    } <= set(cat)
    out, alpha = apply_overlays(
        settings, face, lm, [{"overlay_id": "spectacles_round", "params": {}}]
    )
    ys, xs = np.nonzero(alpha > 0.5)
    cx, cy = xs.mean(), ys.mean()
    eye_mid = (lm[33] + lm[263]) / 2 * SIZE
    assert abs(cx - eye_mid[0]) < 30 and abs(cy - eye_mid[1]) < 40
    # shift the face landmarks right: the overlay must move with them
    shifted = lm + [0.05, 0.0]
    _, alpha2 = apply_overlays(
        settings, face, shifted, [{"overlay_id": "spectacles_round", "params": {}}]
    )
    ys2, xs2 = np.nonzero(alpha2 > 0.5)
    assert abs(xs2.mean() - cx - 0.05 * SIZE) < 3
    # re-apply after a warp: overlay sits on the warped eye positions
    disp = compute_displacement(lm, slider_moves("eye_spacing", 0.1), set())
    warped, lm2 = warp_image(face, lm, disp.delta, 512)
    _, alpha3 = apply_overlays(
        settings, warped, lm2, [{"overlay_id": "spectacles_round", "params": {}}]
    )
    ys3, xs3 = np.nonzero(alpha3 > 0.5)
    assert (xs3.max() - xs3.min()) > (xs.max() - xs.min()) + 20  # wider with eye spacing
    # positional overlay
    out4, alpha4 = apply_overlays(
        settings,
        face,
        lm,
        [{"overlay_id": "scar", "params": {"position": "left_cheek", "size": 1.0}}],
    )
    ys4, xs4 = np.nonzero(alpha4 > 0.3)
    assert xs4.mean() > SIZE / 2  # subject's left = image right
    with pytest.raises(ValidationFailed):
        apply_overlays(settings, face, lm, [{"overlay_id": "nope", "params": {}}])


# ---- compositing + stability -----------------------------------------------------------------


def test_composite_exact_outside_mask(face: np.ndarray, lm: np.ndarray) -> None:
    new = cv2.GaussianBlur(face, (0, 0), 6)
    new = np.clip(new.astype(int) + 40, 0, 255).astype(np.uint8)
    mask = region_mask(lm, "nose", set(), (SIZE, SIZE))
    out = composite(face, new, mask, seamless=True)
    outside = mask <= 0.0
    assert np.array_equal(out[outside], face[outside])
    inside = mask >= 0.99
    assert np.abs(out[inside].astype(int) - face[inside].astype(int)).mean() > 1.0


def test_stability_metrics_and_thresholds(face: np.ndarray, lm: np.ndarray) -> None:
    moves = slider_moves("jaw_width", 0.1)
    disp = compute_displacement(lm, moves, {"eyes"})
    warped, lm2 = warp_image(face, lm, disp.delta, 512)
    mask = region_mask(lm2, "jaw", {"eyes"}, (SIZE, SIZE))
    s = stability.evaluate(face, warped, lm, lm2, mask, {"eyes"}, max_drift_px=3.0, min_ssim=0.9)
    assert s.locked_drift_px == 0.0 and not s.warning and 0.8 < s.geometry_similarity <= 1.0
    assert 0.0 <= s.ssim_outside_mask <= 1.0
    # pretend eyes drifted: warning with reason
    drifted = lm2.copy()
    eyes = feature_regions()["eyes"]
    drifted[eyes] += 0.01
    s2 = stability.evaluate(
        face, warped, lm, drifted, mask, {"eyes"}, max_drift_px=3.0, min_ssim=0.9
    )
    assert s2.warning and any("locked landmarks" in r for r in s2.reasons)
    s3 = stability.evaluate(
        face, np.zeros_like(face), lm, lm2, mask, {"eyes"}, max_drift_px=3.0, min_ssim=0.995
    )
    assert s3.warning and any("SSIM" in r for r in s3.reasons)
    assert stability.geometry_similarity(lm, lm) == 1.0
    assert face_width(lm) > 0.3


def test_pencil_sketch_is_grey_and_edges_present(face: np.ndarray) -> None:
    sk = pencil_sketch(face)
    assert sk.shape == face.shape
    assert np.array_equal(sk[:, :, 0], sk[:, :, 1]) and np.array_equal(sk[:, :, 1], sk[:, :, 2])
    assert sk.mean() > 150 and sk.min() < 120  # mostly light paper with dark lines
