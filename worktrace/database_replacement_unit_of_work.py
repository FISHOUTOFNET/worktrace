"""Sole owner of physical database replacement transactions.

Clear all live data, secure backup import, and any future whole-database
replacement must go through this owner. It owns:

* capturing the replacement generation floor before any delete;
* opening the exclusive replacement transaction;
* letting the caller execute delete/insert/seed/reset/validation;
* advancing the durable replacement epoch exactly once;
* commit or rollback;
* process-local publication only after a successful commit;
* clearing the process clock if publication fails.

It does NOT own ordinary domain mutations (use ``DomainUnitOfWork``), and it
does NOT own maintenance coordination (use the maintenance coordinator).
``DomainUnitOfWork`` continues to handle ordinary business mutations and is
intentionally never reused for physical replacement.

A replacement transaction is mutually exclusive with ordinary
``DomainUnitOfWork`` transactions: this owner opens its own ``BEGIN IMMEDIATE``
on the live database and never participates in the ordinary unit-of-work
ContextVar. Callers must enter a ``database_replacement`` maintenance scope
before opening a ``DatabaseReplacementUnitOfWork`` so the runtime quiesces
collectors and drains existing writers.
"""

from __future__ import annotations

import logging
import sqlite3

from .data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from .db import get_connection, get_db_key
from .generation_clock import clear as clear_generation_clock
from .generation_clock import publish_replacement_committed

_REPLACEMENT_NAMESPACE = DataGenerationNamespace.DATABASE_REPLACEMENT


class DatabaseReplacementUnitOfWork:
    """Own one physical database replacement transaction end-to-end."""

    def __init__(self) -> None:
        self._connection: sqlite3.Connection | None = None
        self._floor: dict[DataGenerationNamespace, int] = {}
        self._committed_values: dict[DataGenerationNamespace, int] | None = None
        self._active = False

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

    def __enter__(self) -> "DatabaseReplacementUnitOfWork":
        if self._active:
            raise RuntimeError("database_replacement_unit_of_work_already_active")
        self._connection = get_connection()
        self._connection.execute("BEGIN IMMEDIATE")
        self._floor = DataGenerationRepository.get_many(
            self._connection,
            (_REPLACEMENT_NAMESPACE,),
        )
        self._active = True
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        connection = self._connection
        if connection is None:
            self._active = False
            return False

        committed_values: dict[DataGenerationNamespace, int] | None = None
        committed = False
        try:
            if exc_type is not None:
                connection.rollback()
                return False

            floor_value = int(self._floor.get(_REPLACEMENT_NAMESPACE, 0))
            committed_values = DataGenerationRepository.bump_replacement(
                connection,
                minimum_value=floor_value,
            )
            connection.commit()
            committed = True
        except Exception:
            if not committed:
                try:
                    connection.rollback()
                except Exception:
                    logging.exception(
                        "database replacement rollback failed after bump/commit error"
                    )
            raise
        finally:
            if not committed:
                try:
                    connection.close()
                except Exception:
                    logging.exception(
                        "database replacement connection close failed"
                    )
                self._connection = None
                self._active = False

        # Durable commit succeeded. Publish the exact committed value to the
        # process-local clock. A publication failure degrades to a cache miss
        # and never misreports the command itself as failed.
        database_key = get_db_key()
        try:
            publish_replacement_committed(database_key, committed_values)
        except Exception:
            logging.exception(
                "database replacement process-local publication failed"
            )
            try:
                clear_generation_clock(database_key)
            except Exception:
                logging.exception(
                    "database replacement clock clear failed after publication error"
                )

        try:
            connection.close()
        except Exception:
            logging.exception("database replacement connection close failed")
        self._committed_values = committed_values
        self._connection = None
        self._active = False
        return False


__all__ = ["DatabaseReplacementUnitOfWork"]
