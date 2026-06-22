from worktrace.collector.single_instance import acquire_single_instance, release_single_instance


def test_single_instance_lock_behavior(monkeypatch, tmp_path):
    release_single_instance()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    try:
        assert acquire_single_instance() is True
        assert acquire_single_instance() is False
    finally:
        release_single_instance()
