from __future__ import annotations

import base64
import json

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.security_privacy, pytest.mark.parallel_safe]

from worktrace.security.backup_format import (
    BackupFormatError,
    BackupManifest,
    create_encrypted_backup,
    decrypt_encrypted_backup,
    parse_backup_manifest,
)


def test_create_decrypt_wtbackup_round_trip() -> None:
    payload = b'{"records":[{"title":"client matter"}]}'
    blob = create_encrypted_backup(payload, "correct horse", "0.2-test")

    assert blob.startswith(b"WTBACKUP1\n")
    assert decrypt_encrypted_backup(blob, "correct horse") == payload


def test_wrong_passphrase_fails() -> None:
    blob = create_encrypted_backup(b"secret payload", "right passphrase", "0.2-test")

    with pytest.raises(BackupFormatError):
        decrypt_encrypted_backup(blob, "wrong passphrase")


def test_corrupted_backup_fails() -> None:
    blob = bytearray(create_encrypted_backup(b"secret payload", "passphrase", "0.2-test"))
    blob[-3] = blob[-3] ^ 1

    with pytest.raises(BackupFormatError):
        decrypt_encrypted_backup(bytes(blob), "passphrase")


def test_manifest_is_parseable() -> None:
    blob = create_encrypted_backup(b"payload", "passphrase", "0.2-test")

    manifest = parse_backup_manifest(blob)

    assert isinstance(manifest, BackupManifest)
    assert manifest.version == 1
    assert manifest.app_version == "0.2-test"
    assert manifest.kdf.algorithm == "scrypt"
    assert manifest.payload_format == "wtenc1"


def test_manifest_does_not_contain_payload_plaintext() -> None:
    payload = b"client matter plaintext"
    blob = create_encrypted_backup(payload, "passphrase", "0.2-test")
    manifest_json, _encrypted_payload = _split_manifest_and_payload(blob)

    assert payload not in manifest_json
    assert payload not in blob


def test_different_exports_use_different_salt_and_nonce() -> None:
    payload = b"same payload"
    first = create_encrypted_backup(payload, "passphrase", "0.2-test")
    second = create_encrypted_backup(payload, "passphrase", "0.2-test")

    first_manifest = parse_backup_manifest(first)
    second_manifest = parse_backup_manifest(second)
    _first_manifest_json, first_payload = _split_manifest_and_payload(first)
    _second_manifest_json, second_payload = _split_manifest_and_payload(second)

    assert first_manifest.salt != second_manifest.salt
    assert _payload_nonce(first_payload) != _payload_nonce(second_payload)


def test_decrypted_payload_matches_original() -> None:
    payload = b'{"test": true, "items": [1, 2, 3]}'
    blob = create_encrypted_backup(payload, "passphrase", "0.2-test")

    assert decrypt_encrypted_backup(blob, "passphrase") == payload


def _split_manifest_and_payload(blob: bytes) -> tuple[bytes, bytes]:
    first = blob.find(b"\n")
    second = blob.find(b"\n", first + 1)
    manifest_len = int(blob[first + 1 : second].decode("ascii"))
    start = second + 1
    end = start + manifest_len
    return blob[start:end], blob[end:]


def _payload_nonce(payload: bytes) -> str:
    envelope = payload.decode("utf-8")
    encoded = envelope.removeprefix("wtenc1:")
    raw = base64.urlsafe_b64decode((encoded + "=" * (-len(encoded) % 4)).encode("ascii"))
    data = json.loads(raw.decode("utf-8"))
    return data["nonce"]
