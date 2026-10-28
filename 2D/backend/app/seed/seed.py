"""Seed demo data.

    python -m app.seed.seed

Creates officer1 (Jayanagar PS), supervisor1, artist1 and admin1 with random passwords
(printed once), one demo case, one Kannada witness with consent, one active session, and
prints the witness token once. Safe to re-run: existing users are kept and a new case is
added with a fresh number.
"""

from __future__ import annotations

import asyncio
import secrets
import sys
from datetime import UTC, datetime

from app.config import get_settings
from app.container import Container
from app.core.logging import setup_logging
from app.core.security import Principal, hash_password
from app.db.models.users import User
from app.db.repositories import users as user_repo
from app.schemas.cases import CaseCreate, WitnessCreate
from app.services import cases as case_service

STATION = "Jayanagar PS"
JURISDICTION = "Bengaluru South"

USERS = [
    ("officer1", "officer", "Inspector Demo Officer"),
    ("supervisor1", "supervisor", "ACP Demo Supervisor"),
    ("artist1", "artist", "Sketch Artist Demo"),
    ("admin1", "admin", "System Admin"),
]


async def seed() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    container = Container(settings)
    await container.start()
    system = Principal.system()
    created: list[tuple[str, str]] = []
    try:
        async with container.db.session() as db:
            users: dict[str, User] = {}
            for username, role, full_name in USERS:
                existing = await user_repo.get_user_by_username(db, username)
                if existing:
                    users[username] = existing
                    continue
                pw = secrets.token_urlsafe(12)
                u = User(
                    username=username,
                    full_name=full_name,
                    password_hash=hash_password(pw),
                    role=role,
                    station=STATION,
                    jurisdiction=JURISDICTION,
                )
                await user_repo.add_user(db, u)
                users[username] = u
                created.append((username, pw))
            from app.core import audit

            audit.record(
                db,
                system,
                "seed.users",
                object_type="user",
                details={"created": [c[0] for c in created]},
            )
            await audit.commit_with_audit(db)

            officer = users["officer1"]
            actor = Principal(
                kind="user",
                user_id=officer.id,
                role=officer.role,
                station=officer.station,
                jurisdiction=officer.jurisdiction,
                request_id="seed",
            )
            case_number = f"DEMO-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
            case = await case_service.create_case(
                db,
                actor,
                CaseCreate(
                    case_number=case_number,
                    crime_type="theft",
                    location_text="Demo grocery shop, 4th Block Jayanagar",
                    occurred_at=datetime.now(UTC),
                ),
            )
            from app.schemas.cases import AssignmentCreate

            await case_service.assign(
                db,
                actor,
                case.id,
                AssignmentCreate(user_id=users["artist1"].id, role_on_case="artist"),
            )
            witness = await case_service.add_witness(
                db,
                actor,
                case.id,
                WitnessCreate(
                    display_name="Demo Witness (Kannada)",
                    preferred_language="kn",
                    consent_given=True,
                    consent_note="Verbal consent recorded for demo",
                ),
            )
            sess, token = await case_service.create_session(
                db, settings, actor, case.id, witness.id
            )
    finally:
        await container.stop()

    print("\n=== Nishaan seed ===")
    if created:
        print("New users (passwords shown ONCE, store them now):")
        for username, pw in created:
            print(f"  {username:12s} {pw}")
    else:
        print("Users already existed; passwords unchanged.")
    print(f"Case:     {case.case_number}  (id {case.id})")
    print(f"Witness:  {witness.display_name}  (id {witness.id})")
    print(f"Session:  {sess.id}")
    print(f"Witness token (shown once): {token}")
    print("====================\n")


def main() -> int:
    asyncio.run(seed())
    return 0


if __name__ == "__main__":
    sys.exit(main())
