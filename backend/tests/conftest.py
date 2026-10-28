"""Shared fixtures. Mock mode, no network, jobs run inline, fresh SQLite per test."""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

# ---- environment: must be set before app modules are imported ------------------------------
TEST_ENV = {
    "AI_MODE": "mock",
    "APP_ENV": "test",
    "JOBS_INLINE": "true",
    "PROVIDER_CACHE": "true",
    "LOG_LEVEL": "WARNING",
    "AUTO_CREATE_DB": "true",
    "JWT_SECRET": "test-secret-not-for-production-0123456789",
    "FILE_MASTER_KEY_B64": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
    "GEMINI_API_KEY": "",
    "GROQ_API_KEY": "",
    "CLOUDFLARE_ACCOUNT_ID": "",
    "CLOUDFLARE_API_TOKEN": "",
    "WARP_INTERNAL_PX": "512",
}
for k, v in TEST_ENV.items():
    os.environ[k] = v

from app.config import Settings, get_settings  # noqa: E402
from app.container import Container  # noqa: E402
from app.core.security import Principal, hash_password  # noqa: E402
from app.db.models.users import User  # noqa: E402
from app.main import create_app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


# ---- block network ---------------------------------------------------------------------------
class _NoNetwork(Exception):
    pass


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any real socket connection; respx-mocked httpx calls never reach sockets."""
    real_connect = socket.socket.connect

    def guard(self: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address)
        raise _NoNetwork(f"network access blocked in tests: {address}")

    monkeypatch.setattr(socket.socket, "connect", guard)


# ---- settings / container -----------------------------------------------------------------------
@pytest.fixture()
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("FILE_STORE_DIR", str(tmp_path / "files"))
    get_settings.cache_clear()
    s = get_settings()
    yield s  # type: ignore[misc]
    get_settings.cache_clear()


@pytest.fixture()
async def container(settings: Settings) -> AsyncIterator[Container]:
    c = Container(settings)
    await c.start()
    yield c
    await c.stop()


@pytest.fixture()
async def client(settings: Settings, container: Container) -> AsyncIterator[httpx.AsyncClient]:
    from app.core.ratelimit import limiter

    limiter.reset()  # the in-memory rate-limit counters are process-global
    app = create_app(settings, container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        async with app.router.lifespan_context(app):
            yield c


# ---- users -----------------------------------------------------------------------------------
PASSWORD = "Str0ngPassw0rd!"


async def make_user(
    container: Container,
    username: str,
    role: str,
    station: str = "Jayanagar PS",
    jurisdiction: str = "Bengaluru South",
) -> User:
    async with container.db.session() as db:
        u = User(
            username=username,
            full_name=username.title(),
            password_hash=hash_password(PASSWORD),
            role=role,
            station=station,
            jurisdiction=jurisdiction,
        )
        db.add(u)
        await db.commit()
        return u


@pytest.fixture()
async def users(container: Container) -> dict[str, User]:
    return {
        "officer": await make_user(container, "officer1", "officer"),
        "officer2": await make_user(container, "officer2", "officer"),
        "supervisor": await make_user(container, "supervisor1", "supervisor"),
        "artist": await make_user(container, "artist1", "artist"),
        "admin": await make_user(container, "admin1", "admin"),
        "other_station": await make_user(
            container, "officer3", "officer", station="Other PS", jurisdiction="Mysuru"
        ),
    }


async def login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def witness_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def principal_officer(users: dict[str, User]) -> Principal:
    u = users["officer"]
    return Principal(
        kind="user", user_id=u.id, role="officer", station=u.station, jurisdiction=u.jurisdiction
    )


async def setup_session(
    client: httpx.AsyncClient, headers: dict[str, str], language: str = "en"
) -> dict[str, Any]:
    """Create case, witness and session; returns ids, witness token and headers."""
    r = await client.post(
        "/api/v1/cases",
        json={"case_number": "CR-1", "crime_type": "theft", "location_text": "shop"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    case = r.json()
    r = await client.post(
        f"/api/v1/cases/{case['id']}/witnesses",
        json={
            "display_name": "W1",
            "preferred_language": language,
            "consent_given": True,
            "consent_note": "verbal",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    witness = r.json()
    r = await client.post(
        f"/api/v1/cases/{case['id']}/sessions", json={"witness_id": witness["id"]}, headers=headers
    )
    assert r.status_code == 201, r.text
    data = r.json()
    return {
        "case": case,
        "witness": witness,
        "session": data["session"],
        "session_id": data["session"]["id"],
        "witness_token": data["witness_token"],
        "witness_headers": witness_headers(data["witness_token"]),
        "officer_headers": headers,
    }


def fake_wav(marker: str | None = None, seconds: float = 1.0) -> bytes:
    """A tiny valid-looking WAV (RIFF header) with an optional mock-ASR marker."""
    import struct

    rate = 8000
    n = int(rate * seconds)
    data = b"\x00\x00" * n
    if marker:
        data = data[: len(data) // 2] + f"nishaan-mock:{marker}".encode() + data[len(data) // 2 :]
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data
