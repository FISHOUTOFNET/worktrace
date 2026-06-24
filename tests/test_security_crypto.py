from __future__ import annotations

import base64
import json
import os

import pytest

from worktrace.security.crypto import CryptoError, decrypt_aead, encrypt_aead, is_encrypted_envelope


def test_aes_gcm_round_trip() -> None:
    key = os.urandom(32)
    aad = b"worktrace:test"
    plaintext = b"sensitive worktrace payload"

    envelope = encrypt_aead(plaintext, aad, key)

    assert decrypt_aead(envelope, aad, key) == plaintext
    assert envelope.startswith("wtenc1:")


def test_same_plaintext_encrypts_to_different_envelopes() -> None:
    key = os.urandom(32)
    plaintext = b"same plaintext"
    aad = b"same aad"

    first = encrypt_aead(plaintext, aad, key)
    second = encrypt_aead(plaintext, aad, key)

    assert first != second


def test_wrong_key_fails() -> None:
    envelope = encrypt_aead(b"secret", b"aad", os.urandom(32))

    with pytest.raises(CryptoError):
        decrypt_aead(envelope, b"aad", os.urandom(32))


def test_wrong_aad_fails() -> None:
    key = os.urandom(32)
    envelope = encrypt_aead(b"secret", b"aad", key)

    with pytest.raises(CryptoError):
        decrypt_aead(envelope, b"other aad", key)


def test_corrupted_ciphertext_fails() -> None:
    key = os.urandom(32)
    envelope = encrypt_aead(b"secret", b"aad", key)
    payload = _decode_envelope_payload(envelope)
    payload["ct"] = payload["ct"][:-1] + ("A" if payload["ct"][-1] != "A" else "B")
    corrupted = "wtenc1:" + _encode_envelope_payload(payload)

    with pytest.raises(CryptoError):
        decrypt_aead(corrupted, b"aad", key)


def test_malformed_envelope_fails() -> None:
    with pytest.raises(CryptoError):
        decrypt_aead("wtenc1:not-json", b"aad", os.urandom(32))

    with pytest.raises(CryptoError):
        decrypt_aead("plaintext", b"aad", os.urandom(32))


def test_is_encrypted_envelope_recognizes_valid_envelope() -> None:
    envelope = encrypt_aead(b"secret", b"aad", os.urandom(32))

    assert is_encrypted_envelope(envelope)
    assert not is_encrypted_envelope("wtenc1:not-json")
    assert not is_encrypted_envelope("plain text")


def test_envelope_does_not_contain_plaintext() -> None:
    plaintext = b"client matter plaintext"
    envelope = encrypt_aead(plaintext, b"aad", os.urandom(32))

    assert plaintext.decode("ascii") not in envelope


def _decode_envelope_payload(envelope: str) -> dict[str, str]:
    encoded = envelope.removeprefix("wtenc1:")
    raw = base64.urlsafe_b64decode((encoded + "=" * (-len(encoded) % 4)).encode("ascii"))
    return json.loads(raw.decode("utf-8"))


def _encode_envelope_payload(payload: dict[str, str]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
