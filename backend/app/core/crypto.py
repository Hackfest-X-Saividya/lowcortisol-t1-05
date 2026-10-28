"""AES-256-GCM file encryption with a per-file key derived via HKDF.

Blob layout on disk: ``nonce (12 bytes) || ciphertext+tag``. The file id is used both as
HKDF ``info`` and as GCM associated data, so a blob cannot be swapped between file ids.
"""

from __future__ import annotations

import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

NONCE_LEN = 12


class DecryptionError(Exception):
    pass


def derive_file_key(master_key: bytes, file_id: str) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"nishaan-file-store-v1",
        info=file_id.encode("utf-8"),
    )
    return hkdf.derive(master_key)


def encrypt_bytes(master_key: bytes, file_id: str, plaintext: bytes) -> bytes:
    key = derive_file_key(master_key, file_id)
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, file_id.encode("utf-8"))
    return nonce + ct


def decrypt_bytes(master_key: bytes, file_id: str, blob: bytes) -> bytes:
    if len(blob) < NONCE_LEN + 16:
        raise DecryptionError("blob too short")
    key = derive_file_key(master_key, file_id)
    nonce, ct = blob[:NONCE_LEN], blob[NONCE_LEN:]
    try:
        return AESGCM(key).decrypt(nonce, ct, file_id.encode("utf-8"))
    except InvalidTag as exc:
        raise DecryptionError("authentication failed (tampered or wrong key)") from exc


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
