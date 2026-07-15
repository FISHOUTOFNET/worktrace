from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

BACKUP_KEY_BYTES = 32
MIN_SALT_BYTES = 16
MAX_SCRYPT_N = 2**18
MAX_SCRYPT_R = 32
MAX_SCRYPT_P = 8


class KdfError(Exception):
    """Raised when backup key derivation parameters are invalid."""


@dataclass(frozen=True)
class KdfParams:
    algorithm: str = "scrypt"
    length: int = BACKUP_KEY_BYTES
    n: int = 2**14
    r: int = 8
    p: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "length": self.length,
            "n": self.n,
            "r": self.r,
            "p": self.p,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KdfParams":
        if not isinstance(data, dict):
            raise KdfError("Invalid KDF parameters")
        return cls(
            algorithm=str(data.get("algorithm", "")),
            length=int(data.get("length", 0)),
            n=int(data.get("n", 0)),
            r=int(data.get("r", 0)),
            p=int(data.get("p", 0)),
        )


def derive_backup_key(passphrase: str, salt: bytes, params: KdfParams) -> bytes:
    if not isinstance(passphrase, str):
        raise TypeError("passphrase must be a string")
    if not isinstance(salt, bytes):
        raise TypeError("salt must be bytes")
    if len(salt) < MIN_SALT_BYTES:
        raise KdfError("Backup KDF salt is too short")
    _validate_params(params)

    if params.algorithm != "scrypt":
        raise KdfError("Unsupported backup KDF")

    kdf = Scrypt(
        salt=salt,
        length=params.length,
        n=params.n,
        r=params.r,
        p=params.p,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _validate_params(params: KdfParams) -> None:
    if not isinstance(params, KdfParams):
        raise TypeError("params must be KdfParams")
    if params.algorithm != "scrypt":
        raise KdfError("Unsupported backup KDF")
    if params.length != BACKUP_KEY_BYTES:
        raise KdfError("Unsupported backup key length")
    if params.n < 2**14 or params.n & (params.n - 1) != 0:
        raise KdfError("Invalid scrypt n parameter")
    if params.r < 1 or params.p < 1:
        raise KdfError("Invalid scrypt parameters")
    if (
        params.n > MAX_SCRYPT_N
        or params.r > MAX_SCRYPT_R
        or params.p > MAX_SCRYPT_P
    ):
        raise KdfError("Unsupported scrypt resource parameters")
