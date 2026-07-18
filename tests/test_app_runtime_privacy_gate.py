"""Current runtime-startup contracts plus retained privacy-gate coverage."""

from __future__ import annotations

import pytest

from tests import app_runtime_privacy_gate_contracts as _contracts

pytestmark = [
    pytest.mark.collector_runtime,
    pytest.mark.integration,
    pytest.mark.security_privacy,
    pytest.mark.serial,
    pytest.mark.db,
]

for _name in dir(_contracts):
    if _name.startswith("test_"):
        globals()[_name] = getattr(_contracts, _name)


def test_runtime_startup_orders_collector_before_derived_workers(
    temp_db,
    tmp_path,
    monkeypatch,
):
    runtime = _contracts._initialize_owned_runtime(
        temp_db,
        tmp_path,
        monkeypatch,
    )
    order: list[str] = []
    runtime._inference_thread = _contracts._fake_thread()
    monkeypatch.setattr(
        runtime,
        "start_background_workers",
        lambda: (
            order.append("workers")
            or _contracts.WorkerReadiness(True, True, True, True)
        ),
    )
    monkeypatch.setattr(
        runtime,
        "start_collector",
        lambda: order.append("collector")
        or {"ok": True, "started": True, "already_running": False},
    )
    try:
        result = runtime.start_authorized_collection()
        assert result.ok is True
        assert result.degraded is False
        assert order == ["collector", "workers"]
    finally:
        runtime.shutdown()
