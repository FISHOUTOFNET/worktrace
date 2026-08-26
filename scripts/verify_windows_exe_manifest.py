from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
from xml.etree import ElementTree


RT_MANIFEST = 24
LOAD_LIBRARY_AS_DATAFILE = 0x00000002
LOAD_LIBRARY_AS_IMAGE_RESOURCE = 0x00000020


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


def _decode_manifest(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "<assembly" in text:
            return text
    raise ValueError("Embedded manifest is not decodable XML")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _has_required_dpi_contract(text: str) -> bool:
    root = ElementTree.fromstring(text)
    dpi_awareness = []
    legacy_dpi_awareness = []
    execution_levels = []
    for element in root.iter():
        name = _local_name(element.tag)
        if name == "dpiAwareness":
            dpi_awareness.append((element.text or "").strip())
        elif name == "dpiAware":
            legacy_dpi_awareness.append((element.text or "").strip())
        elif name == "requestedExecutionLevel":
            execution_levels.append(str(element.attrib.get("level") or ""))
    return (
        "PerMonitorV2" in dpi_awareness
        and "true/pm" in legacy_dpi_awareness
        and "asInvoker" in execution_levels
    )


def _embedded_manifests(exe_path: Path) -> list[str]:
    if os.name != "nt":
        raise RuntimeError("Windows executable manifest verification requires Windows")

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
        names = _resource_names(module, RT_MANIFEST, kernel32)
        if not names:
            raise ValueError(f"Executable contains no RT_MANIFEST resource: {exe_path}")
        return [
            _decode_manifest(_read_resource(module, RT_MANIFEST, name, kernel32))
            for name in names
        ]
    finally:
        kernel32.FreeLibrary(ctypes.c_void_p(module))


def verify(exe_path: Path) -> None:
    manifests = _embedded_manifests(exe_path)
    if not any(_has_required_dpi_contract(text) for text in manifests):
        raise RuntimeError(
            "Compiled executable does not contain the required PerMonitorV2, "
            "true/pm, asInvoker manifest contract"
        )
    print("DPI manifest verified: PerMonitorV2 with true/pm fallback and asInvoker")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    args = parser.parse_args()
    verify(args.exe.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
