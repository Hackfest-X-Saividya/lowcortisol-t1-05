"""Hand-drawn pencil rendering and witness-placed marks."""

from __future__ import annotations

import numpy as np

from app.providers.mock.image import draw_face
from app.services.sketch import hand_drawn, marks
from app.services.sketch.landmarks import load_template


def test_parse_marks_type_place_and_side() -> None:
    got = marks.from_sheet(
        {
            "moles": "a mole on his left cheek and a small one near the right nostril",
            "scars": "scar on the chin",
            "other_marks": "big birthmark above the right eyebrow",
        }
    )
    assert [(m.kind, m.region, m.side) for m in got] == [
        ("mole", "cheek", "left"),
        ("mole", "nostril", "right"),
        ("scar", "chin", "centre"),
        ("birthmark", "eyebrow", "right"),
    ]
    assert got[1].scale < 1 < got[3].scale and got[3].up > 0
    assert marks.parse("none") == [] and marks.parse("gold tooth") == []
    assert not marks.describes_mark("gold tooth") and marks.describes_mark("a mole")


def test_mark_is_drawn_on_the_persons_own_side() -> None:
    lm = load_template().landmarks
    img = np.full((512, 512, 3), 255, np.uint8)
    left = marks.draw(img, lm, marks.parse("mole on his left cheek", "mole"))
    ys, xs = np.nonzero(left[:, :, 0] < 128)
    assert len(xs) > 0
    # the person's left cheek is on the right half of the picture, below the eyes
    assert xs.mean() > 256 and 0.45 * 512 < ys.mean() < 0.75 * 512
    right = marks.draw(img, lm, marks.parse("mole on the right cheek", "mole"))
    assert np.nonzero(right[:, :, 0] < 128)[1].mean() < 256


def test_render_is_pencil_on_white_paper() -> None:
    photo = draw_face(512, "medium brown skin, short black hair", seed=3)
    sketch, lines = hand_drawn.render(photo, load_template().landmarks)
    assert sketch.shape == photo.shape and lines.shape == photo.shape
    gray = sketch[:, :, 0].astype(int)
    assert (sketch[:, :, 0] == sketch[:, :, 1]).all()  # graphite: no colour
    assert gray[:20, :20].mean() > 235  # the backdrop is left as paper
    assert gray[200:320, 180:330].std() > 12  # the face is drawn with tone and strokes


def test_frame_head_crops_a_far_away_face() -> None:
    lm = load_template().landmarks * 0.4 + 0.3  # small face in the middle
    img = np.zeros((400, 400, 3), np.uint8)
    out, moved = hand_drawn.frame_head(img, lm)
    assert out.shape == img.shape and moved is not None
    span = moved[:, 1].max() - moved[:, 1].min()
    assert span > (lm[:, 1].max() - lm[:, 1].min()) * 1.5
