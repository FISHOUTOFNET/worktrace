# Runtime liveness contract

This document narrows the release-time liveness rules for process-owned workers,
desktop restore entry points and the FD Work helper executor. It supplements the
main architecture contract without moving business ownership between services.

## AppRuntime-owned workers

Three facts are intentionally separate:

- **READY** means `AppRuntime` owns a live wrapper thread and can stop or re-enter
  the declared `WorkerSpec` target. READY must not wait for fallible SQLite or
  filesystem work.
- **SERVING** means the current target invocation has established its worker loop
  by reporting successful iteration health. A target restart clears SERVING.
- **HEALTH** is the worker's ongoing iteration history. After SERVING, isolated
  recoverable failures may use the existing consecutive-failure threshold.

Runtime convergence follows those facts rather than raw thread liveness. During
initial startup, READY-but-not-yet-SERVING workers keep the runtime STARTING. A
failure before SERVING degrades immediately. An unexpected return or unhandled
exception clears SERVING before bounded restart backoff, so another worker's
success cannot wash the runtime back to RUNNING while the failed target is absent.
RUNNING is restored only after the replacement invocation reports success.

The wrapper owns thread start, stop, unexpected target exit and bounded restart.
Worker functions own database/filesystem/domain iteration errors and stable health
codes. Database BUSY/LOCKED, maintenance gates and ordinary job failures must stay
inside the worker's own retry boundary whenever they can be classified there.
No worker may create a parallel replacement thread for itself.

Folder-index startup reconciliation is an ordinary retryable worker iteration: it
runs only after the database write gate and privacy gate allow the work. Startup
recovery job discovery is likewise inside the recovery worker's own exception
classification boundary, so SQLite contention is not promoted to an AppRuntime
wrapper crash.

## Desktop restore capability

A successful tray startup is not a permanent promise that the user still has a
restore entry point. `WindowsTrayHost.can_restore_window()` is authoritative and
is true only while the tray owner thread is live, the message window exists, the
icon handle exists, the notification icon is registered with Explorer and stop
has not been requested.

`DesktopShellController` may hide the main window only while that live capability
is true. It rechecks before the deferred native hide and immediately after the
hide. If the tray entry disappears in that interval, the shell restores the main
window instead of leaving the process inaccessible.

Win32 Event wait wrappers distinguish `WAIT_OBJECT_0`, `WAIT_TIMEOUT`,
`WAIT_FAILED` and unexpected return codes. Only `WAIT_TIMEOUT` is a normal false
result. Failed or unknown waits raise stable owner errors and enter the existing
stop-aware listener retry path rather than becoming a tight alive-but-broken loop.

## Derived worker observability

Collector health and derived-worker health are separate projections. Application
status may remain `running` while a derived worker is degraded, but the user-facing
status must then say that some background tasks are abnormal instead of silently
showing only `记录中`. Public status exposes only aggregate state and stable worker
names; tracebacks, paths and internal exception text remain private diagnostics.

## FD Work window executor

Exactly one executor worker owns helper-window mutations. Each request has one
absolute deadline covering FIFO wait, synchronous command execution and callback
settlement.

A command that returns but misses its callback deadline remains the existing
recoverable `callback_timeout`; later FIFO work may continue. A request that
expires before execution becomes `request_timeout` and is skipped when dequeued.
If the current synchronous pywebview command itself has not returned by its
absolute deadline, Python cannot prove that mutation has stopped. That executor
generation therefore latches `executor_stalled`, releases waiting callers, rejects
queued and future commands and never starts a second owner thread. If the old
command later returns, the original worker exits without executing queued window
mutations. Recovery requires the surrounding helper lifecycle to establish a new,
non-overlapping owner only after the old executor is no longer capable of window
mutation.
