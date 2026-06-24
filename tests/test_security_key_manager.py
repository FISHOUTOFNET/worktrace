from __future__ import annotations

import base64
import json
import sys
import types

from worktrace.security.key_manager import (
    DATA_KEY_BYTES,
    DPAPI_WRAP_TYPE,
    FakeKeyWrapper,
    DpapiKeyWrapper,
    create_or_load_local_key,
    default_keyring_path,
    keyring_exists,
    load_local_key,
)


def test_fake_key_manager_create_and_load(tmp_path) -> None:
    path = tmp_path / "WorkTrace" / "security" / "keyring.json"
    wrapper = FakeKeyWrapper()

    created = create_or_load_local_key(path=path, wrapper=wrapper)
    loaded = load_local_key(path=path, wrapper=wrapper)

    assert created.key_id == loaded.key_id
    assert created.key == loaded.key
    assert len(loaded.key) == DATA_KEY_BYTES
    assert keyring_exists(path)


def test_keyring_does_not_store_plaintext_key(tmp_path) -> None:
    path = tmp_path / "keyring.json"
    wrapper = FakeKeyWrapper()
    local_key = create_or_load_local_key(path=path, wrapper=wrapper)
    text = path.read_text(encoding="utf-8")

    assert local_key.key.hex() not in text
    assert base64.b64encode(local_key.key).decode("ascii") not in text
    assert "wrapped_data_key" in text


def test_keyring_path_is_under_worktrace_local_security(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    path = default_keyring_path()

    assert path == tmp_path / "WorkTrace" / "security" / "keyring.json"


def test_windows_dpapi_wrapper_can_be_mocked(monkeypatch) -> None:
    calls: list[tuple[str, bytes]] = []

    def protect(data, description, optional_entropy, reserved, prompt_struct, flags):
        calls.append(("protect", data))
        return b"wrapped:" + data

    def unprotect(wrapped, optional_entropy, reserved, prompt_struct, flags):
        calls.append(("unprotect", wrapped))
        return ("WorkTrace local data key", wrapped.removeprefix(b"wrapped:"))

    fake_win32crypt = types.SimpleNamespace(
        CryptProtectData=protect,
        CryptUnprotectData=unprotect,
    )
    monkeypatch.setitem(sys.modules, "win32crypt", fake_win32crypt)

    wrapper = DpapiKeyWrapper()
    wrapped = wrapper.wrap(b"x" * DATA_KEY_BYTES)
    unwrapped = wrapper.unwrap(wrapped)

    assert wrapper.wrap_type == DPAPI_WRAP_TYPE
    assert unwrapped == b"x" * DATA_KEY_BYTES
    assert calls == [("protect", b"x" * DATA_KEY_BYTES), ("unprotect", wrapped)]


def test_non_windows_tests_do_not_need_real_dpapi(tmp_path) -> None:
    path = tmp_path / "keyring.json"
    wrapper = FakeKeyWrapper(secret=b"test secret")

    local_key = create_or_load_local_key(path=path, wrapper=wrapper)
    keyring = json.loads(path.read_text(encoding="utf-8"))

    assert keyring["keys"][0]["wrap_type"] == wrapper.wrap_type
    assert load_local_key(path=path, wrapper=wrapper).key == local_key.key
