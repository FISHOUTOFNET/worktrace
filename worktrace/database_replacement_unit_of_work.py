"""Sole owner of physical database replacement transactions."""
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


class ReplacementUnitOfWorkState(StrEnum):
    ACQUIRING = "acquiring"
    ACTIVE = "active"
    DURABLE_COMMITTED = "durable_committed"
    ROLLED_BACK = "rolled_back"
    FINALIZED = "finalized"


class DatabaseReplacementUnitOfWork:
    """Own one replacement transaction and retain its durable outcome."""

    def __init__(self) -> None:
        self._connection: sqlite3.Connection | None = None
        self._floor: dict[DataGenerationNamespace, int] = {}
        self._committed_values: dict[DataGenerationNamespace, int] | None = None
        self._database_key: str | None = None
        self._active = False
        self._state = ReplacementUnitOfWorkState.ACQUIRING
        self._durable_committed = False
        self._rolled_back = False

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
    def state(self) -> ReplacementUnitOfWorkState:
        return self._state

    @property
    def committed(self) -> bool:
        return self._durable_committed

    @property
    def rolled_back(self) -> bool:
        return self._rolled_back

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
            self._database_key = get_db_key()
            connection = get_connection()
            connection.execute("BEGIN IMMEDIATE")
            self._floor = DataGenerationRepository.get_many(
                connection,
                (_REPLACEMENT_NAMESPACE,),
            )
            self._connection = connection
            self._active = True
            self._state = ReplacementUnitOfWorkState.ACTIVE
            return self
        except BaseException:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    logging.warning(
                        "database replacement rollback failed stage=acquisition"
                    )
                try:
                    connection.close()
                except Exception:
                    logging.warning(
                        "database replacement close failed stage=acquisition"
                    )
            self._connection = None
            self._active = False
            self._state = ReplacementUnitOfWorkState.FINALIZED
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        connection = self._connection
        if connection is None:
            self._active = False
            self._state = ReplacementUnitOfWorkState.FINALIZED
            return False

        try:
            if exc_type is not None:
                try:
                    connection.rollback()
                except Exception:
                    logging.warning(
                        "database replacement rollback failed stage=operation"
                    )
                self._rolled_back = True
                self._state = ReplacementUnitOfWorkState.ROLLED_BACK
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
                        "database replacement rollback failed stage=commit"
                    )
                self._rolled_back = True
                self._state = ReplacementUnitOfWorkState.ROLLED_BACK
                raise

            self._committed_values = dict(committed_values)
            self._durable_committed = True
            self._state = ReplacementUnitOfWorkState.DURABLE_COMMITTED
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
                    "database replacement publication failed stage=post_commit"
                )
                try:
                    clear_generation_clock(database_key)
                except Exception:
                    logging.warning(
                        "database replacement cache clear failed stage=post_commit"
                    )
            return False
        finally:
            try:
                connection.close()
            except Exception:
                logging.warning(
                    "database replacement close failed stage=finalization"
                )
            self._connection = None
            self._active = False
            self._state = ReplacementUnitOfWorkState.FINALIZED


__all__ = [
    "DatabaseReplacementUnitOfWork",
    "ReplacementUnitOfWorkState",
]
