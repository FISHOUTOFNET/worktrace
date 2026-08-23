"""Short-lived SQLite persistence for FD Work project bindings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable

FD_WORK_STATE_SCHEMA_VERSION = 2
_BUSY_TIMEOUT_MS = 2500
_OPERATION_KINDS = frozenset({"create", "rebind"})
_OPERATION_STAGES = frozenset(
    {
        "prepared",
        "project_created",
        "project_updated",
        "binding_written",
        "recovery_identity_mismatch",
        "recovery_identity_unproven",
        "recovery_ambiguous",
    }
)


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


@dataclass(frozen=True)
class PendingBindingOperation:
    operation_id: str
    operation_kind: str
    intended_name_hash: str
    started_at: str
    project_id: int | None
    project_created_at: str | None
    previous_name_hash: str | None
    stage: str
    updated_at: str


class FDWorkBindingRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def get_binding(self, project_id: int) -> FDWorkProjectBinding | None:
        if not self.path.exists():
            return None
        try:
            with self._connection(create=False) as connection:
                self._initialize_schema(connection)
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
                self._initialize_schema(connection)
                rows = connection.execute(
                    "SELECT * FROM project_binding ORDER BY project_id"
                ).fetchall()
            return [self._record(row) for row in rows]
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def assert_writable(self) -> None:
        try:
            with self._connection(create=True) as connection:
                self._initialize_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def begin_pending_operation(
        self,
        operation_id: str,
        operation_kind: str,
        intended_name_hash: str,
        *,
        previous_name_hash: str | None = None,
        started_at: str | None = None,
    ) -> None:
        self._validate_operation_id(operation_id)
        self._validate_operation_kind(operation_kind)
        self._validate_hash(intended_name_hash)
        if previous_name_hash is not None:
            self._validate_hash(previous_name_hash)
        timestamp = started_at or self._timestamp()
        self._validate_timestamp(timestamp)
        try:
            with self._connection(create=True) as connection:
                self._initialize_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        """
                        INSERT INTO pending_binding_operation(
                            operation_id, operation_kind, intended_name_hash,
                            started_at, project_id, project_created_at,
                            previous_name_hash, stage, updated_at
                        ) VALUES (?, ?, ?, ?, NULL, NULL, ?, 'prepared', ?)
                        """,
                        (
                            operation_id,
                            operation_kind,
                            intended_name_hash,
                            timestamp,
                            previous_name_hash,
                            timestamp,
                        ),
                    )
                    connection.commit()
                except sqlite3.IntegrityError as exc:
                    connection.rollback()
                    raise FDWorkBindingStoreError(
                        "pending_operation_conflict"
                    ) from exc
                except Exception:
                    connection.rollback()
                    raise
        except FDWorkBindingStoreError:
            raise
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def get_pending_operation(
        self,
        operation_id: str,
    ) -> PendingBindingOperation | None:
        self._validate_operation_id(operation_id)
        if not self.path.exists():
            return None
        try:
            with self._connection(create=False) as connection:
                self._initialize_schema(connection)
                row = connection.execute(
                    "SELECT * FROM pending_binding_operation WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
            return self._pending_record(row) if row is not None else None
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def list_pending_operations(self) -> list[PendingBindingOperation]:
        if not self.path.exists():
            return []
        try:
            with self._connection(create=False) as connection:
                self._initialize_schema(connection)
                rows = connection.execute(
                    """
                    SELECT * FROM pending_binding_operation
                    ORDER BY started_at, operation_id
                    """
                ).fetchall()
            return [self._pending_record(row) for row in rows]
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def record_pending_project(
        self,
        operation_id: str,
        project_id: int,
        project_created_at: str,
        stage: str,
    ) -> None:
        self._validate_operation_id(operation_id)
        self._validate_stage(stage)
        self._validate_timestamp(project_created_at)
        if type(project_id) is not int or project_id <= 0:
            raise FDWorkBindingStoreError("pending_operation_invalid")
        timestamp = self._timestamp()
        try:
            with self._connection(create=False) as connection:
                self._initialize_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    cursor = connection.execute(
                        """
                        UPDATE pending_binding_operation
                        SET project_id = ?, project_created_at = ?, stage = ?, updated_at = ?
                        WHERE operation_id = ?
                        """,
                        (
                            int(project_id),
                            project_created_at,
                            stage,
                            timestamp,
                            operation_id,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise FDWorkBindingStoreError("pending_operation_missing")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except FDWorkBindingStoreError:
            raise
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def set_pending_stage(self, operation_id: str, stage: str) -> None:
        self._validate_operation_id(operation_id)
        self._validate_stage(stage)
        timestamp = self._timestamp()
        try:
            with self._connection(create=False) as connection:
                self._initialize_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    cursor = connection.execute(
                        """
                        UPDATE pending_binding_operation
                        SET stage = ?, updated_at = ?
                        WHERE operation_id = ?
                        """,
                        (stage, timestamp, operation_id),
                    )
                    if cursor.rowcount != 1:
                        raise FDWorkBindingStoreError("pending_operation_missing")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except FDWorkBindingStoreError:
            raise
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def delete_pending_operation(self, operation_id: str) -> None:
        self._validate_operation_id(operation_id)
        if not self.path.exists():
            return
        try:
            with self._connection(create=False) as connection:
                self._initialize_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        "DELETE FROM pending_binding_operation WHERE operation_id = ?",
                        (operation_id,),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def complete_pending_with_binding(
        self,
        operation_id: str,
        *,
        project_id: int,
        project_created_at: str | None,
        bound_name_hash: str,
        adapter_contract_version: int,
    ) -> None:
        self._validate_operation_id(operation_id)
        self._validate_hash(bound_name_hash)
        if type(project_id) is not int or project_id <= 0:
            raise FDWorkBindingStoreError("pending_operation_invalid")
        if project_created_at is not None:
            self._validate_timestamp(project_created_at)
        timestamp = self._timestamp()
        try:
            with self._connection(create=False) as connection:
                self._initialize_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    pending = connection.execute(
                        "SELECT * FROM pending_binding_operation WHERE operation_id = ?",
                        (operation_id,),
                    ).fetchone()
                    if pending is None:
                        raise FDWorkBindingStoreError("pending_operation_missing")
                    if (
                        str(pending["intended_name_hash"]) != bound_name_hash
                        or pending["project_id"] is not None
                        and int(pending["project_id"]) != int(project_id)
                        or pending["project_created_at"] is not None
                        and str(pending["project_created_at"]) != project_created_at
                    ):
                        raise FDWorkBindingStoreError("pending_identity_mismatch")
                    self._upsert_binding(
                        connection,
                        project_id,
                        project_created_at,
                        bound_name_hash,
                        adapter_contract_version,
                        timestamp,
                    )
                    connection.execute(
                        "DELETE FROM pending_binding_operation WHERE operation_id = ?",
                        (operation_id,),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except FDWorkBindingStoreError:
            raise
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
                    self._upsert_binding(
                        connection,
                        project_id,
                        project_created_at,
                        bound_name_hash,
                        adapter_contract_version,
                        timestamp,
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def clear_binding(self, project_id: int) -> None:
        self.clear_bindings((project_id,))

    def clear_project_state(self, project_id: int) -> None:
        if not self.path.exists():
            return
        try:
            with self._connection(create=False) as connection:
                self._initialize_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        "DELETE FROM project_binding WHERE project_id = ?",
                        (int(project_id),),
                    )
                    connection.execute(
                        "DELETE FROM pending_binding_operation WHERE project_id = ?",
                        (int(project_id),),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except sqlite3.Error as exc:
            raise self._map_error(exc) from exc

    def clear_bindings(self, project_ids: Iterable[int]) -> None:
        ids = sorted({int(project_id) for project_id in project_ids})
        if not ids or not self.path.exists():
            return
        try:
            with self._connection(create=False) as connection:
                self._initialize_schema(connection)
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
                self._initialize_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute("DELETE FROM project_binding")
                    connection.execute("DELETE FROM pending_binding_operation")
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
    def _pending_record(row: sqlite3.Row) -> PendingBindingOperation:
        return PendingBindingOperation(
            operation_id=str(row["operation_id"]),
            operation_kind=str(row["operation_kind"]),
            intended_name_hash=str(row["intended_name_hash"]),
            started_at=str(row["started_at"]),
            project_id=(int(row["project_id"]) if row["project_id"] is not None else None),
            project_created_at=(
                str(row["project_created_at"])
                if row["project_created_at"] is not None
                else None
            ),
            previous_name_hash=(
                str(row["previous_name_hash"])
                if row["previous_name_hash"] is not None
                else None
            ),
            stage=str(row["stage"]),
            updated_at=str(row["updated_at"]),
        )

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version == FD_WORK_STATE_SCHEMA_VERSION:
            return
        if version == 1:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._create_pending_table(connection)
                connection.execute(
                    f"PRAGMA user_version = {FD_WORK_STATE_SCHEMA_VERSION}"
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
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
            self._create_pending_table(connection)
            connection.execute(
                f"PRAGMA user_version = {FD_WORK_STATE_SCHEMA_VERSION}"
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @staticmethod
    def _create_pending_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE pending_binding_operation (
                operation_id       TEXT PRIMARY KEY,
                operation_kind     TEXT NOT NULL,
                intended_name_hash TEXT NOT NULL,
                started_at         TEXT NOT NULL,
                project_id         INTEGER NULL,
                project_created_at TEXT NULL,
                previous_name_hash TEXT NULL,
                stage              TEXT NOT NULL,
                updated_at         TEXT NOT NULL
            )
            """
        )

    @staticmethod
    def _upsert_binding(
        connection: sqlite3.Connection,
        project_id: int,
        project_created_at: str | None,
        bound_name_hash: str,
        adapter_contract_version: int,
        timestamp: str,
    ) -> None:
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

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _validate_operation_id(value: str) -> None:
        if (
            type(value) is not str
            or not value
            or len(value) > 128
            or any(ord(character) < 33 or ord(character) > 126 for character in value)
        ):
            raise FDWorkBindingStoreError("pending_operation_invalid")

    @staticmethod
    def _validate_operation_kind(value: str) -> None:
        if value not in _OPERATION_KINDS:
            raise FDWorkBindingStoreError("pending_operation_invalid")

    @staticmethod
    def _validate_stage(value: str) -> None:
        if value not in _OPERATION_STAGES:
            raise FDWorkBindingStoreError("pending_operation_invalid")

    @staticmethod
    def _validate_hash(value: str) -> None:
        if (
            type(value) is not str
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise FDWorkBindingStoreError("pending_operation_invalid")

    @staticmethod
    def _validate_timestamp(value: str) -> None:
        if type(value) is not str or not value or len(value) > 64:
            raise FDWorkBindingStoreError("pending_operation_invalid")
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FDWorkBindingStoreError("pending_operation_invalid") from exc

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
    "PendingBindingOperation",
]
