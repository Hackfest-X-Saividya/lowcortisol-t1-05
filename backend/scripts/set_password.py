"""Set (reset) a user's password and clear any login lock.

Run:  python scripts/set_password.py <username> <new-password>
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.repositories import users as user_repo  # noqa: E402
from app.db.session import Database, commit_tx  # noqa: E402


async def run(username: str, password: str) -> int:
    if len(password) < 8:
        print("password must be at least 8 characters")
        return 2
    db = Database(settings=get_settings())
    try:
        async with db.session() as session:
            user = await user_repo.get_user_by_username(session, username)
            if user is None:
                print(f"no such user: {username}")
                return 1
            user.password_hash = hash_password(password)
            user.failed_logins = 0
            user.locked_until = None
            user.is_active = True
            await commit_tx(session)
    finally:
        await db.dispose()
    print(f"password updated for {username}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(run(sys.argv[1], sys.argv[2])))
