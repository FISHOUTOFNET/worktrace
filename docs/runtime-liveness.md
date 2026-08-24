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
  by either reporting successful iteration health or reaching an intentional
  maintenance pause gate. A target restart clears SERVING.
- **HEALTH** is the worker's ongoing iteration history. After SERVING, isolated
  recoverable failures may use the existing consecutive-failure threshold.

Runtime convergence follows those facts rather than raw thread liveness. During
initial startup, READY-but-not-yet-SERVING workers keep the runtime STARTING. A
failure before SERVING degrades immediately. An unexpected return or unhandled
exception clears SERVING before bounded restart backoff, so another worker's
success cannot wash the runtime back to RUNNING while the failed target is absent.
RUNNING is restored only after the replacement invocation establishes SERVING
again.

The wrapper owns thread start, stop, unexpected target exit and bounded restart.
Worker functions own database/filesystem/domain iteration errors and stable health
codes. Database BUSY/LOCKED, maintenance gates and ordinary job failures must stay
inside the worker's own retry boundary whenever they can be classified there.
No worker may create a parallel replacement thread for itself.

Once a worker has SERVED, `AppRuntime` also owns a process-local monotonic progress
lease declared by that worker's `WorkerSpec`. The independent progress watchdog
may mark an alive worker degraded when it stops reporting progress beyond that
lease, but it must never start a second owner while the original thread remains
alive. Intentional maintenance pauses suspend the progress lease. A later health
report from the same owner may restore RUNNING without replacing the thread.
Process-local monotonic progress timestamps are diagnostic inputs only and are not
part of the public worker-health payload.

Folder-index startup reconciliation is an ordinary retryable worker iteration: it
runs only after the database write gate and privacy gate allow the work. Startup
recovery job discovery is likewise inside the recovery worker's own exception
classification boundary, so SQLite contention is not promoted to an AppRuntime
wrapper crash.

## Collector observation authority

Collector wall-clock samples are candidates, not automatically durable activity
time. Before entering fallible or potentially blocking observation work, the
Collector records its last safe wall-clock boundary. After the complete sample
returns, it must pass the same `ClockTracker` monotonic stall/clock-discontinuity
policy before any state transition may advance durable activity time.

A late successful sample is discarded before transition. A late failure, fatal
shutdown, or ordinary shutdown cannot close activity past the last safe boundary.
The activity recorder and fact repository therefore remain unaware of Collector
stall policy; they only receive observation times that the Collector has already
authorized. A later discontinuity correction must not be relied upon to shrink a
previously persisted duration.

## WebView live projection authority

Receiving a runtime envelope does not by itself grant another live-time lease.
Live projection requires both a fresh client receipt and a fresh source clock
sample, with materially future-dated source clocks failing closed. A stale
refresh-state response may be observed for recovery coordination but cannot
release a pending authoritative page rebase.

All presentation paths share one live-projection capability. Cached Timeline,
Overview or Statistics data may reuse durable values, but direct `Date.now()`
clock projection is permitted only while the current runtime is fresh and the
clock identity belongs to that runtime. Presentation code does not own freshness
or rebase policy.

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

A visible WebView shell must also keep its recovery heartbeat even when the first
bridge-backed revision check after restore fails. Restore probing and heartbeat
ownership are deliberately decoupled: revision failure remains fail-closed for
runtime data, while the heartbeat stays alive so later bridge recovery can be
detected. Promise rejection from a heartbeat revision probe is contained by the
heartbeat loop and does not terminate the timer.

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
