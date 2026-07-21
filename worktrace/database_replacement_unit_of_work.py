"""Sole owner of physical database replacement transactions.

Clear all live data, secure backup import, and any future whole-database
replacement must go through this owner. Durable commit is recorded before any
process-local publication or connection finalization can fail.
"""
from __future__ import annotations

import logging
import sqlite3
from enum import StrEnum

from .data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from .db import get_connection, get_db_key
from .generation_clock import clear as clear_generation_clock
from .generation_clock import publish_replacement_committed

_REPLACEMENT_NAMESPACE = DataGenerationNamespace.DATABASE_REPLACEMENT


class ReplacementUnitOfWorkPhase(StrEnum):
    ACQUIRING = "acquiring"
    ACTIVE = "active"
    DURABLE_COMMITTED = "durable_committed"
    ROLLED_BACK = "rolled_back"
    FINALIZED = "finalized"


class DatabaseReplacementUnitOfWork:
    """Own one physical database replacement transaction end-to-end."""

    def __init__(self) -> None:
        self._connection: sqlite3.Connection | None = None
        self._floor: dict[DataGenerationNamespace, int] = {}
        self._committed_values: dict[DataGenerationNamespace, int] | None = None
        self._database_key: str | None = None
        self._active = False
        self._phase = ReplacementUnitOfWorkPhase.ACQUIRING

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("database_replacement_unit_of_work_not_active")
        return self._connection

    @property
    def replacement_floor(self) -> dict[DataGenerationNamespace, int]:
        if not self._active:
            raise RuntimeError("database_replacement_unit_of_work_not_active")
        return dict(self._floor)

    @property
    def phase(self) -> ReplacementUnitOfWorkPhase:
        return self._phase

    @property
    def committed(self) -> bool:
        return self._phase is ReplacementUnitOfWorkPhase.DURABLE_COMMITTED

    @property
    def committed_values(self) -> dict[DataGenerationNamespace, int] | None:
        return (
            dict(self._committed_values)
            if self._committed_values is not None
            else None
        )

    def __enter__(self) -> "DatabaseReplacementUnitOfWork":
        if self._active:
            raise RuntimeError("database_replacement_unit_of_work_already_active")
        connection: sqlite3.Connection | None = None
        try:
            # Resolve stable process identity before the transaction. Failure is
            # therefore a genuine acquisition failure, never post-commit damage.
            self._database_key = get_db_key()
            connection = get_connection()
            connection.execute("BEGIN IMMEDIATE")
            floor = DataGenerationRepository.get_many(
                connection,
                (_REPLACEMENT_NAMESPACE,),
            )
            self._connection = connection
            self._floor = floor
            self._active = True
            self._phase = ReplacementUnitOfWorkPhase.ACTIVE
            return self
        except BaseException:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    logging.warning(
                        "database replacement rollback failed phase=acquisition"
                    )
                try:
                    connection.close()
                except Exception:
                    logging.warning(
                        "database replacement close failed phase=acquisition"
                    )
            self._connection = None
            self._active = False
            self._phase = ReplacementUnitOfWorkPhase.FINALIZED
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        connection = self._connection
        if connection is None:
            self._active = False
            self._phase = ReplacementUnitOfWorkPhase.FINALIZED
            return False

        try:
            if exc_type is not None:
                try:
                    connection.rollback()
                except Exception:
                    logging.warning(
                        "database replacement rollback failed phase=operation"
                    )
                self._phase = ReplacementUnitOfWorkPhase.ROLLED_BACK
                return False

            floor_value = int(self._floor.get(_REPLACEMENT_NAMESPACE, 0))
            committed_values = DataGenerationRepository.bump_replacement(
                connection,
                minimum_value=floor_value,
            )
            try:
                connection.commit()
            except BaseException:
                try:
                    connection.rollback()
                except Exception:
                    logging.warning(
                        "database replacement rollback failed phase=commit"
                    )
                self._phase = ReplacementUnitOfWorkPhase.ROLLED_BACK
                raise

            # This assignment and coordinator handoff are the first operations
            # after sqlite commit returns. Every later failure is finalization.
            self._committed_values = dict(committed_values)
            self._phase = ReplacementUnitOfWorkPhase.DURABLE_COMMITTED
            from .services.database_maintenance_service import (
                record_database_replacement_committed,
            )

            record_database_replacement_committed()

            database_key = self._database_key
            assert database_key is not None
            try:
                publish_replacement_committed(database_key, committed_values)
            except Exception:
                logging.warning(
                    "database replacement publication failed phase=post_commit"
                )
                try:
                    clear_generation_clock(database_key)
                except Exception:
                    logging.warning(
                        "database replacement cache clear failed phase=post_commit"
                    )
            return False
        finally:
            try:
                connection.close()
            except Exception:
                logging.warning(
                    "database replacement close failed phase=finalization"
                )
            self._connection = None
            self._active = False


__all__ = [
    "DatabaseReplacementUnitOfWork",
    "ReplacementUnitOfWorkPhase",
]
