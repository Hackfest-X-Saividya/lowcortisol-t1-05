"""Recompute the audit hash chain and report the first broken row.

Run:  python scripts/verify_audit_chain.py
Exit code 0 when the chain verifies, 1 when a row is broken, 2 on errors.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.core.audit import verify_chain  # noqa: E402
from app.db.session import Database  # noqa: E402


async def run() -> int:
    settings = get_settings()
    db = Database(settings=settings)
    try:
        async with db.session() as session:
            result = await verify_chain(session)
    finally:
        await db.dispose()
    if result.ok:
        print(f"ok: {result.checked} audit entries verified")
        return 0
    print(
        f"BROKEN: first bad entry id={result.first_broken_id} ({result.reason}); "
        f"{result.checked} entries verified before it"
    )
    return 1


def main() -> int:
    try:
        return asyncio.run(run())
    except Exception as exc:  # noqa: BLE001
        print(f"failed: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
