"""Draw placeholder accessory PNGs and write assets/overlays/anchors.json.

Run:  python scripts/make_placeholder_overlays.py
Replace the PNGs with better art; keep the anchor pixel positions in anchors.json valid.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.sketch.overlay_assets import CATALOG, write_placeholders  # noqa: E402


def main() -> int:
    out = ROOT / "assets" / "overlays"
    path = write_placeholders(out)
    print(f"wrote {len(CATALOG)} overlays and {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
