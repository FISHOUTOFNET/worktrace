"""Short-lived SQLite persistence for FD Work project bindings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable

FD_WORK_STATE_SCHEMA_VERSION = 1
_BUSY_TIMEOUT_MS = 2500


class FDWorkBindingStoreError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FDWorkProjectBinding:
    project_id: int
    project_created_at: str | None
    bound_name_hash: str
    adapter_contract_version: int
    bound_at: str
    updated_at: str


class FDWorkBindingRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def get_binding(self, project_id: int) -> FDWorkProjectBinding | None:
        if not self.path.exists():
            return None
        try:
            with self._connection(create=False) as connection:
                self._require_schema(connection)
                row = connection.execute(
                    "SELECT * FROM project_binding WHERE project_id = ?",
                    (int(project_id),),
                ).fetchone()
            return self._record(row) if row is not None else None
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def list_bindings(self) -> list[FDWorkProjectBinding]:
        if not self.path.exists():
            return []
        try:
            with self._connection(create=False) as connection:
                self._require_schema(connection)
                rows = connection.execute(
                    "SELECT * FROM project_binding ORDER BY project_id"
                ).fetchall()
            return [self._record(row) for row in rows]
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def bind_project(
        self,
        project_id: int,
        project_created_at: str | None,
        bound_name_hash: str,
        adapter_contract_version: int,
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with self._connection(create=True) as connection:
                self._initialize_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        """
                        INSERT INTO project_binding(
                            project_id, project_created_at, bound_name_hash,
                            adapter_contract_version, bound_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(project_id) DO UPDATE SET
                            project_created_at = excluded.project_created_at,
                            bound_name_hash = excluded.bound_name_hash,
                            adapter_contract_version = excluded.adapter_contract_version,
                            updated_at = excluded.updated_at
                        """,
                        (
                            int(project_id),
                            project_created_at,
                            str(bound_name_hash),
                            int(adapter_contract_version),
                            timestamp,
                            timestamp,
                        ),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def clear_binding(self, project_id: int) -> None:
        self.clear_bindings((project_id,))

    def clear_bindings(self, project_ids: Iterable[int]) -> None:
        ids = sorted({int(project_id) for project_id in project_ids})
        if not ids or not self.path.exists():
            return
        try:
            with self._connection(create=False) as connection:
                self._require_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.executemany(
                        "DELETE FROM project_binding WHERE project_id = ?",
                        ((project_id,) for project_id in ids),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def clear_all(self) -> None:
        if not self.path.exists():
            return
        try:
            with self._connection(create=False) as connection:
                self._require_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute("DELETE FROM project_binding")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def delete_database(self) -> None:
        targets = (
            self.path,
            Path(f"{self.path}-wal"),
            Path(f"{self.path}-shm"),
            Path(f"{self.path}-journal"),
        )
        for target in targets:
            if not target.exists():
                continue
            try:
                target.unlink()
            except OSError as exc:
                raise FDWorkBindingStoreError("binding_store_unavailable") from exc

    def _connection(self, *, create: bool) -> sqlite3.Connection:
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=_BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> FDWorkProjectBinding:
        return FDWorkProjectBinding(
            project_id=int(row["project_id"]),
            project_created_at=(
                str(row["project_created_at"])
                if row["project_created_at"] is not None
                else None
            ),
            bound_name_hash=str(row["bound_name_hash"]),
            adapter_contract_version=int(row["adapter_contract_version"]),
            bound_at=str(row["bound_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _require_schema(connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != FD_WORK_STATE_SCHEMA_VERSION:
            raise FDWorkBindingStoreError("binding_schema_unsupported")

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version == FD_WORK_STATE_SCHEMA_VERSION:
            return
        if version != 0:
            raise FDWorkBindingStoreError("binding_schema_unsupported")
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                CREATE TABLE project_binding (
                    project_id               INTEGER PRIMARY KEY,
                    project_created_at       TEXT NULL,
                    bound_name_hash          TEXT NOT NULL,
                    adapter_contract_version INTEGER NOT NULL,
                    bound_at                 TEXT NOT NULL,
                    updated_at               TEXT NOT NULL
                )
                """
            )
            connection.execute(
                f"PRAGMA user_version = {FD_WORK_STATE_SCHEMA_VERSION}"
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @staticmethod
    def _map_error(exc: sqlite3.Error) -> FDWorkBindingStoreError:
        message = str(exc).casefold()
        if "locked" in message or "busy" in message:
            return FDWorkBindingStoreError("binding_store_busy")
        if "not a database" in message or "malformed" in message or "corrupt" in message:
            return FDWorkBindingStoreError("binding_store_corrupted")
        return FDWorkBindingStoreError("binding_store_unavailable")


__all__ = [
    "FD_WORK_STATE_SCHEMA_VERSION",
    "FDWorkBindingRepository",
    "FDWorkBindingStoreError",
    "FDWorkProjectBinding",
]
