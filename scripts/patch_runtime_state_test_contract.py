from __future__ import annotations

from pathlib import Path

PATH = Path("tests/test_secure_backup_service.py")
OLD = '''        # Runtime-state settings should be re-seeded with defaults.
        for key in ("collector_status", "user_paused", "current_activity_snapshot"):
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            assert row is not None, f"runtime setting {key} missing after import"
'''
NEW = '''        # Durable runtime controls are re-seeded; the live activity sample is
        # process-local and must not be recreated as a SQLite setting.
        for key in ("collector_status", "user_paused"):
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            assert row is not None, f"runtime setting {key} missing after import"
        snapshot_row = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            ("current_activity_snapshot",),
        ).fetchone()
        assert snapshot_row is None
'''


def main() -> None:
    source = PATH.read_text(encoding="utf-8")
    count = source.count(OLD)
    if count != 1:
        raise SystemExit(f"expected one backup test contract, found {count}")
    PATH.write_text(source.replace(OLD, NEW), encoding="utf-8")


if __name__ == "__main__":
    main()
