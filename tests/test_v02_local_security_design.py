from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v02_local_security_design_doc_exists() -> None:
    assert (REPO_ROOT / "docs" / "v0.2-local-security-design.md").exists()


def test_v02_local_security_design_doc_covers_required_boundaries() -> None:
    text = (REPO_ROOT / "docs" / "v0.2-local-security-design.md").read_text(
        encoding="utf-8"
    )

    required = [
        "DPAPI",
        "AEAD",
        ".wtbackup",
        "scrypt",
        "Argon2id",
        "no SQLCipher",
        "no AI",
        "no server",
    ]
    for phrase in required:
        assert phrase in text


def test_readme_links_v02_local_security_design() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/v0.2-local-security-design.md" in text
