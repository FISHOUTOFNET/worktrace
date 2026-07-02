"""Unit tests for ``worktrace.api._write_contract`` helper.

The shared Project Rules write-path validation
/ fail payload / success payload logic was moved into this helper. These tests lock
the contract so a future refactor cannot silently break the "true positive
int", "true bool", "true non-empty str", or stable payload shapes that
every Project Rules facade relies on.
"""

from __future__ import annotations

from worktrace.api import _write_contract as wc


# valid_int: true positive int, bool must reject.


def test_valid_int_accepts_positive_int():
    assert wc.valid_int(1) is True
    assert wc.valid_int(42) is True
    assert wc.valid_int(10_000) is True


def test_valid_int_rejects_zero_and_negative():
    assert wc.valid_int(0) is False
    assert wc.valid_int(-1) is False
    assert wc.valid_int(-100) is False


def test_valid_int_rejects_bool():
    # ``type(True) is bool``, not ``int``, so ``valid_int`` must reject
    # ``True`` / ``False`` even though ``isinstance(True, int)`` is True.
    assert wc.valid_int(True) is False
    assert wc.valid_int(False) is False


def test_valid_int_rejects_float_str_none_containers():
    assert wc.valid_int(1.0) is False
    assert wc.valid_int("1") is False
    assert wc.valid_int(None) is False
    assert wc.valid_int([1]) is False
    assert wc.valid_int({"id": 1}) is False
    assert wc.valid_int((1,)) is False


# valid_bool: true bool only.


def test_valid_bool_accepts_true_and_false():
    assert wc.valid_bool(True) is True
    assert wc.valid_bool(False) is True


def test_valid_bool_rejects_int_and_truthy():
    # ``0`` / ``1`` must NOT be accepted as bool.
    assert wc.valid_bool(0) is False
    assert wc.valid_bool(1) is False
    assert wc.valid_bool(2) is False


def test_valid_bool_rejects_str_none_containers():
    assert wc.valid_bool("true") is False
    assert wc.valid_bool("false") is False
    assert wc.valid_bool(None) is False
    assert wc.valid_bool([True]) is False


# valid_str / valid_nonempty_str: true str, non-empty after trim.


def test_valid_str_accepts_real_str():
    assert wc.valid_str("") is True
    assert wc.valid_str("hello") is True
    assert wc.valid_str("   ") is True


def test_valid_str_rejects_non_str():
    assert wc.valid_str(1) is False
    assert wc.valid_str(1.0) is False
    assert wc.valid_str(True) is False
    assert wc.valid_str(None) is False
    assert wc.valid_str(["a"]) is False


def test_valid_nonempty_str_returns_trimmed_for_non_empty():
    assert wc.valid_nonempty_str("hello") == "hello"
    assert wc.valid_nonempty_str("  hello  ") == "hello"
    assert wc.valid_nonempty_str("\tfoo\n") == "foo"


def test_valid_nonempty_str_returns_none_for_empty_after_trim():
    assert wc.valid_nonempty_str("") is None
    assert wc.valid_nonempty_str("   ") is None
    assert wc.valid_nonempty_str("\t\n") is None


def test_valid_nonempty_str_returns_none_for_non_str():
    assert wc.valid_nonempty_str(1) is None
    assert wc.valid_nonempty_str(True) is None
    assert wc.valid_nonempty_str(None) is None
    assert wc.valid_nonempty_str(["a"]) is None
    # bool must be rejected even though ``True`` is "truthy".
    assert wc.valid_nonempty_str(True) is None


# fail_payload / ok_payload: stable shapes.


def test_fail_payload_shape():
    payload = wc.fail_payload(wc.ERROR_INVALID_INPUT)
    assert payload == {"ok": False, "error": "invalid_input"}
    assert payload["ok"] is False
    assert isinstance(payload["error"], str)


def test_ok_payload_shape_merges_fields():
    payload = wc.ok_payload(rule={"id": 1})
    assert payload == {"ok": True, "rule": {"id": 1}}
    assert payload["ok"] is True


def test_ok_payload_with_no_fields_is_just_ok_envelope():
    assert wc.ok_payload() == {"ok": True}


def test_stable_error_codes_are_distinct_strings():
    codes = {
        wc.ERROR_INVALID_INPUT,
        wc.ERROR_NOT_FOUND,
        wc.ERROR_PROJECT_NOT_FOUND,
        wc.ERROR_DUPLICATE_RULE,
        wc.ERROR_DUPLICATE_PROJECT,
        wc.ERROR_SYSTEM_PROJECT,
        wc.ERROR_OPERATION_FAILED,
    }
    assert len(codes) == 7
    for code in codes:
        assert isinstance(code, str) and code


def test_helper_module_does_not_import_forbidden_layers():
    """The contract helper must stay pure stdlib so it can be imported from
    any API facade without creating a layering cycle."""
    import worktrace.api._write_contract as helper_mod

    source = open(helper_mod.__file__, encoding="utf-8").read()
    for forbidden in (
        "import worktrace.services",
        "import worktrace.db",
        "import worktrace.collector",
        "import worktrace.security",
        "import worktrace.runtime",
        "import worktrace.config",
        "from ..services",
        "from ..db",
        "from ..collector",
        "from ..security",
        "from ..runtime",
        "from ..config",
    ):
        assert forbidden not in source, (
            f"_write_contract must not import forbidden layer: {forbidden}"
        )
