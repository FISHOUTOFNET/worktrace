from __future__ import annotations

from pathlib import Path
import re
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise AssertionError(
            f"{path}: expected one replacement, found {count}: {old[:100]!r}"
        )
    write(path, content.replace(old, new, 1))


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    content = read(path)
    start_index = content.find(start)
    if start_index < 0:
        raise AssertionError(f"{path}: start marker missing: {start!r}")
    end_index = content.find(end, start_index)
    if end_index < 0:
        raise AssertionError(f"{path}: end marker missing: {end!r}")
    end_index += len(end)
    write(path, content[:start_index] + replacement + content[end_index:])


def overwrite_runtime_contract() -> None:
    write(
        "worktrace/services/live_runtime_envelope_service.py",
        textwrap.dedent(
            '''\
            """Canonical live-runtime transport envelope.

            Page services own domain DTOs. This module only projects an already-built
            page payload into the versioned transport contract consumed by the WebView.
            It performs no database reads and takes no runtime samples.
            """

            from __future__ import annotations

            from typing import Any, Mapping

            LIVE_RUNTIME_SCHEMA_VERSION = 1


            def _mapping(value: Any) -> dict[str, Any]:
                return dict(value) if isinstance(value, Mapping) else {}


            def build_live_runtime_envelope(
                payload: Mapping[str, Any],
                *,
                surface: str,
                scope_report_date: str | None = None,
                live_report_date: str | None = None,
            ) -> dict[str, Any]:
                """Build the sole versioned live-runtime transport contract."""

                live_clock = _mapping(payload.get("live_clock"))
                current_activity = _mapping(payload.get("current_activity"))
                scoped_date = str(
                    scope_report_date
                    or payload.get("report_date")
                    or payload.get("date")
                    or ""
                )
                live_date = str(
                    live_report_date
                    or payload.get("today")
                    or scoped_date
                    or ""
                )
                return {
                    "schema_version": LIVE_RUNTIME_SCHEMA_VERSION,
                    "surface": str(surface or ""),
                    "scope_report_date": scoped_date,
                    "live_report_date": live_date,
                    "collector_status": str(payload.get("collector_status") or ""),
                    "paused": bool(payload.get("paused")),
                    "status_display": str(payload.get("status_display") or ""),
                    "live_revision": str(payload.get("live_revision") or ""),
                    "structure_revision": str(payload.get("structure_revision") or ""),
                    "page_revision": str(payload.get("page_revision") or ""),
                    "sample_id": str(payload.get("sample_id") or ""),
                    "display_span_id": str(
                        payload.get("display_span_id")
                        or live_clock.get("display_span_id")
                        or ""
                    ),
                    "stable_live_key_hash": str(
                        payload.get("stable_live_key_hash")
                        or live_clock.get("stable_live_key_hash")
                        or current_activity.get("stable_live_key_hash")
                        or ""
                    ),
                    "current_activity_display_span_id": str(
                        current_activity.get("current_activity_display_span_id") or ""
                    ),
                    "current_resource_identity_hash": str(
                        current_activity.get("current_resource_identity_hash") or ""
                    ),
                    "live_clock": live_clock,
                    "current_activity": current_activity,
                }


            def attach_live_runtime_envelope(
                payload: dict[str, Any],
                *,
                surface: str,
                scope_report_date: str | None = None,
                live_report_date: str | None = None,
            ) -> dict[str, Any]:
                payload["runtime"] = build_live_runtime_envelope(
                    payload,
                    surface=surface,
                    scope_report_date=scope_report_date,
                    live_report_date=live_report_date,
                )
                return payload


            __all__ = [
                "LIVE_RUNTIME_SCHEMA_VERSION",
                "attach_live_runtime_envelope",
                "build_live_runtime_envelope",
            ]
            '''
        ),
    )

    write(
        "worktrace/api/view_model_api.py",
        textwrap.dedent(
            '''\
            """ViewModel API facade — sole bridge-facing page payload boundary."""

            from __future__ import annotations

            from typing import Any

            from ..services import refresh_state_view_model_service, timeline_service, view_model_service
            from ..services.live_display_service import build_current_activity_summary
            from ..services.live_runtime_envelope_service import attach_live_runtime_envelope
            from ..services.page_read_context import page_read_scope


            def _attach_runtime(
                payload: dict[str, Any],
                *,
                surface: str,
                scope_report_date: str | None = None,
            ) -> dict[str, Any]:
                live_report_date = str(
                    payload.get("today") or timeline_service.get_default_report_date()
                )
                return attach_live_runtime_envelope(
                    payload,
                    surface=surface,
                    scope_report_date=scope_report_date,
                    live_report_date=live_report_date,
                )


            def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
                with page_read_scope():
                    payload = view_model_service.get_overview_view_model(today)
                    return _attach_runtime(
                        payload,
                        surface="overview",
                        scope_report_date=str(payload.get("date") or today or ""),
                    )


            def get_timeline_view_model(report_date: str | None = None) -> dict[str, Any]:
                with page_read_scope():
                    payload = view_model_service.get_timeline_view_model(report_date)
                    return _attach_runtime(
                        payload,
                        surface="timeline",
                        scope_report_date=str(payload.get("date") or report_date or ""),
                    )


            def get_session_activity_summary_view_model(
                *,
                report_date: str | None = None,
                projection_instance_key: str,
                expected_projection_revision: str | None = None,
            ) -> dict[str, Any]:
                with page_read_scope():
                    payload = view_model_service.get_session_activity_summary_view_model(
                        report_date=report_date,
                        projection_instance_key=projection_instance_key,
                        expected_projection_revision=expected_projection_revision,
                    )
                    return _attach_runtime(
                        payload,
                        surface="details",
                        scope_report_date=str(payload.get("date") or report_date or ""),
                    )


            def get_refresh_state_view_model(report_date: str | None = None) -> dict[str, Any]:
                with page_read_scope():
                    payload = refresh_state_view_model_service.get_refresh_state_view_model(
                        report_date
                    )
                    return _attach_runtime(
                        payload,
                        surface="refresh",
                        scope_report_date=str(
                            payload.get("report_date") or report_date or ""
                        ),
                    )


            __all__ = [
                "build_current_activity_summary",
                "get_overview_view_model",
                "get_refresh_state_view_model",
                "get_session_activity_summary_view_model",
                "get_timeline_view_model",
            ]
            '''
        ),
    )


def migrate_runtime_store() -> None:
    replacement = textwrap.dedent(
        '''\
            var runtimeState = null;

            function frozenRuntime(value) {
                if (!value || typeof value !== "object") return null;
                var copy = Object.assign({}, value);
                if (copy.liveClock && typeof copy.liveClock === "object") {
                    copy.liveClock = Object.freeze(Object.assign({}, copy.liveClock));
                }
                if (copy.currentActivity && typeof copy.currentActivity === "object") {
                    copy.currentActivity = Object.freeze(Object.assign({}, copy.currentActivity));
                }
                return Object.freeze(copy);
            }

            function runtimeEnvelope(value) {
                if (!value || typeof value !== "object") return null;
                return value.runtime && typeof value.runtime === "object" ? value.runtime : value;
            }

            function normalizeRuntimeEnvelope(value, page, reportDate) {
                var envelope = runtimeEnvelope(value);
                if (!envelope || Number(envelope.schema_version || 0) !== 1) return null;
                var scopeDate = String(
                    envelope.scope_report_date
                    || reportDate
                    || App.runtimeReportDateForPage(page || App.currentPage || "overview", reportDate)
                    || ""
                );
                var liveDate = String(envelope.live_report_date || scopeDate || "");
                var liveClock = App.normalizeLiveClock
                    ? App.normalizeLiveClock(envelope.live_clock || null)
                    : (envelope.live_clock || null);
                if (scopeDate && liveDate && scopeDate !== liveDate) liveClock = null;
                return {
                    schemaVersion: 1,
                    surface: String(envelope.surface || page || App.currentPage || "overview"),
                    page: String(page || App.currentPage || envelope.surface || "overview"),
                    reportDate: scopeDate,
                    liveReportDate: liveDate,
                    liveClock: liveClock,
                    displaySpanId: String(envelope.display_span_id || (liveClock && liveClock.display_span_id) || ""),
                    stableLiveKeyHash: String(envelope.stable_live_key_hash || (liveClock && liveClock.stable_live_key_hash) || ""),
                    liveRevision: String(envelope.live_revision || ""),
                    structureRevision: String(envelope.structure_revision || ""),
                    pageRevision: String(envelope.page_revision || ""),
                    sampleId: String(envelope.sample_id || ""),
                    currentActivityDisplaySpanId: String(envelope.current_activity_display_span_id || ""),
                    currentResourceIdentityHash: String(envelope.current_resource_identity_hash || ""),
                    currentActivity: envelope.current_activity || {}
                };
            }

            var liveRuntimeStore = Object.freeze({
                get: function () { return runtimeState; },
                acceptEnvelope: function (value, page, reportDate) {
                    var next = normalizeRuntimeEnvelope(value, page, reportDate);
                    if (!next) return null;
                    var previous = runtimeState;
                    if (previous && previous.liveClock && next.liveClock
                        && App.sameLiveContinuity
                        && App.sameLiveContinuity(previous.liveClock, next.liveClock)
                        && App.rebaseIncomingClockWithoutRollback) {
                        next.liveClock = App.rebaseIncomingClockWithoutRollback(
                            previous.liveClock,
                            next.liveClock,
                            Date.now()
                        );
                    }
                    runtimeState = frozenRuntime(next);
                    return runtimeState;
                },
                reset: function () {
                    runtimeState = null;
                    return null;
                },
                setScope: function (page, reportDate) {
                    var existing = runtimeState;
                    if (!existing) return null;
                    runtimeState = frozenRuntime(Object.assign({}, existing, {
                        page: String(page || App.currentPage || "overview"),
                        reportDate: App.runtimeReportDateForPage(
                            page || App.currentPage || "overview",
                            reportDate
                        )
                    }));
                    return runtimeState;
                }
            });
            App.liveRuntimeStore = liveRuntimeStore;
            Object.defineProperty(App, "liveRuntime", {
                configurable: false,
                enumerable: true,
                get: function () { return liveRuntimeStore.get(); }
            });

            function resetClientGeneration()
        '''
    )
    replace_between(
        "worktrace/webview_ui/js/init.js",
        "    var runtimeState = App.liveRuntime || null;",
        "    function resetClientGeneration()",
        replacement,
    )
    replace_once(
        "worktrace/webview_ui/js/init.js",
        '        getRecentActivities: fixedBridgeMethod("get_recent_activities"),\n',
        "",
    )

    action_mappings = {
        '["timeline-hide-session", "hide_timeline_session"]': '["timeline-hide-session", "hide"]',
        '["timeline-merge-previous", "merge_timeline_session", "previous"]': '["timeline-merge-previous", "merge", "previous"]',
        '["timeline-merge-next", "merge_timeline_session", "next"]': '["timeline-merge-next", "merge", "next"]',
        '["timeline-split-session", "split_timeline_session"]': '["timeline-split-session", "split"]',
        '["timeline-copy-session", "copy_timeline_session"]': '["timeline-copy-session", "copy"]',
    }
    for old, new in action_mappings.items():
        replace_once("worktrace/webview_ui/js/init.js", old, new)


def migrate_core_runtime() -> None:
    path = "worktrace/webview_ui/js/core.js"
    content = read(path).replace("    App.liveRuntime = null;\n", "")
    content, count = re.subn(
        r"\n    function callBridge\(method\) \{.*?\n    App\.callBridge = callBridge;\n",
        "\n",
        content,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise AssertionError("core.js: dynamic bridge wrapper not found")
    write(path, content)

    replace_between(
        path,
        "    function payloadReportDate(payload, page, fallbackDate) {",
        "    App.payloadReportDate = payloadReportDate;",
        textwrap.dedent(
            '''\
                function payloadReportDate(payload, page, fallbackDate) {
                    var envelope = payload && payload.runtime && typeof payload.runtime === "object"
                        ? payload.runtime
                        : payload;
                    if (envelope && (envelope.scope_report_date || envelope.report_date || envelope.date)) {
                        return String(envelope.scope_report_date || envelope.report_date || envelope.date);
                    }
                    return runtimeReportDateForPage(page, fallbackDate);
                }
                App.payloadReportDate = payloadReportDate;
            '''
        ),
    )
    replace_between(
        path,
        "    function runtimeIdentityFromPayload(payload) {",
        "    App.runtimeIdentityFromPayload = runtimeIdentityFromPayload;",
        textwrap.dedent(
            '''\
                function runtimeIdentityFromPayload(payload) {
                    payload = payload || {};
                    var envelope = payload.runtime && typeof payload.runtime === "object"
                        ? payload.runtime
                        : payload;
                    var clock = normalizeLiveClock(envelope.live_clock || findClockInPayload(payload, false));
                    var current = envelope.current_activity || payload.current_activity || {};
                    return {
                        liveClock: isActiveLiveTime(clock) ? clock : null,
                        displaySpanId: String(envelope.display_span_id || (clock && clock.display_span_id) || ""),
                        stableLiveKeyHash: String(envelope.stable_live_key_hash || (clock && clock.stable_live_key_hash) || ""),
                        liveRevision: String(envelope.live_revision || ""),
                        pageRevision: String(envelope.page_revision || ""),
                        sampleId: String(envelope.sample_id || ""),
                        currentActivityDisplaySpanId: String(envelope.current_activity_display_span_id || current.current_activity_display_span_id || ""),
                        currentResourceIdentityHash: String(envelope.current_resource_identity_hash || current.current_resource_identity_hash || "")
                    };
                }
                App.runtimeIdentityFromPayload = runtimeIdentityFromPayload;
            '''
        ),
    )
    replace_between(
        path,
        "    function acceptLiveRuntimePayload(payload, page, reportDate, options) {",
        "    App.acceptLiveRuntimePayload = acceptLiveRuntimePayload;",
        textwrap.dedent(
            '''\
                function acceptLiveRuntimePayload(payload, page, reportDate, options) {
                    if (!payload || !payload.ok || !App.liveRuntimeStore) return false;
                    options = options || {};
                    var runtimePage = String(page || App.currentPage || "overview");
                    var runtimeDate = payloadReportDate(payload, runtimePage, reportDate);
                    var previous = App.liveRuntimeStore.get();
                    var previousKey = runtimeVisualContinuityKey(previous);
                    var accepted = App.liveRuntimeStore.acceptEnvelope(payload, runtimePage, runtimeDate);
                    if (!accepted) return false;
                    App.liveDisplayModel = payload.activity_display_model || null;
                    if (previousKey && previousKey !== runtimeVisualContinuityKey(accepted)) {
                        App._monotonicRenderState = {};
                    }
                    if (options.source === "refresh_state") App.lastRefreshState = payload;
                    return true;
                }
                App.acceptLiveRuntimePayload = acceptLiveRuntimePayload;
            '''
        ),
    )
    replace_between(
        path,
        "    function setLiveRuntimeScope(page, reportDate) {",
        "    App.setLiveRuntimeScope = setLiveRuntimeScope;",
        textwrap.dedent(
            '''\
                function setLiveRuntimeScope(page, reportDate) {
                    if (App.liveRuntimeStore) App.liveRuntimeStore.setScope(page, reportDate);
                }
                App.setLiveRuntimeScope = setLiveRuntimeScope;
            '''
        ),
    )
    replace_between(
        path,
        "    function getActiveLiveClock() {",
        "    App.getActiveLiveClock = getActiveLiveClock;",
        textwrap.dedent(
            '''\
                function getActiveLiveClock() {
                    var runtime = App.liveRuntimeStore ? App.liveRuntimeStore.get() : null;
                    if (!runtime || runtime.page !== (App.currentPage || "overview")) return null;
                    return runtime.liveClock || null;
                }
                App.getActiveLiveClock = getActiveLiveClock;
            '''
        ),
    )
    replace_between(
        path,
        "    function isPagePayloadCompatibleWithRuntime(payload, page, reportDate) {",
        "    App.isPagePayloadCompatibleWithRuntime = isPagePayloadCompatibleWithRuntime;",
        textwrap.dedent(
            '''\
                function isPagePayloadCompatibleWithRuntime(payload, page, reportDate) {
                    if (!payload || !payload.ok || !payload.runtime) return false;
                    var expectedPage = String(page || App.currentPage || "overview");
                    var expectedDate = payloadReportDate(payload, expectedPage, reportDate);
                    if (expectedPage !== String(App.currentPage || "overview")) return false;
                    if (expectedPage === "timeline") {
                        var currentDate = runtimeReportDateForPage("timeline", reportDate);
                        if (expectedDate && currentDate && expectedDate !== currentDate) return false;
                        if (expectedDate && expectedDate !== App.localTodayStr()) return true;
                    } else if (expectedDate && expectedDate !== App.localTodayStr()) {
                        return false;
                    }
                    var currentRuntime = App.liveRuntimeStore ? App.liveRuntimeStore.get() : null;
                    var currentClock = currentRuntime && currentRuntime.liveClock;
                    var incomingIdentity = runtimeIdentityFromPayload(payload);
                    var incomingClock = incomingIdentity.liveClock;
                    var envelope = payload.runtime || {};
                    var currentActivity = envelope.current_activity || payload.current_activity || {};
                    if (isActiveLiveTime(currentClock) && incomingClock && !sameLiveContinuity(currentClock, incomingClock)) return false;
                    if (isActiveLiveTime(currentClock) && !incomingClock
                        && (currentActivity.active === true || currentActivity.is_active === true)) return false;
                    if (currentRuntime && currentRuntime.currentActivityDisplaySpanId
                        && incomingIdentity.currentActivityDisplaySpanId
                        && currentRuntime.currentActivityDisplaySpanId !== incomingIdentity.currentActivityDisplaySpanId) return false;
                    if (currentRuntime && currentRuntime.currentResourceIdentityHash
                        && incomingIdentity.currentResourceIdentityHash
                        && currentRuntime.currentResourceIdentityHash !== incomingIdentity.currentResourceIdentityHash) return false;
                    return true;
                }
                App.isPagePayloadCompatibleWithRuntime = isPagePayloadCompatibleWithRuntime;
            '''
        ),
    )
    replace_between(
        path,
        "    function noteRejectedPagePayload(payload, page, reportDate) {",
        "    App.noteRejectedPagePayload = noteRejectedPagePayload;",
        textwrap.dedent(
            '''\
                function noteRejectedPagePayload(payload, page, reportDate) {
                    var envelope = payload && payload.runtime ? payload.runtime : (payload || {});
                    App.liveClockContractRefreshRequested = true;
                    App.liveClockContractViolation = {
                        spanId: envelope.display_span_id ? String(envelope.display_span_id) : "",
                        page: String(page || App.currentPage || "overview"),
                        reason: "page_payload_runtime_mismatch",
                        reportDate: reportDate || envelope.scope_report_date || payloadReportDate(payload, page, reportDate) || ""
                    };
                }
                App.noteRejectedPagePayload = noteRejectedPagePayload;
            '''
        ),
    )


def remove_recent_capability() -> None:
    replace_once("worktrace/webview_ui/bridge.py", '        "get_recent_activities",\n', "")
    replace_between(
        "worktrace/webview_ui/bridge_overview.py",
        "    def get_recent_activities(self) -> dict[str, Any]:",
        "    def get_refresh_state(self, report_date=None) -> dict[str, Any]:",
        "    def get_refresh_state(self, report_date=None) -> dict[str, Any]:",
    )


def camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def migrate_literal_bridge_calls() -> None:
    for path in sorted((ROOT / "worktrace/webview_ui/js").glob("*.js")):
        content = path.read_text(encoding="utf-8")
        content = re.sub(
            r'App\.callBridge\(\s*"([a-z0-9_]+)"\s*,\s*',
            lambda match: f"App.bridge.{camel(match.group(1))}(",
            content,
        )
        content = re.sub(
            r'App\.callBridge\(\s*"([a-z0-9_]+)"\s*\)',
            lambda match: f"App.bridge.{camel(match.group(1))}()",
            content,
        )
        path.write_text(content, encoding="utf-8", newline="\n")


def migrate_timeline() -> None:
    path = "worktrace/webview_ui/js/timeline.js"
    replace_between(
        path,
        "    function acceptTimelinePayload(data, date) {",
        "    App.acceptTimelinePayload = acceptTimelinePayload;",
        textwrap.dedent(
            '''\
                function acceptTimelinePayload(data, date) {
                    if (!data || !data.ok) return false;
                    if (String(App.currentPage || "overview") !== "timeline") {
                        App.noteRejectedPagePayload(data, "timeline", date);
                        return false;
                    }
                    var expectedDate = App.runtimeReportDateForPage("timeline", date);
                    var payloadDate = App.payloadReportDate(data, "timeline", date);
                    if (expectedDate && payloadDate && expectedDate !== payloadDate) {
                        App.noteRejectedPagePayload(data, "timeline", date);
                        return false;
                    }
                    if (!App.isPagePayloadCompatibleWithRuntime(data, "timeline", date)) {
                        App.noteRejectedPagePayload(data, "timeline", date);
                        return false;
                    }
                    return App.acceptLiveRuntimePayload(data, "timeline", date, {
                        source: "page_model"
                    });
                }
                App.acceptTimelinePayload = acceptTimelinePayload;
            '''
        ),
    )
    replace_once(
        path,
        'App.runTimelineSessionOperation("hide_timeline_session_activity", { summaryId: this.getAttribute("data-summary-id") });',
        'App.runTimelineSessionOperation("hideActivity", { summaryId: this.getAttribute("data-summary-id") });',
    )
    replace_between(
        path,
        "    function runTimelineSessionOperation(method, options) {",
        "    App.runTimelineSessionOperation = runTimelineSessionOperation;",
        textwrap.dedent(
            '''\
                var TIMELINE_OPERATIONS = Object.freeze({
                    hide: Object.freeze({ intent: "hide_timeline_session", invoke: App.bridge.hideTimelineSession }),
                    hideActivity: Object.freeze({ intent: "hide_timeline_session_activity", invoke: App.bridge.hideTimelineSessionActivity }),
                    merge: Object.freeze({ intent: "merge_timeline_session", invoke: App.bridge.mergeTimelineSession }),
                    split: Object.freeze({ intent: "split_timeline_session", invoke: App.bridge.splitTimelineSession }),
                    copy: Object.freeze({ intent: "copy_timeline_session", invoke: App.bridge.copyTimelineSession })
                });

                function runTimelineSessionOperation(operationKey, options) {
                    options = options || {};
                    var operation = TIMELINE_OPERATIONS[operationKey];
                    if (!operation) return Promise.reject(new Error("unsupported_timeline_operation"));
                    var method = operation.intent;
                    var key = App.selectedProjectionInstanceKey;
                    var date = currentTimelineReportDate();
                    var revision = App.selectedProjectionRevision || "";
                    if (!key || !date) return Promise.resolve();
                    var mergeTarget = operationKey === "merge" ? findMergeTarget(key, options.direction) : null;
                    if (operationKey === "merge" && !mergeTarget) {
                        showEditStatus("只能合并相邻时段。", true);
                        return Promise.resolve();
                    }
                    var argsSignature = JSON.stringify([
                        options || {},
                        mergeTarget ? mergeTarget.projection_instance_key || "" : "",
                        mergeTarget ? mergeTarget.projection_revision || "" : ""
                    ]);
                    var owner = App.timelineRequestState.nextMutationOwner(method, date, key, revision, argsSignature);
                    if (!owner) {
                        blockDifferentMutationIntent();
                        return Promise.resolve();
                    }
                    var args;
                    if (operationKey === "hideActivity") {
                        args = [date, key, options.summaryId || "", revision, owner.requestId];
                    } else if (operationKey === "merge") {
                        args = [
                            date,
                            key,
                            options.direction,
                            revision,
                            owner.requestId,
                            mergeTarget.projection_instance_key || "",
                            mergeTarget.projection_revision || ""
                        ];
                    } else {
                        args = [date, key, revision, owner.requestId];
                    }
                    owner.payload = args.slice();
                    return operation.invoke.apply(null, args).then(function (result) {
                        if (!App.timelineRequestState.isCurrentMutationOwner(owner)) return null;
                        var data = App.handleResult(result, function (message) {
                            showEditStatus(message || "操作失败，请刷新后重试。", true);
                        });
                        if (!data) {
                            App.timelineRequestState.releaseMutationOwner(owner, "confirmed_failure", result);
                            return null;
                        }
                        App.timelineRequestState.transitionMutation(owner, "confirmed_success", result);
                        consumeMutationResult(result);
                        App.timelineRequestState.releaseMutationOwner(owner, "confirmed_success", result);
                        showEditStatus("操作成功", false);
                        return refreshAfterConfirmedMutation().catch(function () {
                            showEditStatus("操作已保存，但刷新失败", true);
                        });
                    }).catch(function () {
                        if (!App.timelineRequestState.isCurrentMutationOwner(owner)) return null;
                        markMutationUnknown(owner);
                        return null;
                    });
                }
                App.runTimelineSessionOperation = runTimelineSessionOperation;
            '''
        ),
    )


def verify() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "worktrace/webview_ui/js").glob("*.js")):
        content = path.read_text(encoding="utf-8")
        if "App.callBridge" in content:
            offenders.append(str(path.relative_to(ROOT)))
    if offenders:
        raise AssertionError(f"dynamic bridge dispatch remains: {offenders}")
    init = read("worktrace/webview_ui/js/init.js")
    if "set: function (value)" in init:
        raise AssertionError("live runtime setter remains")
    if "get_recent_activities" in read("worktrace/webview_ui/bridge.py"):
        raise AssertionError("obsolete recent capability remains")


def main() -> None:
    overwrite_runtime_contract()
    migrate_runtime_store()
    migrate_core_runtime()
    remove_recent_capability()
    migrate_literal_bridge_calls()
    migrate_timeline()
    verify()


if __name__ == "__main__":
    main()
