"""Canonical immutable product metadata for 有迹 presentation surfaces."""
from __future__ import annotations

from dataclasses import dataclass

from .version import __version__


@dataclass(frozen=True)
class ApplicationMetadata:
    """Process-lifetime product identity and release-channel metadata."""

    version: str
    release_channel: str
    creator: str

    def as_dict(self) -> dict[str, str]:
        return {
            "version": self.version,
            "release_channel": self.release_channel,
            "creator": self.creator,
        }


APPLICATION_METADATA = ApplicationMetadata(
    version=__version__,
    release_channel="beta",
    creator="Sun Yi",
)


class ApplicationMetadataService:
    """Read-only capability exposing canonical application metadata."""

    def get_application_metadata(self) -> dict[str, str]:
        return APPLICATION_METADATA.as_dict()


__all__ = [
    "APPLICATION_METADATA",
    "ApplicationMetadata",
    "ApplicationMetadataService",
]
