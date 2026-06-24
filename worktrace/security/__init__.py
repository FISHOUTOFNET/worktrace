"""Local security foundations for WorkTrace v0.2."""

from worktrace.security.crypto import CryptoError, decrypt_aead, encrypt_aead, is_encrypted_envelope

__all__ = [
    "CryptoError",
    "decrypt_aead",
    "encrypt_aead",
    "is_encrypted_envelope",
]
