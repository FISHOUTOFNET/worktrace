"""Verify that a Windows executable embeds the canonical ICO payload.

The check reads PE icon resources directly through the Win32 resource API rather
than asking Explorer for an associated icon. That avoids false results from the
Windows shell icon cache, which can legitimately be stale after rebuilding an
EXE at the same path.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


RT_ICON = 3
RT_GROUP_ICON = 14
LOAD_LIBRARY_AS_DATAFILE = 0x00000002
LOAD_LIBRARY_AS_IMAGE_RESOURCE = 0x00000020


@dataclass(frozen=True)
class IconImage:
    width: int
    height: int
    planes: int
    bit_count: int
    payload: bytes


def _dimension(value: int) -> int:
    return 256 if value == 0 else value


def _parse_ico(path: Path) -> list[IconImage]:
    data = path.read_bytes()
    if len(data) < 6:
        raise ValueError(f"ICO file is truncated: {path}")
    reserved, icon_type, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or icon_type != 1 or count < 1:
        raise ValueError(f"Invalid ICO header: {path}")
    directory_end = 6 + count * 16
    if len(data) < directory_end:
        raise ValueError(f"ICO directory is truncated: {path}")

    images: list[IconImage] = []
    for index in range(count):
        offset = 6 + index * 16
        (
            width,
            height,
            _color_count,
            _reserved,
            planes,
            bit_count,
            size,
            image_offset,
        ) = struct.unpack_from("<BBBBHHII", data, offset)
        image_end = image_offset + size
        if image_offset < directory_end or image_end > len(data):
            raise ValueError(f"ICO image entry {index} is out of range: {path}")
        images.append(
            IconImage(
                width=_dimension(width),
                height=_dimension(height),
                planes=planes,
                bit_count=bit_count,
                payload=data[image_offset:image_end],
            )
        )
    return images


def _parse_group_icon(data: bytes) -> list[tuple[int, int, int, int, int]]:
    if len(data) < 6:
        raise ValueError("RT_GROUP_ICON resource is truncated")
    reserved, icon_type, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or icon_type != 1 or count < 1:
        raise ValueError("RT_GROUP_ICON resource has an invalid header")
    required = 6 + count * 14
    if len(data) < required:
        raise ValueError("RT_GROUP_ICON directory is truncated")

    entries: list[tuple[int, int, int, int, int]] = []
    for index in range(count):
        offset = 6 + index * 14
        (
            width,
            height,
            _color_count,
            _reserved,
            planes,
            bit_count,
            _size,
            resource_id,
        ) = struct.unpack_from("<BBBBHHIH", data, offset)
        entries.append(
            (
                _dimension(width),
                _dimension(height),
                planes,
                bit_count,
                resource_id,
            )
        )
    return entries


def _resource_names(module: int, resource_type: int, kernel32: object) -> list[int | str]:
    names: list[int | str] = []
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ssize_t,
    )

    def collect(_module: int, _type: int, name: int, _param: int) -> int:
        value = ctypes.cast(name, ctypes.c_void_p).value or 0
        if value <= 0xFFFF:
            names.append(value)
        else:
            names.append(ctypes.wstring_at(value))
        return 1

    callback = callback_type(collect)
    kernel32.EnumResourceNamesW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        callback_type,
        ctypes.c_ssize_t,
    ]
    kernel32.EnumResourceNamesW.restype = ctypes.c_int
    ok = kernel32.EnumResourceNamesW(
        ctypes.c_void_p(module),
        ctypes.c_void_p(resource_type),
        callback,
        0,
    )
    if not ok and not names:
        error = ctypes.get_last_error()
        raise OSError(error, f"Unable to enumerate resource type {resource_type}")
    return names


def _resource_pointer(value: int | str) -> tuple[ctypes.c_void_p, object | None]:
    if isinstance(value, int):
        return ctypes.c_void_p(value), None
    buffer = ctypes.create_unicode_buffer(value)
    return ctypes.cast(buffer, ctypes.c_void_p), buffer


def _read_resource(
    module: int,
    resource_type: int,
    name: int | str,
    kernel32: object,
) -> bytes:
    name_ptr, keepalive = _resource_pointer(name)
    _ = keepalive
    kernel32.FindResourceW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    kernel32.FindResourceW.restype = ctypes.c_void_p
    resource = kernel32.FindResourceW(
        ctypes.c_void_p(module),
        name_ptr,
        ctypes.c_void_p(resource_type),
    )
    if not resource:
        error = ctypes.get_last_error()
        raise OSError(error, f"Unable to find resource {resource_type}/{name}")

    kernel32.SizeofResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.SizeofResource.restype = ctypes.c_uint32
    size = kernel32.SizeofResource(ctypes.c_void_p(module), resource)
    if not size:
        error = ctypes.get_last_error()
        raise OSError(error, f"Unable to size resource {resource_type}/{name}")

    kernel32.LoadResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.LoadResource.restype = ctypes.c_void_p
    loaded = kernel32.LoadResource(ctypes.c_void_p(module), resource)
    if not loaded:
        error = ctypes.get_last_error()
        raise OSError(error, f"Unable to load resource {resource_type}/{name}")

    kernel32.LockResource.argtypes = [ctypes.c_void_p]
    kernel32.LockResource.restype = ctypes.c_void_p
    address = kernel32.LockResource(loaded)
    if not address:
        raise OSError(f"Unable to lock resource {resource_type}/{name}")
    return ctypes.string_at(address, size)


def _embedded_icons(exe_path: Path) -> list[IconImage]:
    if os.name != "nt":
        raise RuntimeError("Windows executable icon verification requires Windows")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
    kernel32.LoadLibraryExW.restype = ctypes.c_void_p
    module = kernel32.LoadLibraryExW(
        str(exe_path),
        None,
        LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_IMAGE_RESOURCE,
    )
    if not module:
        error = ctypes.get_last_error()
        raise OSError(error, f"Unable to open executable resources: {exe_path}")

    kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
    kernel32.FreeLibrary.restype = ctypes.c_int
    try:
        group_names = _resource_names(module, RT_GROUP_ICON, kernel32)
        if not group_names:
            raise ValueError(f"Executable contains no RT_GROUP_ICON resource: {exe_path}")
        group = _read_resource(module, RT_GROUP_ICON, group_names[0], kernel32)
        entries = _parse_group_icon(group)
        return [
            IconImage(
                width=width,
                height=height,
                planes=planes,
                bit_count=bit_count,
                payload=_read_resource(module, RT_ICON, resource_id, kernel32),
            )
            for width, height, planes, bit_count, resource_id in entries
        ]
    finally:
        kernel32.FreeLibrary(ctypes.c_void_p(module))


def _preferred(images: Iterable[IconImage]) -> list[IconImage]:
    preference = {32: 0, 48: 1, 256: 2, 16: 3}
    return sorted(images, key=lambda image: (preference.get(image.width, 10), image.width))


def verify(exe_path: Path, ico_path: Path) -> None:
    expected = _preferred(_parse_ico(ico_path))
    embedded = _embedded_icons(exe_path)
    for expected_image in expected:
        for embedded_image in embedded:
            if (
                expected_image.width == embedded_image.width
                and expected_image.height == embedded_image.height
                and expected_image.payload == embedded_image.payload
            ):
                print(
                    "Installer icon verified: "
                    f"{expected_image.width}x{expected_image.height} canonical payload embedded"
                )
                return
    embedded_sizes = ", ".join(
        f"{image.width}x{image.height}" for image in _preferred(embedded)
    )
    expected_sizes = ", ".join(f"{image.width}x{image.height}" for image in expected)
    raise RuntimeError(
        "Compiled executable does not contain any canonical icon payload; "
        f"expected sizes [{expected_sizes}], embedded sizes [{embedded_sizes}]"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--ico", required=True, type=Path)
    args = parser.parse_args()
    verify(args.exe.resolve(), args.ico.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
