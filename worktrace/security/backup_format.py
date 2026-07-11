from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from worktrace.security.crypto import AES_GCM_ALGORITHM, CryptoError, decrypt_aead, encrypt_aead
from worktrace.security.kdf import KdfError, KdfParams, derive_backup_key


MAGIC = b"WTBACKUP1"
BACKUP_VERSION = 2
SALT_BYTES = 16
MAX_MANIFEST_BYTES = 1024 * 1024


class BackupFormatError(Exception):
    """Raised when a WorkTrace backup cannot be parsed or decrypted."""


@dataclass(frozen=True)
class BackupManifest:
    version: int
    app_version: str
    created_at: str
    kdf: KdfParams
    salt: str
    payload_format: str
    payload_alg: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "app_version": self.app_version,
            "created_at": self.created_at,
            "kdf": self.kdf.to_dict(),
            "salt": self.salt,
            "payload": {
                "format": "wtenc1",
                "alg": self.payload_alg,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BackupManifest":
        if not isinstance(data, dict):
            raise BackupFormatError("Invalid backup manifest")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise BackupFormatError("Invalid backup manifest")
        try:
            manifest = cls(
                version=int(data["version"]),
                app_version=str(data["app_version"]),
                created_at=str(data["created_at"]),
                kdf=KdfParams.from_dict(data["kdf"]),
                salt=str(data["salt"]),
                payload_format=str(payload["format"]),
                payload_alg=str(payload["alg"]),
            )
        except (KeyError, TypeError, ValueError, KdfError) as exc:
            raise BackupFormatError("Invalid backup manifest") from exc
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if self.version != BACKUP_VERSION:
            raise BackupFormatError("Unsupported backup version")
        if self.payload_format != "wtenc1" or self.payload_alg != AES_GCM_ALGORITHM:
            raise BackupFormatError("Unsupported backup payload encryption")
        _decode_salt(self.salt)


def create_encrypted_backup(payload: bytes, passphrase: str, app_version: str) -> bytes:
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if not isinstance(app_version, str):
        raise TypeError("app_version must be a string")

    salt = os.urandom(SALT_BYTES)
    kdf_params = KdfParams()
    manifest = BackupManifest(
        version=BACKUP_VERSION,
        app_version=app_version,
        created_at=_utc_now(),
        kdf=kdf_params,
        salt=_b64(salt),
        payload_format="wtenc1",
        payload_alg=AES_GCM_ALGORITHM,
    )
    manifest_json = _manifest_json(manifest)
    aad = _backup_aad(manifest_json)
    key = derive_backup_key(passphrase, salt, kdf_params)
    envelope = encrypt_aead(payload, aad, key).encode("utf-8")
    return b"\n".join([MAGIC, str(len(manifest_json)).encode("ascii"), manifest_json]) + envelope


def decrypt_encrypted_backup(blob: bytes, passphrase: str) -> bytes:
    manifest, manifest_json, encrypted_payload = _split_backup(blob)
    salt = _decode_salt(manifest.salt)
    try:
        key = derive_backup_key(passphrase, salt, manifest.kdf)
        return decrypt_aead(encrypted_payload.decode("utf-8"), _backup_aad(manifest_json), key)
    except (UnicodeDecodeError, CryptoError, KdfError) as exc:
        raise BackupFormatError("Could not decrypt WorkTrace backup") from exc


def parse_backup_manifest(blob: bytes) -> BackupManifest:
    manifest, _manifest_json, _encrypted_payload = _split_backup(blob)
    return manifest


def _split_backup(blob: bytes) -> tuple[BackupManifest, bytes, bytes]:
    if not isinstance(blob, bytes):
        raise TypeError("blob must be bytes")
    first_newline = blob.find(b"\n")
    if first_newline == -1 or blob[:first_newline] != MAGIC:
        raise BackupFormatError("Invalid WorkTrace backup magic")
    second_newline = blob.find(b"\n", first_newline + 1)
    if second_newline == -1:
        raise BackupFormatError("Invalid WorkTrace backup header")
    try:
        manifest_len = int(blob[first_newline + 1 : second_newline].decode("ascii"))
    except ValueError as exc:
        raise BackupFormatError("Invalid WorkTrace backup manifest length") from exc
    if manifest_len <= 0 or manifest_len > MAX_MANIFEST_BYTES:
        raise BackupFormatError("Invalid WorkTrace backup manifest length")

    manifest_start = second_newline + 1
    manifest_end = manifest_start + manifest_len
    manifest_json = blob[manifest_start:manifest_end]
    encrypted_payload = blob[manifest_end:]
    if len(manifest_json) != manifest_len or not encrypted_payload:
        raise BackupFormatError("Invalid WorkTrace backup body")

    try:
        manifest_data = json.loads(manifest_json.decode("utf-8"))
    except Exception as exc:
        raise BackupFormatError("Invalid WorkTrace backup manifest") from exc
    manifest = BackupManifest.from_dict(manifest_data)
    return manifest, manifest_json, encrypted_payload


def _manifest_json(manifest: BackupManifest) -> bytes:
    return json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")


def _backup_aad(manifest_json: bytes) -> bytes:
    return MAGIC + b"\n" + manifest_json


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode_salt(value: str) -> bytes:
    try:
        salt = base64.b64decode(value.encode("ascii"), validate=True)
    except Exception as exc:
        raise BackupFormatError("Invalid backup salt") from exc
    if len(salt) != SALT_BYTES:
        raise BackupFormatError("Invalid backup salt")
    return salt
