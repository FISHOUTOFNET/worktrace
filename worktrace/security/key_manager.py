from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


DATA_KEY_BYTES = 32
KEYRING_VERSION = 1
DPAPI_WRAP_TYPE = "dpapi-current-user"
FAKE_WRAP_TYPE = "fake-test-wrapper"


class KeyManagerError(Exception):
    """Raised when a local data key cannot be created or loaded."""


@dataclass(frozen=True)
class LocalKey:
    key_id: str
    key: bytes
    created_at: str
    wrap_type: str


class KeyWrapper(Protocol):
    wrap_type: str

    def wrap(self, data: bytes) -> bytes: ...

    def unwrap(self, wrapped: bytes) -> bytes: ...


class DpapiKeyWrapper:
    wrap_type = DPAPI_WRAP_TYPE

    def wrap(self, data: bytes) -> bytes:
        try:
            import win32crypt
        except ImportError as exc:  # pragma: no cover - Windows runtime dependency.
            raise KeyManagerError("Windows DPAPI is unavailable") from exc
        return win32crypt.CryptProtectData(
            data,
            "WorkTrace local data key",
            None,
            None,
            None,
            0,
        )

    def unwrap(self, wrapped: bytes) -> bytes:
        try:
            import win32crypt
        except ImportError as exc:  # pragma: no cover - Windows runtime dependency.
            raise KeyManagerError("Windows DPAPI is unavailable") from exc
        try:
            _description, data = win32crypt.CryptUnprotectData(
                wrapped,
                None,
                None,
                None,
                0,
            )
            return data
        except Exception as exc:
            raise KeyManagerError("Could not unwrap local data key") from exc


class FakeKeyWrapper:
    """Deterministic wrapper available only through explicit test injection."""

    wrap_type = FAKE_WRAP_TYPE

    def __init__(self, secret: bytes = b"worktrace-fake-key-wrapper") -> None:
        self._mask = hashlib.sha256(secret).digest()

    def wrap(self, data: bytes) -> bytes:
        return b"fake1:" + _xor(data, self._mask)

    def unwrap(self, wrapped: bytes) -> bytes:
        prefix = b"fake1:"
        if not wrapped.startswith(prefix):
            raise KeyManagerError("Unsupported fake wrapped key")
        return _xor(wrapped[len(prefix) :], self._mask)


def create_or_load_local_key(
    *,
    path: Path | None = None,
    wrapper: KeyWrapper | None = None,
) -> LocalKey:
    keyring_path = path or default_keyring_path()
    active_wrapper = wrapper if wrapper is not None else _default_wrapper()
    if keyring_path.exists():
        return load_local_key(path=keyring_path, wrapper=active_wrapper)

    key = os.urandom(DATA_KEY_BYTES)
    created_at = _utc_now()
    key_id = str(uuid.uuid4())
    wrapped = active_wrapper.wrap(key)
    keyring = {
        "version": KEYRING_VERSION,
        "active_key_id": key_id,
        "keys": [
            {
                "key_id": key_id,
                "wrapped_data_key": _b64(wrapped),
                "wrap_type": active_wrapper.wrap_type,
                "created_at": created_at,
            }
        ],
    }
    keyring_path.parent.mkdir(parents=True, exist_ok=True)
    keyring_path.write_text(
        json.dumps(keyring, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return LocalKey(
        key_id=key_id,
        key=key,
        created_at=created_at,
        wrap_type=active_wrapper.wrap_type,
    )


def load_local_key(
    *,
    path: Path | None = None,
    wrapper: KeyWrapper | None = None,
) -> LocalKey:
    keyring_path = path or default_keyring_path()
    active_wrapper = wrapper if wrapper is not None else _default_wrapper()
    try:
        keyring = json.loads(keyring_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KeyManagerError("Local keyring does not exist") from exc
    except Exception as exc:
        raise KeyManagerError("Could not read local keyring") from exc

    entry = _active_key_entry(keyring)
    if entry.get("wrap_type") != active_wrapper.wrap_type:
        raise KeyManagerError("Local keyring wrap type mismatch")

    try:
        key = active_wrapper.unwrap(_unb64(str(entry["wrapped_data_key"])))
    except Exception as exc:
        raise KeyManagerError("Could not unwrap local data key") from exc
    if len(key) != DATA_KEY_BYTES:
        raise KeyManagerError("Invalid local data key")

    return LocalKey(
        key_id=str(entry["key_id"]),
        key=key,
        created_at=str(entry["created_at"]),
        wrap_type=str(entry["wrap_type"]),
    )


def keyring_exists(path: Path | None = None) -> bool:
    return (path or default_keyring_path()).exists()


def default_keyring_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / "AppData" / "Local"
    return base / "WorkTrace" / "security" / "keyring.json"


def _default_wrapper() -> KeyWrapper:
    if platform.system() != "Windows":
        raise KeyManagerError("unsupported_platform")
    return DpapiKeyWrapper()


def _active_key_entry(keyring: object) -> dict[str, object]:
    if not isinstance(keyring, dict) or keyring.get("version") != KEYRING_VERSION:
        raise KeyManagerError("Unsupported local keyring")
    active_key_id = keyring.get("active_key_id")
    keys = keyring.get("keys")
    if not isinstance(active_key_id, str) or not isinstance(keys, list):
        raise KeyManagerError("Malformed local keyring")
    for entry in keys:
        if isinstance(entry, dict) and entry.get("key_id") == active_key_id:
            if not isinstance(entry.get("wrapped_data_key"), str):
                raise KeyManagerError("Malformed local keyring")
            return entry
    raise KeyManagerError("Active local key was not found")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def _xor(data: bytes, mask: bytes) -> bytes:
    return bytes(byte ^ mask[index % len(mask)] for index, byte in enumerate(data))


__all__ = [
    "DATA_KEY_BYTES",
    "DPAPI_WRAP_TYPE",
    "FAKE_WRAP_TYPE",
    "KEYRING_VERSION",
    "DpapiKeyWrapper",
    "FakeKeyWrapper",
    "KeyManagerError",
    "KeyWrapper",
    "LocalKey",
    "create_or_load_local_key",
    "default_keyring_path",
    "keyring_exists",
    "load_local_key",
]
