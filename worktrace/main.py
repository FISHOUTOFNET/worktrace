from __future__ import annotations

import logging
import sys
import threading

from . import config, db
from .collector.collector import run_collector
from .collector.single_instance import acquire_single_instance, release_single_instance
from .services import activity_service, recovery_service
from .services.settings_service import set_setting
from .ui.app import WorkTraceApp


def setup_logging(log_path) -> None:
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def choose_adapter():
    if sys.platform.startswith("win"):
        from .platforms.windows_adapter import WindowsAdapter

        return WindowsAdapter()
    from .platforms.fake_adapter import FakeAdapter

    return FakeAdapter()


def main() -> int:
    paths = config.resolve_paths()
    config.ensure_directories(paths)
    setup_logging(paths.log_path)
    logging.info("app startup")
    db.initialize_database(paths.db_path)

    owns_collector = acquire_single_instance()
    if not owns_collector:
        logging.warning("single instance collector lock not acquired; UI will start without collector")

    recovery_service.recover_unclosed_records()
    stop_event = threading.Event()
    collector_thread: threading.Thread | None = None

    def start_collector() -> None:
        nonlocal collector_thread
        if not owns_collector or collector_thread is not None:
            return
        collector_thread = threading.Thread(
            target=run_collector,
            args=(choose_adapter(), stop_event),
            name="WorkTraceCollector",
            daemon=True,
        )
        collector_thread.start()

    try:
        app = WorkTraceApp(start_collector, stop_event)
        app.mainloop()
    finally:
        stop_event.set()
        if collector_thread:
            collector_thread.join(timeout=5)
        activity_service.close_current_open_record()
        set_setting("collector_status", "stopped")
        release_single_instance()
        logging.info("app shutdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
