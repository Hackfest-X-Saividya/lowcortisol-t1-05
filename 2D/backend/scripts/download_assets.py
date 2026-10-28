"""Download the MediaPipe Face Landmarker model and the Noto fonts into assets/.

Run:  python scripts/download_assets.py

Every file comes from an official location (Google's MediaPipe model bucket and the
notofonts GitHub organisation). Each entry lists a primary URL and fallbacks; the
script prints where each file came from. Re-running skips files that already exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# (destination, [urls...])
FILES: list[tuple[Path, list[str]]] = [
    (
        ASSETS / "models" / "face_landmarker.task",
        [
            "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
            "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
        ],
    ),
    (
        ASSETS / "fonts" / "NotoSans-Regular.ttf",
        [
            "https://github.com/notofonts/latin-greek-cyrillic/raw/main/fonts/NotoSans/hinted/ttf/NotoSans-Regular.ttf",
            "https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts/NotoSans/hinted/ttf/NotoSans-Regular.ttf",
            "https://cdn.jsdelivr.net/gh/notofonts/notofonts.github.io/fonts/NotoSans/hinted/ttf/NotoSans-Regular.ttf",
        ],
    ),
    (
        ASSETS / "fonts" / "NotoSansDevanagari-Regular.ttf",
        [
            "https://github.com/notofonts/devanagari/raw/main/fonts/NotoSansDevanagari/hinted/ttf/NotoSansDevanagari-Regular.ttf",
            "https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts/NotoSansDevanagari/hinted/ttf/NotoSansDevanagari-Regular.ttf",
            "https://cdn.jsdelivr.net/gh/notofonts/notofonts.github.io/fonts/NotoSansDevanagari/hinted/ttf/NotoSansDevanagari-Regular.ttf",
        ],
    ),
    (
        ASSETS / "fonts" / "NotoSansKannada-Regular.ttf",
        [
            "https://github.com/notofonts/kannada/raw/main/fonts/NotoSansKannada/hinted/ttf/NotoSansKannada-Regular.ttf",
            "https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts/NotoSansKannada/hinted/ttf/NotoSansKannada-Regular.ttf",
            "https://cdn.jsdelivr.net/gh/notofonts/notofonts.github.io/fonts/NotoSansKannada/hinted/ttf/NotoSansKannada-Regular.ttf",
        ],
    ),
]


def fetch(url: str) -> bytes | None:
    try:
        with httpx.Client(follow_redirects=True, timeout=120) as client:
            r = client.get(url)
            if r.status_code == 200 and len(r.content) > 10_000:
                return r.content
            print(f"   {url} -> HTTP {r.status_code} ({len(r.content)} bytes)")
    except httpx.HTTPError as exc:
        print(f"   {url} -> {type(exc).__name__}: {exc}")
    return None


def main() -> int:
    failures = 0
    for dest, urls in FILES:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 10_000:
            print(f"ok   {dest.relative_to(ROOT)} (already present)")
            continue
        got = False
        for url in urls:
            data = fetch(url)
            if data:
                dest.write_bytes(data)
                print(f"ok   {dest.relative_to(ROOT)} <- {url} ({len(data)} bytes)")
                got = True
                break
        if not got:
            failures += 1
            print(f"FAIL {dest.relative_to(ROOT)} (all sources failed)")
    if failures:
        print(
            f"{failures} file(s) could not be downloaded. The app still runs: the sketch "
            "pipeline falls back to template landmarks and the PDF to a built-in font."
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
