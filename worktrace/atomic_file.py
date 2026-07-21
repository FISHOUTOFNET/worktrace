"""Small ownership primitives for temporary and atomic file lifecycles."""
from __future__ import annotations

import logging
import os
import tempfile
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


class TemporaryFileError(OSError):
    """Stable temporary-file infrastructure failure."""

    code = "temporary_file_failed"


class TemporaryFileCleanupError(TemporaryFileError):
    """A caller-owned temporary resource could not be removed."""

    code = "temporary_file_cleanup_failed"

    def __init__(self, resource: str, *, sensitive: bool = False) -> None:
        super().__init__(self.code)
        self.resource = str(resource or "temporary_file")
        self.sensitive = bool(sensitive)
        self.requires_recovery_block = self.sensitive


class AtomicReplaceError(TemporaryFileError):
    """The completed temporary output could not replace its destination."""

    code = "atomic_replace_failed"


CleanupFailureHandler = Callable[[TemporaryFileCleanupError], None]


class OwnedTemporaryFile(AbstractContextManager["OwnedTemporaryFile"]):
    """Own one unpredictable temporary pathname until explicit cleanup."""

    def __init__(
        self,
        *,
        directory: str | Path | None = None,
        prefix: str = "worktrace-",
        suffix: str = ".tmp",
        resource: str = "temporary_file",
        sensitive: bool = False,
        permissions: int | None = 0o600,
        on_cleanup_failure: CleanupFailureHandler | None = None,
    ) -> None:
        self.directory = Path(directory) if directory is not None else None
        self.prefix = str(prefix)
        self.suffix = str(suffix)
        self.resource = str(resource or "temporary_file")
        self.sensitive = bool(sensitive)
        self.permissions = permissions
        self.on_cleanup_failure = on_cleanup_failure
        self._path: Path | None = None
        self._cleaned = False

    @property
    def path(self) -> Path:
        if self._path is None:
            raise RuntimeError("temporary_file_not_acquired")
        return self._path

    @property
    def cleaned(self) -> bool:
        return self._cleaned

    def __enter__(self) -> "OwnedTemporaryFile":
        if self._path is not None:
            raise RuntimeError("temporary_file_already_acquired")
        if self.directory is not None:
            self.directory.mkdir(parents=True, exist_ok=True)
        fd: int | None = None
        created: str | None = None
        try:
            fd, created = tempfile.mkstemp(
                dir=str(self.directory) if self.directory is not None else None,
                prefix=self.prefix,
                suffix=self.suffix,
            )
            if self.permissions is not None:
                try:
                    os.fchmod(fd, int(self.permissions))
                except (AttributeError, OSError):
                    # Windows may not provide useful POSIX mode semantics. The
                    # file is still created with the current-user temp ACL.
                    pass
            os.close(fd)
            fd = None
            self._path = Path(created)
            return self
        except Exception as exc:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    logger.warning(
                        "temporary descriptor cleanup failed resource=%s",
                        self.resource,
                    )
            if created is not None:
                try:
                    os.unlink(created)
                except FileNotFoundError:
                    pass
                except OSError:
                    logger.warning(
                        "partial temporary file cleanup failed resource=%s",
                        self.resource,
                    )
            raise TemporaryFileError("temporary_file_create_failed") from exc

    def cleanup(self) -> None:
        if self._cleaned or self._path is None:
            self._cleaned = True
            return
        try:
            self._path.unlink()
        except FileNotFoundError:
            self._cleaned = True
            return
        except OSError as exc:
            error = TemporaryFileCleanupError(
                self.resource,
                sensitive=self.sensitive,
            )
            if self.on_cleanup_failure is not None:
                try:
                    self.on_cleanup_failure(error)
                except Exception:
                    logger.exception(
                        "temporary cleanup failure handler failed resource=%s",
                        self.resource,
                    )
            raise error from exc
        self._cleaned = True

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            self.cleanup()
        except TemporaryFileCleanupError:
            if exc_type is None:
                raise
            logger.warning(
                "temporary cleanup failed while preserving primary error resource=%s",
                self.resource,
            )
        return False


class AtomicFileOutput(AbstractContextManager["AtomicFileOutput"]):
    """Write beside a destination and atomically publish only on commit."""

    def __init__(
        self,
        target: str | Path,
        *,
        resource: str = "file_output",
        permissions: int | None = None,
        on_cleanup_failure: CleanupFailureHandler | None = None,
    ) -> None:
        self.target = Path(target)
        self.resource = str(resource or "file_output")
        self.permissions = permissions
        self.on_cleanup_failure = on_cleanup_failure
        self._owner: OwnedTemporaryFile | None = None
        self._committed = False

    @property
    def temporary_path(self) -> Path:
        if self._owner is None:
            raise RuntimeError("atomic_output_not_acquired")
        return self._owner.path

    @property
    def committed(self) -> bool:
        return self._committed

    def __enter__(self) -> "AtomicFileOutput":
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self._owner = OwnedTemporaryFile(
            directory=self.target.parent,
            prefix=f".{self.target.name}.",
            suffix=".tmp",
            resource=self.resource,
            permissions=self.permissions,
            on_cleanup_failure=self.on_cleanup_failure,
        )
        self._owner.__enter__()
        return self

    def commit(self) -> None:
        if self._owner is None:
            raise RuntimeError("atomic_output_not_acquired")
        try:
            os.replace(self.temporary_path, self.target)
        except OSError as exc:
            raise AtomicReplaceError("atomic_replace_failed") from exc
        self._committed = True
        self._owner._cleaned = True

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        owner = self._owner
        if owner is None:
            return False
        if self._committed:
            return False
        return owner.__exit__(exc_type, exc_value, traceback)


def atomic_write_bytes(
    target: str | Path,
    data: bytes,
    *,
    resource: str = "file_output",
    permissions: int | None = None,
) -> Path:
    destination = Path(target)
    with AtomicFileOutput(
        destination,
        resource=resource,
        permissions=permissions,
    ) as output:
        with open(output.temporary_path, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        output.commit()
    return destination


def atomic_write_text(
    target: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
    resource: str = "file_output",
    permissions: int | None = None,
) -> Path:
    destination = Path(target)
    with AtomicFileOutput(
        destination,
        resource=resource,
        permissions=permissions,
    ) as output:
        with open(output.temporary_path, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        output.commit()
    return destination


__all__ = [
    "AtomicFileOutput",
    "AtomicReplaceError",
    "OwnedTemporaryFile",
    "TemporaryFileCleanupError",
    "TemporaryFileError",
    "atomic_write_bytes",
    "atomic_write_text",
]
