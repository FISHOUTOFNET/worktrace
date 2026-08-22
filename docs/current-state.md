# WorkTrace Current State

> Default entry point for developers and AI tools. This is the pre-release, current-only product contract; historical notes do not override it. Historical WebView migration notes are archived in [`history/webview-phases.md`](history/webview-phases.md).

## Product
- Windows desktop application using Python, SQLite, pywebview and WebView2.
- Local-only: no registration, cloud sync, administrator privilege, screenshots, screen recording, OCR or keyboard logging.
- WebView is the only shipping visual UI. An authorized `--background` cold start runs Collector/workers, tray, activation and update-shutdown without creating a WebView. After the first UI open, a healthy tray host makes window close hide the window while collection continues; tray Exit ends either the headless wait or WebView loop and reaches `AppRuntime.shutdown()`.
- The privacy notice is fail-closed; sensitive workers and clipboard capture do not start before acceptance.
- CSV export is the only current public export; Excel, PDF and timesheet-template export are unsupported in the shipping WebView.

## Composition and lifecycle
```text
webview_main -> AppRuntime + one ApplicationServices graph
             -> authorized background: DeferredUIGate + tray (no WebView)
             -> first open/foreground: DesktopShellController + WebViewBridge
```
- `AppRuntime` owns the single-instance lease, Collector and every background worker thread handle.
- `DeferredUIGate` coalesces tray/activation open requests and wakes the main thread for the once-only initial UI bootstrap; exit can wake a process that has no window. After binding, `DesktopShellController` owns visible/hidden/exiting window state. Neither capability manages the database, Collector or workers.
- `ApplicationServices` is explicit composition with no service locator. It injects core project callbacks and fixed lifecycle tuples; bridges call explicit capabilities.
- Background composition builds `ApplicationServices` once with a late-bound FD Work interaction coordinator. The first UI binds the existing service graph to the real coordinator/window controller; it never creates another runtime or services graph.
- Project Rules uses an external-identity port; Settings/Backup use a post-commit lifecycle hook. None imports or instantiates FD Work.
- Privacy startup sees generic participants; a typed main-window sink owns JSON callback delivery and fails softly for stale/shutdown windows.
- `RuntimeMaintenanceCoordinator` solely owns snapshot/replacement ordering and the stable fail-closed latch.
- `CollectorControl`/`CollectorStateMachine` own command identity, terminal states and collection transitions; the maintenance command atomically seals an open activity and enqueues eligible inference.

Workers are declared by `WorkerSpec` in one `AppRuntime` registry. Readiness needs successful initialization and an explicit ready signal. AppRuntime alone publishes lifecycle state, joins handles and releases the lease after every writer stops.

## Maintenance
Collector maintenance is not user pause:
```text
OPERATIONAL -> HOLD_REQUESTED -> SEALING -> HELD
HELD -> RESETTING -> HELD
HELD -> RELEASE_REQUESTED -> OPERATIONAL
```
A successful hold seals the current activity, clears process-local activity state and blocks Collector writes without changing durable `user_paused`. The coordinator drains writers, enters exclusive ownership, performs the operation, restores durable state, releases the hold and verifies terminal OPERATIONAL before leaving the exclusive scope. Pre-commit failure uses the same order. Durable restore failure sends no release; Collector remains HELD and fail-closed is set. Unknown hold/reset/release outcomes also fail closed. Ordinary pause/resume cannot clear that latch; only explicit verified recovery may.

## Transaction and replacement owners
`DomainUnitOfWork` owns ordinary root/nested SQLite transactions, rollback-only propagation, declared effects and explicitly changed effects. SQL text, row counts, `total_changes` and commit hooks never infer business semantics. `mark_changed(namespace)` requires a declared namespace; missing or undeclared effects are contract errors. Root commit bumps each marked namespace at most once. No-op, rollback, worker progress, checkpoint and receipt-only writes publish no business generation. Effective report operations publish `REPORT_STRUCTURE` once; no-effect and duplicate receipts do not publish.

Permanent project deletion is an application-level workflow owned by `project_deletion_command_service`. It keeps project validation, assignment release, active history-job guarding, rule deletion and project-row deletion in one root `DomainUnitOfWork`. Each domain contributes a narrow in-transaction capability; `project_service` owns project identity writes and does not query history-job or rule tables to coordinate deletion.

`DatabaseReplacementUnitOfWork` solely owns the replacement epoch, live commit and process-local generation publication. Secure import creates decrypted staging inside one `ValidatedStaging` scope, fully validates it before maintenance and deletes it after success, maintenance rejection or any failure. Staging content and semantic validation failures raise `BackupCorruptedError`; local staging infrastructure failures raise `BackupStagingInfrastructureError`. Neither changes live data, generations or recovery state. Once staging is valid, ordinary live apply/generation/validation/commit/I/O failures raise `BackupReplacementError` with the internal cause chained. Maintenance/recovery errors remain separate.

## Database content manifest
`database_content_manifest` is the only current-schema table inventory. Each table has a `TableCategory`; backup, clear, privacy wipe, delete order and schema coverage derive their sets from this manifest.

## Report replay identity
Report replay is members-only. Admission revision and durable replay identity are separate. Copy, merge, split and undo form a supersede graph. Non-members legacy revision replay is rejected at the read boundary. Operation payload version is `6`; repository, replay engine and backup validator share one contract owner.

## Project, rule and privacy invariants
Schema seeding alone creates system projects. Stable identity controls reserved behavior. Ordinary commands cannot create, rename, archive, delete or toggle system projects; missing system rows are reported unavailable rather than recreated by normal API calls. Shipped lifecycle capabilities are exactly: user project create / edit / enable-disable / archive / permanent delete.

Keyword/folder mutations use the canonical rule command owner for project type, normalized pattern, duplicate and batch-atomicity validation. Excluded rules use explicit catalog commands. Classification/privacy generations publish only after commit; no-op and rollback publish nothing and each affected namespace bumps at most once. Privacy classification is a pure `ExclusionDecision` query; unresolved private paths fail closed while Collector alone schedules folder-index refresh.

## Current data contracts
- Database schema: **v13**.
- Encrypted backup payload: **v6**.
- Report operation payload: **v6**.
- Frontend live-time transport: **LiveClock v2**.
- Old schemas, payloads, replay bindings and LiveClock aliases are unsupported.

Exact versions and DTO keys are in [`runtime-contracts.md`](runtime-contracts.md).

## Live display
Every live-capable row has one exact nine-field clock: `current_live` for current activity, `aggregate_live` for aggregates and `static_closed` for closed rows. Overlay occurs only when runtime and SQLite identities agree, including the replacement epoch. Overview owns current-activity presentation; Timeline matches one persisted open activity ID to one live entry. The frontend validates exact keys/types, never selects among candidate clocks and never carries duration into a new identity. Invalid clocks stop ticking, retain durable seconds and request bounded reconciliation.

## Pages and writes
- Overview: today total, current atomic activity snapshot, an unheaded single-line project/uncategorized distribution bar, and full-width recent merged report sessions. Uncategorized participates in the same Top 3 + other ranking as projects. The bar is display-only; current/recent rows hand off to Timeline and shared row attention facts remain in their DTOs.
- Timeline: reverse chronological sessions, authoritative project filtering, composition-safe debounced autosave for completed sessions, always-visible activity details, direct two-step deletion, and a compact-window focus-trapped Drawer. In-progress sessions are selectable but read-only; their detail selection is maintained in-memory by exact key or unique first-activity anchor.
- Statistics/Export: this-month default with all-time/custom options, optional project scope, automatic latest-request acceptance, and display-safe CSV bound to the accepted export ticket.
- Project Rules: searchable/sortable summaries, direct actions and Drawers. Project names remain ordinary editable local text whether FD Work is disabled or enabled. When FD Work is enabled, the same project-name input may instead be populated by the explicit native FD Work picker; only a valid one-use picker proof creates or rebinds the durable FD Work identity. Typing a name without a proof creates a local project, and manually renaming a bound project converts it to local by invalidating/clearing its binding. WorkTrace provides no cross-window autocomplete.
- `window.WorkTraceApp` is a namespace, not a state owner. Pages reset their own transient state; FD Work owns picker/editor identity state behind `projectIdentity`. Project Rules supplies narrow host callbacks and FD Work does not read Rules panel session/busy/editing globals.
- Settings/Privacy: four categories. General owns authoritative HKCU launch state and clipboard control; Privacy, Data and Backup, and Advanced retain their responsibilities. Secret inputs remain local and are cleared after use.

Timeline edits on completed sessions allow project, description and duration changes. New description edits are limited to 200 characters while the durable 2000-character read/replay boundary remains compatible with historical data. Duration edits carry a required `duration_touched` intent through the WebView, API and report operation owner: false ignores the submitted duration, true plus null clears an override, and true plus an integer sets the normalized override. Rule batches are atomic, manual assignments are preserved, and statistics/export use persisted report facts rather than frontend time.

FD Work is shared by Settings, Timeline and Project Rules. Its sidecar stays outside the main schema/backup. A durable project binding is identity truth independent of whether the plugin is currently enabled; the plugin switch controls FD Work interaction availability, not whether that binding exists. Project Rules and Timeline consume binding state through the generic project-identity capability, while only verified bindings authorize Timeline fill. Local projects remain valid WorkTrace projects and Timeline shows them as non-FD-Work projects rather than attempting a fill. Privacy gates startup and passive probes stay hidden. Auth/picker are user-owned; fill/save is exclusively `automation_fill`-owned through field verification, the explicit Save click and verified save completion. Adapter v5 reports success only on positive completion evidence such as a new success notice, a reinitialized entry form or a closed editor with the unique create action available. Save-button loading that merely settles to idle is not success. A new error/validation signal or an otherwise unprovable post-click result fails closed; an ambiguous result is surfaced as `save_outcome_unknown`, the helper remains visible for user verification and WorkTrace does not retry automatically. Helper close/navigation/disable/shutdown invalidate the active generation; a delayed close callback from an older helper generation cannot cancel a newer operation. Selection uses FD Work's native Ant Select only. Adapter v5 remains generation-guarded; v4 bindings remain valid. WorkTrace never reads or exports credentials.

## Validation
Local development uses explicit pytest targets or marker shards. Standard CI runs the full Python non-benchmark suite, `node --test tests/webview/*.test.js`, the FD Work DOM fixture and typography acceptance, plus Windows executable/installer build smoke.

Standard CI validates one exact revision. Pytest marker validation is strict and owned by `pytest.ini`; Python failure diagnostics are artifact-only. Installer lifecycle acceptance and optional performance/timing workflows remain separate from Standard CI.
