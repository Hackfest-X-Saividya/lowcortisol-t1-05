from __future__ import annotations

import os

import pytest

from app.core.crypto import DecryptionError, decrypt_bytes, derive_file_key, encrypt_bytes


def test_round_trip_and_distinct_keys() -> None:
    master = os.urandom(32)
    data = b"hello nishaan" * 100
    blob = encrypt_bytes(master, "file-a", data)
    assert blob != data
    assert decrypt_bytes(master, "file-a", blob) == data
    assert derive_file_key(master, "file-a") != derive_file_key(master, "file-b")


def test_tampered_ciphertext_fails() -> None:
    master = os.urandom(32)
    blob = bytearray(encrypt_bytes(master, "f", b"secret payload"))
    blob[20] ^= 0x01
    with pytest.raises(DecryptionError):
        decrypt_bytes(master, "f", bytes(blob))


def test_wrong_file_id_or_key_fails() -> None:
    master = os.urandom(32)
    blob = encrypt_bytes(master, "f1", b"x" * 50)
    with pytest.raises(DecryptionError):
        decrypt_bytes(master, "f2", blob)
    with pytest.raises(DecryptionError):
        decrypt_bytes(os.urandom(32), "f1", blob)
    with pytest.raises(DecryptionError):
        decrypt_bytes(master, "f1", b"short")


@pytest.mark.asyncio
async def test_file_store_round_trip(container) -> None:  # type: ignore[no-untyped-def]
    from app.services.storage import sniff_audio, sniff_image

    async with container.db.session() as db:
        rec = await container.files.save(
            db, b"\x89PNG\r\n\x1a\n" + b"abc", kind="preview", mime="image/png"
        )
        await db.commit()
        got, data = await container.files.load(db, rec.id)
        assert data.startswith(b"\x89PNG") and got.size_bytes == 11
        raw = (container.files.root / rec.storage_path).read_bytes()
        assert b"abc" not in raw  # encrypted at rest
    assert sniff_image(b"\x89PNG\r\n\x1a\n...") == "image/png"
    assert sniff_image(b"\xff\xd8\xff\xe0...") == "image/jpeg"
    assert sniff_audio(b"OggS....") == "audio/ogg"
    assert sniff_audio(b"\x1a\x45\xdf\xa3....") == "audio/webm"
    assert sniff_audio(b"RIFF\x00\x00\x00\x00WAVEfmt ") == "audio/wav"
    assert sniff_audio(b"ID3\x03....") == "audio/mpeg"
    assert sniff_audio(b"\x00\x00\x00\x18ftypM4A ....") == "audio/mp4"
    assert sniff_audio(b"not audio at all") is None
