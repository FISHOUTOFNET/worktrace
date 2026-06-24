from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ENVELOPE_PREFIX = "wtenc1:"
ENVELOPE_VERSION = 1
AES_GCM_ALGORITHM = "AES-256-GCM"
AES_GCM_KEY_BYTES = 32
AES_GCM_NONCE_BYTES = 12


class CryptoError(Exception):
    """Raised when encryption or decryption cannot be completed safely."""


def encrypt_aead(plaintext: bytes, aad: bytes, key: bytes) -> str:
    _require_bytes("plaintext", plaintext)
    _require_bytes("aad", aad)
    _validate_key(key)

    nonce = os.urandom(AES_GCM_NONCE_BYTES)
    try:
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    except Exception as exc:  # pragma: no cover - defensive; AESGCM rarely fails here.
        raise CryptoError("AEAD encryption failed") from exc

    envelope = {
        "v": ENVELOPE_VERSION,
        "alg": AES_GCM_ALGORITHM,
        "nonce": _b64url_encode(nonce),
        "ct": _b64url_encode(ciphertext),
    }
    encoded = _b64url_encode(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return f"{ENVELOPE_PREFIX}{encoded}"


def decrypt_aead(envelope: str, aad: bytes, key: bytes) -> bytes:
    _require_bytes("aad", aad)
    _validate_key(key)

    try:
        parsed = _parse_envelope(envelope)
        nonce = _b64url_decode(parsed["nonce"])
        ciphertext = _b64url_decode(parsed["ct"])
    except Exception as exc:
        raise CryptoError("Malformed encrypted envelope") from exc

    if len(nonce) != AES_GCM_NONCE_BYTES:
        raise CryptoError("Malformed encrypted envelope")

    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise CryptoError("AEAD decryption failed") from exc
    except Exception as exc:
        raise CryptoError("AEAD decryption failed") from exc


def is_encrypted_envelope(value: str) -> bool:
    if not isinstance(value, str) or not value.startswith(ENVELOPE_PREFIX):
        return False
    try:
        _parse_envelope(value)
    except CryptoError:
        return False
    return True


def _parse_envelope(value: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value.startswith(ENVELOPE_PREFIX):
        raise CryptoError("Malformed encrypted envelope")

    encoded = value[len(ENVELOPE_PREFIX) :]
    try:
        raw = _b64url_decode(encoded)
        parsed = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CryptoError("Malformed encrypted envelope") from exc

    if not isinstance(parsed, dict):
        raise CryptoError("Malformed encrypted envelope")
    if parsed.get("v") != ENVELOPE_VERSION or parsed.get("alg") != AES_GCM_ALGORITHM:
        raise CryptoError("Unsupported encrypted envelope")
    if not isinstance(parsed.get("nonce"), str) or not isinstance(parsed.get("ct"), str):
        raise CryptoError("Malformed encrypted envelope")
    return parsed


def _validate_key(key: bytes) -> None:
    _require_bytes("key", key)
    if len(key) != AES_GCM_KEY_BYTES:
        raise CryptoError("Invalid AEAD key")


def _require_bytes(name: str, value: bytes) -> None:
    if not isinstance(value, bytes):
        raise TypeError(f"{name} must be bytes")


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError("base64url value must be a string")
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
