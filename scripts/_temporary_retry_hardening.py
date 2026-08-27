from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {relative}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def write_new(relative: str, content: str) -> None:
    path = ROOT / relative
    if path.exists():
        raise RuntimeError(f"refusing to overwrite existing file: {relative}")
    path.write_text(content, encoding="utf-8")


write_new(
    "worktrace/retry_state.py",
    '''"""Process-local retry episode state with no I/O or lifecycle ownership."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RetryDecision:
    code: str
    attempt: int
    delay_seconds: float
    elapsed_seconds: float
    first_failure: bool
    code_changed: bool
    detail_log_due: bool
    summary_log_due: bool


@dataclass(frozen=True)
class RecoveryDecision:
    recovered: bool
    code: str = ""
    attempts: int = 0
    elapsed_seconds: float = 0.0


class RetryEpisode:
    """Track one worker-local failure episode without performing side effects."""

    def __init__(
        self,
        *,
        initial_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
        summary_interval_seconds: float = 60.0,
        monotonic_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self._initial_delay = max(0.0, float(initial_delay_seconds))
        self._max_delay = max(self._initial_delay, float(max_delay_seconds))
        self._summary_interval = max(0.0, float(summary_interval_seconds))
        self._monotonic = monotonic_func
        self._code = ""
        self._attempts = 0
        self._started_at = 0.0
        self._last_summary_at = 0.0

    def failed(self, code: str) -> RetryDecision:
        now = self._monotonic()
        normalized = str(code or "retryable_failure").strip() or "retryable_failure"
        first_failure = self._attempts == 0
        code_changed = bool(not first_failure and normalized != self._code)
        if first_failure or code_changed:
            self._code = normalized
            self._attempts = 1
            self._started_at = now
            self._last_summary_at = now
        else:
            self._attempts += 1

        detail_log_due = bool(first_failure or code_changed)
        summary_log_due = False
        if (
            not detail_log_due
            and self._summary_interval > 0.0
            and now - self._last_summary_at >= self._summary_interval
        ):
            summary_log_due = True
            self._last_summary_at = now

        if self._initial_delay <= 0.0:
            delay_seconds = 0.0
        else:
            delay_seconds = min(
                self._max_delay,
                self._initial_delay * (2 ** min(self._attempts - 1, 30)),
            )
        return RetryDecision(
            code=self._code,
            attempt=self._attempts,
            delay_seconds=delay_seconds,
            elapsed_seconds=max(0.0, now - self._started_at),
            first_failure=first_failure,
            code_changed=code_changed,
            detail_log_due=detail_log_due,
            summary_log_due=summary_log_due,
        )

    def succeeded(self) -> RecoveryDecision:
        if self._attempts <= 0:
            return RecoveryDecision(False)
        now = self._monotonic()
        recovered = RecoveryDecision(
            True,
            code=self._code,
            attempts=self._attempts,
            elapsed_seconds=max(0.0, now - self._started_at),
        )
        self._code = ""
        self._attempts = 0
        self._started_at = 0.0
        self._last_summary_at = 0.0
        return recovered


__all__ = ["RecoveryDecision", "RetryDecision", "RetryEpisode"]
''',
)

replace_once(
    "worktrace/platforms/base.py",
    "    def get_active_window(self) -> ActiveWindow: ...\n",
    "    def get_active_window(self) -> ActiveWindow | None: ...\n",
)

replace_once(
    "worktrace/platforms/windows_adapter.py",
    '''    def get_active_window(self) -> ActiveWindow:\n        import psutil\n        import win32gui\n        import win32process\n\n        try:\n            hwnd = int(win32gui.GetForegroundWindow() or 0)\n            if hwnd <= 0:\n                raise PlatformTemporarilyUnavailableError(\n                    "foreground_window_unavailable"\n                )\n            title = win32gui.GetWindowText(hwnd) or ""\n''',
    '''    def get_active_window(self) -> ActiveWindow | None:\n        import psutil\n        import win32gui\n        import win32process\n\n        try:\n            hwnd = int(win32gui.GetForegroundWindow() or 0)\n            if hwnd <= 0:\n                return None\n            title = win32gui.GetWindowText(hwnd) or ""\n''',
)

replace_once(
    "worktrace/platforms/windows_clipboard.py",
    "        source_window_provider: Callable[[], ActiveWindow],\n",
    "        source_window_provider: Callable[[], ActiveWindow | None],\n",
)
replace_once(
    "worktrace/platforms/windows_clipboard.py",
    '''        source_window = self._source_window_provider()\n        text = read_clipboard_unicode_text()\n''',
    '''        source_window = self._source_window_provider()\n        if source_window is None:\n            return\n        text = read_clipboard_unicode_text()\n''',
)

replace_once(
    "worktrace/collector/collector.py",
    "from ..platforms.base import PlatformAdapter\n",
    "from ..platforms.base import PlatformAdapter\nfrom ..retry_state import RetryEpisode\n",
)
replace_once(
    "worktrace/collector/collector.py",
    '''        machine = CollectorStateMachine()\n        clock_tracker = ClockTracker()\n        last_loop_time: str | None = None\n''',
    '''        machine = CollectorStateMachine()\n        clock_tracker = ClockTracker()\n        transient_episode = RetryEpisode(\n            initial_delay_seconds=0.0,\n            max_delay_seconds=0.0,\n            summary_interval_seconds=60.0,\n        )\n        last_loop_time: str | None = None\n''',
)
replace_once(
    "worktrace/collector/collector.py",
    '''            if last_loop_time:\n                midnight = _midnight_crossed_between(last_loop_time, now)\n                if midnight is not None:\n                    machine.split_at_midnight(midnight)\n''',
    '''            if last_loop_time:\n                midnight = _midnight_crossed_between(last_loop_time, now)\n                if midnight is not None:\n                    machine.split_at_midnight(midnight)\n                    last_loop_time = midnight\n                    last_safe_boundary_time = midnight\n''',
)
replace_once(
    "worktrace/collector/collector.py",
    '''            phase = "active_window"\n            active_window = adapter.get_active_window()\n            phase = "clipboard"\n            capture_enabled = clipboard_service.is_capture_enabled()\n            _set_clipboard_capture_enabled(adapter, capture_enabled)\n            clipboard_events = _clipboard_events(adapter) if capture_enabled else []\n            phase = "idle"\n            idle_seconds = adapter.get_idle_seconds()\n            idle_threshold = max(1, idle_threshold_seconds)\n\n            decision = None\n            if idle_seconds < idle_threshold:\n                phase = "privacy"\n                decision = privacy_service.evaluate_exclusion(active_window)\n''',
    '''            phase = "idle"\n            idle_seconds = adapter.get_idle_seconds()\n            idle_threshold = max(1, idle_threshold_seconds)\n\n            active_window = None\n            clipboard_events = []\n            decision = None\n            if idle_seconds >= idle_threshold:\n                _set_clipboard_capture_enabled(adapter, False)\n            else:\n                phase = "active_window"\n                active_window = adapter.get_active_window()\n                if active_window is None:\n                    collector_health.record_sampling_progress()\n                    next_poll_deadline = _sleep_until_next_poll(\n                        stop_event,\n                        control,\n                        next_poll_deadline,\n                    )\n                    continue\n                phase = "clipboard"\n                capture_enabled = clipboard_service.is_capture_enabled()\n                _set_clipboard_capture_enabled(adapter, capture_enabled)\n                clipboard_events = _clipboard_events(adapter) if capture_enabled else []\n                phase = "privacy"\n                decision = privacy_service.evaluate_exclusion(active_window)\n''',
)
replace_once(
    "worktrace/collector/collector.py",
    '''            collector_health.record_successful_observation(observation_time)\n            last_loop_time = observation_time\n''',
    '''            recovery = transient_episode.succeeded()\n            collector_health.record_successful_observation(observation_time)\n            if recovery.recovered:\n                logging.info(\n                    "collector transient failure recovered code=%s attempts=%s elapsed_seconds=%.1f",\n                    recovery.code,\n                    recovery.attempts,\n                    recovery.elapsed_seconds,\n                )\n            last_loop_time = observation_time\n''',
)
replace_once(
    "worktrace/collector/collector.py",
    '''            if startup_runtime_pending:\n                logging.exception(\n                    "collector transient startup failure code=%s",\n                    disposition.code.value,\n                )\n                _wait_for_poll_delay(stop_event, control, POLL_CADENCE_SECONDS)\n                continue\n\n            collector_health.record_transient_failure(\n                phase,\n                disposition.code,\n                now_str(),\n            )\n            logging.exception(\n                "collector transient failure phase=%s code=%s",\n                phase,\n                disposition.code.value,\n            )\n''',
    '''            retry = transient_episode.failed(disposition.code.value)\n            if startup_runtime_pending:\n                if retry.detail_log_due:\n                    logging.warning(\n                        "collector transient startup failure code=%s",\n                        disposition.code.value,\n                        exc_info=True,\n                    )\n                elif retry.summary_log_due:\n                    logging.warning(\n                        "collector transient startup failure continues code=%s consecutive=%s elapsed_seconds=%.1f",\n                        disposition.code.value,\n                        retry.attempt,\n                        retry.elapsed_seconds,\n                    )\n                _wait_for_poll_delay(stop_event, control, POLL_CADENCE_SECONDS)\n                continue\n\n            collector_health.record_transient_failure(\n                phase,\n                disposition.code,\n                now_str(),\n            )\n            if retry.detail_log_due:\n                logging.warning(\n                    "collector transient failure phase=%s code=%s consecutive=%s",\n                    phase,\n                    disposition.code.value,\n                    retry.attempt,\n                    exc_info=True,\n                )\n            elif retry.summary_log_due:\n                logging.warning(\n                    "collector transient failure continues phase=%s code=%s consecutive=%s elapsed_seconds=%.1f",\n                    phase,\n                    disposition.code.value,\n                    retry.attempt,\n                    retry.elapsed_seconds,\n                )\n''',
)

replace_once(
    "worktrace/collector/collector_health.py",
    "_SUCCESS_PERSIST_INTERVAL_SECONDS = 30\n",
    "_SUCCESS_PERSIST_INTERVAL_SECONDS = 30\n_FAILURE_PERSIST_INTERVAL_SECONDS = 60\n",
)
replace_once(
    "worktrace/collector/collector_health.py",
    '''class _RuntimeHealthState:\n    health_state: str\n    failures: int\n    last_failure_at: str\n    last_success_persisted_at: str\n''',
    '''class _RuntimeHealthState:\n    health_state: str\n    failures: int\n    last_failure_at: str\n    last_success_persisted_at: str\n    last_failure_persisted_at: str\n    last_failure_phase: str\n    last_failure_code: str\n''',
)
replace_once(
    "worktrace/collector/collector_health.py",
    '''                last_success_persisted_at=get_setting(\n                    "collector_last_successful_observation_at",\n                    "",\n                )\n                or "",\n            )\n''',
    '''                last_success_persisted_at=get_setting(\n                    "collector_last_successful_observation_at",\n                    "",\n                )\n                or "",\n                last_failure_persisted_at=get_setting(\n                    "collector_last_failure_at",\n                    "",\n                )\n                or "",\n                last_failure_phase=get_setting(\n                    "collector_last_failure_phase",\n                    "",\n                )\n                or "",\n                last_failure_code=get_setting(\n                    "collector_last_failure_kind",\n                    "",\n                )\n                or "",\n            )\n''',
)
replace_once(
    "worktrace/collector/collector_health.py",
    '''def _record_successful_runtime_progress(at_time: str) -> None:\n    with _PROGRESS_LOCK:\n        _RUNTIME_PROGRESS.last_successful_observation_at = str(at_time or "")\n        _RUNTIME_PROGRESS.last_success_monotonic = time.monotonic()\n        _RUNTIME_PROGRESS.runtime_status = "running"\n\n\ndef _elapsed_seconds''',
    '''def _record_successful_runtime_progress(at_time: str) -> None:\n    with _PROGRESS_LOCK:\n        _RUNTIME_PROGRESS.last_successful_observation_at = str(at_time or "")\n        _RUNTIME_PROGRESS.last_success_monotonic = time.monotonic()\n        _RUNTIME_PROGRESS.runtime_status = "running"\n\n\ndef record_sampling_progress() -> None:\n    """Refresh process-local liveness without advancing the durable time watermark."""\n\n    with _PROGRESS_LOCK:\n        _RUNTIME_PROGRESS.last_success_monotonic = time.monotonic()\n        _RUNTIME_PROGRESS.runtime_status = "running"\n\n\ndef _elapsed_seconds''',
)
replace_once(
    "worktrace/collector/collector_health.py",
    '''def record_transient_failure(\n    phase: str,\n    code: CollectorFailureCode,\n    at_time: str | None = None,\n) -> None:\n    safe_code = _safe_failure_code(code)\n    if code not in RETRYABLE_COLLECTOR_FAILURE_CODES:\n        raise ValueError("collector_failure_code_not_retryable")\n    at = at_time or now_str()\n    state = _runtime_state()\n    with _STATE_LOCK:\n        state.failures += 1\n        state.health_state = (\n            HEALTH_FAILING\n            if state.failures >= _FAILING_THRESHOLD\n            else HEALTH_DEGRADED\n        )\n        state.last_failure_at = at\n        failures = state.failures\n        health_state = state.health_state\n    set_settings(\n        {\n            "collector_health_state": health_state,\n            "collector_last_failure_at": at,\n            "collector_consecutive_failures": str(failures),\n            "collector_last_failure_phase": _safe_phase(phase),\n            "collector_last_failure_kind": safe_code,\n        }\n    )\n    logging.warning(\n        "collector transient failure phase=%s code=%s consecutive=%s",\n        _safe_phase(phase),\n        safe_code,\n        failures,\n    )\n''',
    '''def record_transient_failure(\n    phase: str,\n    code: CollectorFailureCode,\n    at_time: str | None = None,\n) -> None:\n    safe_code = _safe_failure_code(code)\n    safe_phase = _safe_phase(phase)\n    if code not in RETRYABLE_COLLECTOR_FAILURE_CODES:\n        raise ValueError("collector_failure_code_not_retryable")\n    at = at_time or now_str()\n    state = _runtime_state()\n    with _STATE_LOCK:\n        previous_health = state.health_state\n        previous_phase = state.last_failure_phase\n        previous_code = state.last_failure_code\n        state.failures += 1\n        state.health_state = (\n            HEALTH_FAILING\n            if state.failures >= _FAILING_THRESHOLD\n            else HEALTH_DEGRADED\n        )\n        state.last_failure_at = at\n        state.last_failure_phase = safe_phase\n        state.last_failure_code = safe_code\n        elapsed = _elapsed_seconds(state.last_failure_persisted_at, at)\n        should_persist = bool(\n            state.failures == 1\n            or state.health_state != previous_health\n            or safe_phase != previous_phase\n            or safe_code != previous_code\n            or elapsed is None\n            or elapsed < 0\n            or elapsed >= _FAILURE_PERSIST_INTERVAL_SECONDS\n        )\n        failures = state.failures\n        health_state = state.health_state\n        if should_persist:\n            state.last_failure_persisted_at = at\n\n    if not should_persist:\n        return\n    set_settings(\n        {\n            "collector_health_state": health_state,\n            "collector_last_failure_at": at,\n            "collector_consecutive_failures": str(failures),\n            "collector_last_failure_phase": safe_phase,\n            "collector_last_failure_kind": safe_code,\n        }\n    )\n''',
)
replace_once(
    "worktrace/collector/collector_health.py",
    '    "record_runtime_status",\n    "record_successful_observation",\n',
    '    "record_runtime_status",\n    "record_sampling_progress",\n    "record_successful_observation",\n',
)

# Worker-level retry episodes are deliberately process-local. Durable job retries
# remain owned by their existing repositories.
for relative in [
    "worktrace/services/activity_fact_repair_service.py",
    "worktrace/services/activity_inference_job_service.py",
    "worktrace/services/recovery_service.py",
    "worktrace/services/history_mutation_job_service.py",
    "worktrace/services/folder_index_service.py",
    "worktrace/runtime/collector_supervisor.py",
]:
    replace_once(
        relative,
        "from ..worker_health import WorkerHealthReporter\n" if "/services/" in relative else "from ..services.settings_service import get_bool_setting\n",
        (
            "from ..retry_state import RetryEpisode\nfrom ..worker_health import WorkerHealthReporter\n"
            if "/services/" in relative
            else "from ..retry_state import RetryEpisode\nfrom ..services.settings_service import get_bool_setting\n"
        ),
    )

replace_once(
    "worktrace/services/activity_fact_repair_service.py",
    '''    interval = max(0.1, float(poll_seconds))\n    logging.info("activity resource repair worker loop enter")\n    while not stop_event.is_set():\n''',
    '''    interval = max(0.1, float(poll_seconds))\n    retry_episode = RetryEpisode()\n    logging.info("activity resource repair worker loop enter")\n    while not stop_event.is_set():\n''',
)
replace_once(
    "worktrace/services/activity_fact_repair_service.py",
    '''        try:\n            repaired = repair_missing_activity_resources(size)\n        except Exception:\n            logging.exception("activity resource repair worker iteration failed")\n            health.failed("activity_resource_repair_iteration_failed")\n            repaired = 0\n        else:\n            health.succeeded()\n        if repaired >= size:\n            continue\n        stop_event.wait(interval)\n''',
    '''        try:\n            repaired = repair_missing_activity_resources(size)\n        except Exception:\n            retry = retry_episode.failed("activity_resource_repair_iteration_failed")\n            health.failed("activity_resource_repair_iteration_failed")\n            if retry.detail_log_due:\n                logging.warning(\n                    "activity resource repair worker iteration failed",\n                    exc_info=True,\n                )\n            elif retry.summary_log_due:\n                logging.warning(\n                    "activity resource repair worker failure continues consecutive=%s elapsed_seconds=%.1f",\n                    retry.attempt,\n                    retry.elapsed_seconds,\n                )\n            stop_event.wait(max(interval, retry.delay_seconds))\n            continue\n        recovery = retry_episode.succeeded()\n        health.succeeded()\n        if recovery.recovered:\n            logging.info(\n                "activity resource repair worker recovered attempts=%s elapsed_seconds=%.1f",\n                recovery.attempts,\n                recovery.elapsed_seconds,\n            )\n        if repaired >= size:\n            continue\n        stop_event.wait(interval)\n''',
)

replace_once(
    "worktrace/services/activity_inference_job_service.py",
    '''    interval = max(0.1, float(poll_seconds))\n    logging.info("activity inference worker loop enter")\n    while not stop_event.is_set():\n''',
    '''    interval = max(0.1, float(poll_seconds))\n    retry_episode = RetryEpisode()\n    logging.info("activity inference worker loop enter")\n    while not stop_event.is_set():\n''',
)
replace_once(
    "worktrace/services/activity_inference_job_service.py",
    '''        try:\n            processed = process_pending_inference_jobs(\n                infer_activity,\n                limit=size,\n            )\n        except Exception:\n            logging.exception("activity inference worker iteration failed")\n            health.failed("inference_iteration_failed")\n            processed = 0\n        else:\n            health.succeeded()\n        if processed >= size:\n            continue\n        stop_event.wait(interval)\n''',
    '''        try:\n            processed = process_pending_inference_jobs(\n                infer_activity,\n                limit=size,\n            )\n        except Exception as exc:\n            code = _classify_failure(exc)\n            retry = retry_episode.failed(code.value)\n            health.failed("inference_iteration_failed")\n            if retry.detail_log_due:\n                logging.warning(\n                    "activity inference worker iteration failed code=%s",\n                    code.value,\n                    exc_info=True,\n                )\n            elif retry.summary_log_due:\n                logging.warning(\n                    "activity inference worker failure continues code=%s consecutive=%s elapsed_seconds=%.1f",\n                    code.value,\n                    retry.attempt,\n                    retry.elapsed_seconds,\n                )\n            stop_event.wait(max(interval, retry.delay_seconds))\n            continue\n        recovery = retry_episode.succeeded()\n        health.succeeded()\n        if recovery.recovered:\n            logging.info(\n                "activity inference worker recovered code=%s attempts=%s elapsed_seconds=%.1f",\n                recovery.code,\n                recovery.attempts,\n                recovery.elapsed_seconds,\n            )\n        if processed >= size:\n            continue\n        stop_event.wait(interval)\n''',
)

replace_once(
    "worktrace/services/history_mutation_job_service.py",
    '''    logging.info("history mutation worker loop enter")\n    while not stop_event.is_set():\n''',
    '''    retry_episode = RetryEpisode()\n    logging.info("history mutation worker loop enter")\n    while not stop_event.is_set():\n''',
)
replace_once(
    "worktrace/services/history_mutation_job_service.py",
    '''        try:\n            processed = run_pending_jobs(limit=1)\n        except Exception:\n            logging.exception("history mutation worker error")\n            health.failed("history_iteration_failed")\n            processed = 0\n        else:\n            health.succeeded()\n        if processed:\n            continue\n        stop_event.wait(_WORKER_IDLE_SECONDS)\n''',
    '''        try:\n            processed = run_pending_jobs(limit=1)\n        except Exception:\n            retry = retry_episode.failed("history_iteration_failed")\n            health.failed("history_iteration_failed")\n            if retry.detail_log_due:\n                logging.warning("history mutation worker error", exc_info=True)\n            elif retry.summary_log_due:\n                logging.warning(\n                    "history mutation worker failure continues consecutive=%s elapsed_seconds=%.1f",\n                    retry.attempt,\n                    retry.elapsed_seconds,\n                )\n            stop_event.wait(max(_WORKER_IDLE_SECONDS, retry.delay_seconds))\n            continue\n        recovery = retry_episode.succeeded()\n        health.succeeded()\n        if recovery.recovered:\n            logging.info(\n                "history mutation worker recovered attempts=%s elapsed_seconds=%.1f",\n                recovery.attempts,\n                recovery.elapsed_seconds,\n            )\n        if processed:\n            continue\n        stop_event.wait(_WORKER_IDLE_SECONDS)\n''',
)

replace_once(
    "worktrace/services/recovery_service.py",
    '''    interval = max(0.1, float(poll_seconds))\n    logging.info("startup recovery continuation worker loop enter")\n    while not stop_event.is_set():\n''',
    '''    interval = max(0.1, float(poll_seconds))\n    discovery_retry = RetryEpisode()\n    logging.info("startup recovery continuation worker loop enter")\n    while not stop_event.is_set():\n''',
)
replace_once(
    "worktrace/services/recovery_service.py",
    '''            if not jobs:\n                health.succeeded()\n                stop_event.wait(interval)\n                continue\n\n            job = jobs[0]\n''',
    '''            recovery = discovery_retry.succeeded()\n            if recovery.recovered:\n                logging.info(\n                    "startup recovery discovery recovered code=%s attempts=%s elapsed_seconds=%.1f",\n                    recovery.code,\n                    recovery.attempts,\n                    recovery.elapsed_seconds,\n                )\n            if not jobs:\n                health.succeeded()\n                stop_event.wait(interval)\n                continue\n\n            job = jobs[0]\n''',
)
replace_once(
    "worktrace/services/recovery_service.py",
    '''        except Exception as exc:\n            code = _classify_recovery_failure(exc)\n            job_id = int(job["id"]) if job is not None else None\n            logging.exception(\n                "startup recovery continuation failed job_id=%s code=%s",\n                job_id,\n                code.value,\n            )\n            if job_id is not None:\n                _record_recovery_failure_safely(job_id, code)\n            health.failed(code.value)\n            stop_event.wait(interval)\n        else:\n            health.succeeded()\n''',
    '''        except Exception as exc:\n            code = _classify_recovery_failure(exc)\n            job_id = int(job["id"]) if job is not None else None\n            if job_id is None:\n                retry = discovery_retry.failed(code.value)\n                if retry.detail_log_due:\n                    logging.warning(\n                        "startup recovery discovery failed code=%s",\n                        code.value,\n                        exc_info=True,\n                    )\n                elif retry.summary_log_due:\n                    logging.warning(\n                        "startup recovery discovery failure continues code=%s consecutive=%s elapsed_seconds=%.1f",\n                        code.value,\n                        retry.attempt,\n                        retry.elapsed_seconds,\n                    )\n                health.failed(code.value)\n                stop_event.wait(max(interval, retry.delay_seconds))\n                continue\n            logging.warning(\n                "startup recovery continuation failed job_id=%s code=%s",\n                job_id,\n                code.value,\n                exc_info=True,\n            )\n            _record_recovery_failure_safely(job_id, code)\n            health.failed(code.value)\n            stop_event.wait(interval)\n        else:\n            health.succeeded()\n''',
)

replace_once(
    "worktrace/services/folder_index_service.py",
    '''    logging.info("folder index worker loop enter")\n    next_hot_refresh_at = 0.0\n    startup_reconciliation_pending = True\n''',
    '''    retry_episode = RetryEpisode(\n        initial_delay_seconds=_WORKER_IDLE_SECONDS,\n        max_delay_seconds=30.0,\n    )\n    logging.info("folder index worker loop enter")\n    next_hot_refresh_at = 0.0\n    startup_reconciliation_pending = True\n''',
)
replace_once(
    "worktrace/services/folder_index_service.py",
    '''                startup_reconciliation_pending = False\n                health.succeeded()\n                _wait_for_worker()\n                continue\n''',
    '''                startup_reconciliation_pending = False\n                recovery = retry_episode.succeeded()\n                health.succeeded()\n                if recovery.recovered:\n                    logging.info(\n                        "folder index worker recovered code=%s attempts=%s elapsed_seconds=%.1f",\n                        recovery.code,\n                        recovery.attempts,\n                        recovery.elapsed_seconds,\n                    )\n                _wait_for_worker()\n                continue\n''',
)
replace_once(
    "worktrace/services/folder_index_service.py",
    '''            health.succeeded()\n            _wait_for_worker()\n        except Exception:\n            if startup_reconciliation_pending:\n                logging.exception("folder index startup reconciliation failed")\n                health.failed("folder_index_startup_failed")\n            else:\n                logging.exception("folder index worker error")\n                health.failed("folder_index_iteration_failed")\n            _wait_for_worker()\n''',
    '''            recovery = retry_episode.succeeded()\n            health.succeeded()\n            if recovery.recovered:\n                logging.info(\n                    "folder index worker recovered code=%s attempts=%s elapsed_seconds=%.1f",\n                    recovery.code,\n                    recovery.attempts,\n                    recovery.elapsed_seconds,\n                )\n            _wait_for_worker()\n        except Exception:\n            code = (\n                "folder_index_startup_failed"\n                if startup_reconciliation_pending\n                else "folder_index_iteration_failed"\n            )\n            retry = retry_episode.failed(code)\n            health.failed(code)\n            if retry.detail_log_due:\n                logging.warning(\n                    "folder index worker failure code=%s",\n                    code,\n                    exc_info=True,\n                )\n            elif retry.summary_log_due:\n                logging.warning(\n                    "folder index worker failure continues code=%s consecutive=%s elapsed_seconds=%.1f",\n                    code,\n                    retry.attempt,\n                    retry.elapsed_seconds,\n                )\n            _wait_for_worker(max(_WORKER_IDLE_SECONDS, retry.delay_seconds))\n''',
)
replace_once(
    "worktrace/services/folder_index_service.py",
    '''def _wait_for_worker() -> None:\n    _WORKER_WAKE_EVENT.wait(_WORKER_IDLE_SECONDS)\n    _WORKER_WAKE_EVENT.clear()\n''',
    '''def _wait_for_worker(timeout_seconds: float | None = None) -> None:\n    timeout = (\n        _WORKER_IDLE_SECONDS\n        if timeout_seconds is None\n        else max(0.0, float(timeout_seconds))\n    )\n    _WORKER_WAKE_EVENT.wait(timeout)\n    _WORKER_WAKE_EVENT.clear()\n''',
)

replace_once(
    "worktrace/runtime/collector_supervisor.py",
    '''        logging.info("collector supervisor worker loop enter")\n        health.succeeded()\n        while not stop_event.wait(self._poll_seconds):\n            if self._runtime.stop_event.is_set():\n                break\n            try:\n                self.check_once()\n            except Exception:\n                health.failed("collector_supervisor_iteration_failed")\n                logging.exception("collector supervisor check failed")\n            else:\n                health.succeeded()\n        logging.info("collector supervisor worker loop exit")\n''',
    '''        logging.info("collector supervisor worker loop enter")\n        retry_episode = RetryEpisode(\n            initial_delay_seconds=self._poll_seconds,\n            max_delay_seconds=30.0,\n            monotonic_func=self._monotonic,\n        )\n        health.succeeded()\n        delay = self._poll_seconds\n        while not stop_event.wait(delay):\n            delay = self._poll_seconds\n            if self._runtime.stop_event.is_set():\n                break\n            try:\n                self.check_once()\n            except Exception:\n                retry = retry_episode.failed("collector_supervisor_iteration_failed")\n                health.failed("collector_supervisor_iteration_failed")\n                if retry.detail_log_due:\n                    logging.warning("collector supervisor check failed", exc_info=True)\n                elif retry.summary_log_due:\n                    logging.warning(\n                        "collector supervisor failure continues consecutive=%s elapsed_seconds=%.1f",\n                        retry.attempt,\n                        retry.elapsed_seconds,\n                    )\n                delay = max(self._poll_seconds, retry.delay_seconds)\n            else:\n                recovery = retry_episode.succeeded()\n                health.succeeded()\n                if recovery.recovered:\n                    logging.info(\n                        "collector supervisor recovered attempts=%s elapsed_seconds=%.1f",\n                        recovery.attempts,\n                        recovery.elapsed_seconds,\n                    )\n        logging.info("collector supervisor worker loop exit")\n''',
)
replace_once(
    "worktrace/runtime/collector_supervisor.py",
    '''    def _liveness(self) -> dict[str, object]:\n        reader = getattr(self._runtime, "collection_liveness_snapshot", None)\n        if not callable(reader):\n            return {}\n        try:\n            return dict(reader())\n        except Exception:\n            logging.exception("collector supervisor liveness read failed")\n            return {"state": "recovery_required", "live_eligible": False}\n''',
    '''    def _liveness(self) -> dict[str, object]:\n        reader = getattr(self._runtime, "collection_liveness_snapshot", None)\n        if not callable(reader):\n            return {}\n        return dict(reader())\n''',
)

write_new(
    "worktrace/logging_config.py",
    '''"""Bounded application file logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 4
_FORMAT = "%(asctime)s %(levelname)s %(message)s"
_OWNED_MARKER = "_worktrace_owned_file_handler"


def configure_file_logging(
    log_path,
    *,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
) -> RotatingFileHandler:
    """Install one WorkTrace-owned rotating handler without disturbing host handlers."""

    root = logging.getLogger()
    for handler in tuple(root.handlers):
        if getattr(handler, _OWNED_MARKER, False):
            root.removeHandler(handler)
            handler.close()

    path = Path(log_path)
    handler = RotatingFileHandler(
        path,
        maxBytes=max(1, int(max_bytes)),
        backupCount=max(1, int(backup_count)),
        encoding="utf-8",
        delay=True,
    )
    setattr(handler, _OWNED_MARKER, True)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return handler


__all__ = ["configure_file_logging"]
''',
)

replace_once(
    "worktrace/main.py",
    '''def setup_logging(log_path) -> None:\n    logging.basicConfig(\n        filename=log_path,\n        level=logging.INFO,\n        format="%(asctime)s %(levelname)s %(message)s",\n        encoding="utf-8",\n    )\n''',
    '''def setup_logging(log_path) -> None:\n    from .logging_config import configure_file_logging\n\n    configure_file_logging(log_path)\n''',
)
replace_once(
    "worktrace/webview_main.py",
    '''def setup_logging(log_path) -> None:\n    logging.basicConfig(\n        filename=log_path,\n        level=logging.INFO,\n        format="%(asctime)s %(levelname)s %(message)s",\n        encoding="utf-8",\n    )\n''',
    '''def setup_logging(log_path) -> None:\n    from .logging_config import configure_file_logging\n\n    configure_file_logging(log_path)\n''',
)

write_new(
    "tests/test_retry_state.py",
    '''from __future__ import annotations

import pytest

from worktrace.retry_state import RetryEpisode

pytestmark = pytest.mark.unit


def test_retry_episode_bounds_backoff_and_throttles_repeated_detail_logs():
    now = {"value": 100.0}
    episode = RetryEpisode(
        initial_delay_seconds=1.0,
        max_delay_seconds=4.0,
        summary_interval_seconds=10.0,
        monotonic_func=lambda: now["value"],
    )

    first = episode.failed("database_busy")
    assert first.attempt == 1
    assert first.delay_seconds == 1.0
    assert first.detail_log_due is True
    assert first.summary_log_due is False

    now["value"] += 1.0
    second = episode.failed("database_busy")
    assert second.attempt == 2
    assert second.delay_seconds == 2.0
    assert second.detail_log_due is False
    assert second.summary_log_due is False

    now["value"] += 10.0
    third = episode.failed("database_busy")
    assert third.attempt == 3
    assert third.delay_seconds == 4.0
    assert third.summary_log_due is True

    recovery = episode.succeeded()
    assert recovery.recovered is True
    assert recovery.code == "database_busy"
    assert recovery.attempts == 3

    restarted = episode.failed("database_busy")
    assert restarted.attempt == 1
    assert restarted.detail_log_due is True


def test_retry_episode_treats_code_change_as_new_diagnostic_detail():
    episode = RetryEpisode(initial_delay_seconds=0.0, max_delay_seconds=0.0)
    episode.failed("database_busy")
    changed = episode.failed("database_generation_changed")
    assert changed.attempt == 1
    assert changed.code_changed is True
    assert changed.detail_log_due is True
    assert changed.delay_seconds == 0.0
''',
)

write_new(
    "tests/test_collector_observation_absence.py",
    '''from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

import pytest

from worktrace.collector import collector as collector_mod
from worktrace.collector.collector import run_collector
from worktrace.platforms.windows_adapter import WindowsAdapter
from worktrace.services import privacy_gate_service, settings_service

pytestmark = [pytest.mark.db, pytest.mark.collector_runtime]


class _Resolver:
    def privacy_path_required(self, _process_name, _title):
        return False

    def resolve(self, *_args):
        return None

    def reset(self):
        return None


def test_windows_foreground_absence_is_not_an_adapter_failure(monkeypatch):
    class PsutilError(Exception):
        pass

    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(Error=PsutilError, Process=lambda _pid: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32gui",
        SimpleNamespace(GetForegroundWindow=lambda: 0),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(GetWindowThreadProcessId=lambda _hwnd: (0, 0)),
    )

    adapter = WindowsAdapter(path_resolver=_Resolver())
    assert adapter.get_active_window() is None


class _IdleAdapter:
    def __init__(self) -> None:
        self.active_calls = 0
        self.idle_calls = 0
        self.clipboard_calls = 0

    def get_active_window(self):
        self.active_calls += 1
        raise AssertionError("foreground sampling must be skipped once idle is known")

    def get_idle_seconds(self):
        self.idle_calls += 1
        return 60

    def get_clipboard_events(self):
        self.clipboard_calls += 1
        raise AssertionError("clipboard drain must be skipped while idle")

    def set_clipboard_capture_enabled(self, _enabled: bool) -> None:
        return None


class _NoForegroundAdapter:
    def __init__(self) -> None:
        self.active_calls = 0
        self.idle_calls = 0
        self.clipboard_calls = 0

    def get_active_window(self):
        self.active_calls += 1
        return None

    def get_idle_seconds(self):
        self.idle_calls += 1
        return 0

    def get_clipboard_events(self):
        self.clipboard_calls += 1
        return []

    def set_clipboard_capture_enabled(self, _enabled: bool) -> None:
        return None


def _stop_after_one_poll(monkeypatch, stop_event):
    def fake_sleep(_stop_event, _control, next_poll_deadline):
        stop_event.set()
        return next_poll_deadline + 1.0

    monkeypatch.setattr(collector_mod, "_sleep_until_next_poll", fake_sleep)


def test_idle_short_circuits_foreground_and_clipboard_sampling(temp_db, monkeypatch):
    privacy_gate_service.accept_privacy_notice()
    settings_service.set_setting("idle_threshold_seconds", "1")
    stop_event = threading.Event()
    adapter = _IdleAdapter()
    _stop_after_one_poll(monkeypatch, stop_event)

    run_collector(adapter, stop_event)

    assert adapter.idle_calls == 1
    assert adapter.active_calls == 0
    assert adapter.clipboard_calls == 0


def test_no_foreground_window_is_a_normal_observation_gap(temp_db, monkeypatch):
    privacy_gate_service.accept_privacy_notice()
    settings_service.set_setting("idle_threshold_seconds", "300")
    stop_event = threading.Event()
    adapter = _NoForegroundAdapter()
    _stop_after_one_poll(monkeypatch, stop_event)

    run_collector(adapter, stop_event)

    assert adapter.idle_calls == 1
    assert adapter.active_calls == 1
    assert adapter.clipboard_calls == 0
    assert settings_service.get_setting("collector_consecutive_failures") == "0"
''',
)

write_new(
    "tests/test_logging_config.py",
    '''from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import pytest

from worktrace.logging_config import configure_file_logging

pytestmark = pytest.mark.unit


def test_application_file_logging_is_bounded_without_removing_host_handlers(tmp_path):
    root = logging.getLogger()
    host_handler = logging.NullHandler()
    root.addHandler(host_handler)
    handler = None
    try:
        handler = configure_file_logging(
            tmp_path / "worktrace.log",
            max_bytes=1024,
            backup_count=2,
        )
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == 1024
        assert handler.backupCount == 2
        assert host_handler in root.handlers
    finally:
        if handler is not None and handler in root.handlers:
            root.removeHandler(handler)
            handler.close()
        if host_handler in root.handlers:
            root.removeHandler(host_handler)
''',
)

print("transient runtime hardening patch applied")
