from worktrace.collector.single_instance import acquire_single_instance, release_single_instance


def test_single_instance_lock_behavior():
    release_single_instance()
    assert acquire_single_instance() is True
    assert acquire_single_instance() is False
    release_single_instance()
