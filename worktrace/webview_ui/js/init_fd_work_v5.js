// WorkTrace WebView frontend — initialization, fixed bridge client, and runtime store.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function invokeBridge(method, argsLike) {
        if (!window.pywebview || !window.pywebview.api) {
            return Promise.reject(new Error("bridge unavailable"));
        }
        var fn = window.pywebview.api[method];
        if (typeof fn !== "function") {
            return Promise.reject(new Error("bridge method unavailable"));
        }
        return fn.apply(window.pywebview.api, Array.prototype.slice.call(argsLike || []));
    }

    function fixedBridgeMethod(method) {
        return function () { return invokeBridge(method, arguments); };
    }

    App.bridge = Object.freeze({
        acceptFirstRunNotice: fixedBridgeMethod("accept_first_run_notice"),
        archiveProjectForRules: fixedBridgeMethod("archive_project_for_rules"),
        automaticRulesStatus: fixedBridgeMethod("automatic_rules_status"),
        backfillProjectRule: fixedBridgeMethod("backfill_project_rule"),
        backfillProjectRulesBatch: fixedBridgeMethod("backfill_project_rules_batch"),
        clearAllLocalData: fixedBridgeMethod("clear_all_local_data"),
        chooseProjectRuleFolder: fixedBridgeMethod("choose_project_rule_folder"),
        clearFDWorkBindingForRules: fixedBridgeMethod("clear_fd_work_binding_for_rules"),
        copyTimelineSession: fixedBridgeMethod("copy_timeline_session"),
        createExcludedFolderRule: fixedBridgeMethod("create_excluded_folder_rule"),
        createExcludedKeywordRule: fixedBridgeMethod("create_excluded_keyword_rule"),
        createProjectFolderRule: fixedBridgeMethod("create_project_folder_rule"),
        createProjectForRules: fixedBridgeMethod("create_project_for_rules"),
        createProjectKeywordRule: fixedBridgeMethod("create_project_keyword_rule"),
        deleteProjectFolderRule: fixedBridgeMethod("delete_project_folder_rule"),
        deleteProjectForRules: fixedBridgeMethod("delete_project_for_rules"),
        deleteProjectKeywordRule: fixedBridgeMethod("delete_project_keyword_rule"),
        exportEncryptedBackup: fixedBridgeMethod("export_encrypted_backup"),
        exportStatisticsCsv: fixedBridgeMethod("export_statistics_csv"),
        getFDWorkStatus: fixedBridgeMethod("get_fd_work_status"),
        getFirstRunNotice: fixedBridgeMethod("get_first_run_notice"),
        getOverview: fixedBridgeMethod("get_overview"),
        getProjectRules: fixedBridgeMethod("get_project_rules"),
        getRefreshState: fixedBridgeMethod("get_refresh_state"),
        getSettingsPrivacyStatus: fixedBridgeMethod("get_settings_privacy_status"),
        getStatisticsExportSummary: fixedBridgeMethod("get_statistics_export_summary"),
        getStatus: fixedBridgeMethod("get_status"),
        getTimeline: fixedBridgeMethod("get_timeline"),
        getTimelineSessionActivitySummary: fixedBridgeMethod("get_timeline_session_activity_summary"),
        hideTimelineSession: fixedBridgeMethod("hide_timeline_session"),
        hideTimelineSessionActivity: fixedBridgeMethod("hide_timeline_session_activity"),
        importEncryptedBackup: fixedBridgeMethod("import_encrypted_backup"),
        listProjectCatalog: fixedBridgeMethod("list_project_catalog"),
        mergeTimelineSession: fixedBridgeMethod("merge_timeline_session"),
        openFDWorkCasePicker: fixedBridgeMethod("open_fd_work_case_picker"),
        openFDWorkEntry: fixedBridgeMethod("open_fd_work_entry"),
        showFDWorkLogin: fixedBridgeMethod("show_fd_work_login"),
        previewEncryptedBackupManifest: fixedBridgeMethod("preview_encrypted_backup_manifest"),
        previewProjectRuleImpact: fixedBridgeMethod("preview_project_rule_impact"),
        previewProjectRulesBatchImpact: fixedBridgeMethod("preview_project_rules_batch_impact"),
        recoverDatabaseMaintenance: fixedBridgeMethod("recover_database_maintenance"),
        saveTimelineSessionEdit: fixedBridgeMethod("save_timeline_session_edit"),
        setClipboardCaptureEnabled: fixedBridgeMethod("set_clipboard_capture_enabled"),
        setFDWorkEnabled: fixedBridgeMethod("set_fd_work_enabled"),
        setLaunchAtLogin: fixedBridgeMethod("set_launch_at_login"),
        setExcludedRulesEnabled: fixedBridgeMethod("set_excluded_rules_enabled"),
        setProjectEnabledForRules: fixedBridgeMethod("set_project_enabled_for_rules"),
        setProjectRuleEnabled: fixedBridgeMethod("set_project_rule_enabled"),
        setProjectRulesBatchEnabled: fixedBridgeMethod("set_project_rules_batch_enabled"),
        splitTimelineSession: fixedBridgeMethod("split_timeline_session"),
        togglePause: fixedBridgeMethod("toggle_pause"),
        updateProjectFolderRule: fixedBridgeMethod("update_project_folder_rule"),
        updateProjectForRules: fixedBridgeMethod("update_project_for_rules"),
        updateProjectKeywordRule: fixedBridgeMethod("update_project_keyword_rule")
    });

    var runtimeState = null;
    var RUNTIME_FRESHNESS_LEASE_MS = 10000;
    var RUNTIME_SOURCE_FUTURE_SKEW_MS = 2000;
    var runtimeLeaseExpired = false;
    var runtimeRebasePending = false;
    var LIVE_PROJECTION_PAGES = Object.freeze(["overview", "timeline", "statistics"]);
    var AUTOMATIC_PAGE_REFRESH_DELAY_MS = 1500;
    var AUTOMATIC_PAGE_REFRESH_RETRY_MS = 5000;
    var automaticPageRefreshTimer = null;
    var automaticPageRefreshKey = "";
    var automaticPageRefreshDueAtEpochMs = 0;
    var PAGE_NAMES = App.pageLifecycle ? App.pageLifecycle.names : Object.freeze([]);
    var pageRefreshDirty = {};
    var pageRefreshEpoch = {};
    PAGE_NAMES.forEach(function (page) {
        pageRefreshDirty[page] = true;
        pageRefreshEpoch[page] = 0;
    });

    function nonNegativeInt(value, fallback) {
        return typeof value === "number" && Number.isInteger(value) && value >= 0
            ? value
            : (fallback || 0);
    }

    function objectValue(value) {
        return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    }

    function pageUsesLiveProjection(page) {
        return LIVE_PROJECTION_PAGES.indexOf(String(page || "")) >= 0;
    }

    function runtimeLiveEligible(runtime) {
        if (!runtime || typeof runtime !== "object") return false;
        var collector = runtime.collector;
        if (collector && typeof collector.live_eligible === "boolean") {
            return collector.live_eligible;
        }
        var clock = runtime.liveClock;
        return !!(clock && clock.is_live === true);
    }

    function expireRuntimeLease() {
        runtimeLeaseExpired = true;
        runtimeRebasePending = true;
        App.liveClockContractRefreshRequested = true;
        return false;
    }

    function runtimeFresh(runtime, nowMs) {
        if (!runtimeLiveEligible(runtime)) return true;
        var acceptedAt = nonNegativeInt(runtime && runtime.acceptedAtEpochMs, 0);
        var clock = runtime && runtime.liveClock;
        var sampledAt = nonNegativeInt(clock && clock.sampled_at_epoch_ms, 0);
        var now = nonNegativeInt(nowMs, Date.now());
        if (!acceptedAt || !sampledAt) return expireRuntimeLease();
        var receiptAge = now - acceptedAt;
        var sourceAge = now - sampledAt;
        if (receiptAge < 0 || receiptAge > RUNTIME_FRESHNESS_LEASE_MS) {
            return expireRuntimeLease();
        }
        if (sourceAge < -RUNTIME_SOURCE_FUTURE_SKEW_MS
            || sourceAge > RUNTIME_FRESHNESS_LEASE_MS) {
            return expireRuntimeLease();
        }
        return true;
    }

    function runtimeProjectionAllowed(runtime, nowMs) {
        if (!runtimeLiveEligible(runtime)) return false;
        if (!runtimeFresh(runtime, nowMs)) return false;
        return runtimeRebasePending !== true;
    }

    function reconcileRuntimeFreshness(previous, accepted, source, page) {
        if (!accepted) return;
        if (!runtimeLiveEligible(accepted)) {
            runtimeLeaseExpired = false;
            runtimeRebasePending = false;
            return;
        }
        if (!runtimeFresh(accepted, accepted.acceptedAtEpochMs)) {
            return;
        }
        if (source === "page_model") {
            runtimeLeaseExpired = false;
            runtimeRebasePending = false;
            return;
        }
        if (source !== "refresh_state" || !pageUsesLiveProjection(page)) return;
        var previousLive = runtimeLiveEligible(previous);
        if (runtimeLeaseExpired || runtimeRebasePending || (!!previous && !previousLive)) {
            runtimeLeaseExpired = false;
            runtimeRebasePending = true;
            App.liveClockContractRefreshRequested = true;
        }
    }

    function generationValue(generations, key) {
        var value = objectValue(generations)[key];
        return typeof value === "number" && Number.isInteger(value) && value >= 0
            ? value
            : 0;
    }

    function changedGenerationKeys(previous, next) {
        var keys = [
            "report_structure",
            "classification_catalog",
            "settings",
            "privacy_catalog"
        ];
        if (!previous) return [];
        return keys.filter(function (key) {
            return generationValue(previous, key) !== generationValue(next, key);
        });
    }

    function intersects(left, right) {
        return (left || []).some(function (value) {
            return (right || []).indexOf(value) >= 0;
        });
    }

    function markPageDirty(page) {
        if (!Object.prototype.hasOwnProperty.call(pageRefreshDirty, page)) return;
        pageRefreshDirty[page] = true;
        pageRefreshEpoch[page] = nonNegativeInt(pageRefreshEpoch[page], 0) + 1;
    }

    function markPagesDirtyForGenerationChanges(changedKeys) {
        PAGE_NAMES.forEach(function (page) {
            var policy = pageRefreshPolicy(page);
            if (intersects(changedKeys, policy.entryGenerations)) markPageDirty(page);
        });
    }

    function pageCapability(page) {
        return App.pageLifecycle ? App.pageLifecycle.capability(page) : null;
    }

    function pageRefreshPolicy(page) {
        var capability = pageCapability(page);
        return capability && capability.refreshPolicy ? capability.refreshPolicy : {};
    }

    function pageHasLoadedData(page) {
        var capability = pageCapability(page);
        return !!(
            capability
            && typeof capability.hasLoadedData === "function"
            && capability.hasLoadedData()
        );
    }

    function pageRefreshEvidence(page) {
        var capability = pageCapability(page);
        return capability && typeof capability.refreshEvidence === "function"
            ? capability.refreshEvidence()
            : null;
    }

    function pageReportDate(page) {
        var capability = pageCapability(page);
        return capability && typeof capability.reportDate === "function"
            ? capability.reportDate()
            : null;
    }

    function markPageFresh(page, expectedEpoch) {
        if (!Object.prototype.hasOwnProperty.call(pageRefreshDirty, page)) return false;
        if (expectedEpoch === undefined || expectedEpoch === null) {
            // Page-local helpers may confirm an already-fresh view, but only the
            // coordinator that captured the dirty epoch may clear a dirty page.
            if (pageRefreshDirty[page] !== false) return false;
        } else if (nonNegativeInt(pageRefreshEpoch[page], 0) !== expectedEpoch) {
            return false;
        }
        pageRefreshDirty[page] = false;
        return true;
    }
    App.markPageFresh = markPageFresh;

    function pageNeedsRefresh(page) {
        return !pageHasLoadedData(page) || pageRefreshDirty[page] !== false;
    }
    App.pageNeedsRefresh = pageNeedsRefresh;

    function automaticRefreshAllowedForPage(page) {
        var capability = pageCapability(page);
        if (!capability || typeof capability.automaticRefreshAllowed !== "function") {
            return true;
        }
        return capability.automaticRefreshAllowed(App.localTodayStr());
    }

    function automaticRefreshScopeKey(page) {
        var capability = pageCapability(page);
        if (capability && typeof capability.refreshScopeKey === "function") {
            return String(capability.refreshScopeKey() || (page + "|"));
        }
        return page + "|";
    }

    function clearScheduledAutomaticPageRefresh() {
        if (automaticPageRefreshTimer !== null) {
            window.clearTimeout(automaticPageRefreshTimer);
        }
        automaticPageRefreshTimer = null;
        automaticPageRefreshKey = "";
        automaticPageRefreshDueAtEpochMs = 0;
    }
    App.clearScheduledAutomaticPageRefresh = clearScheduledAutomaticPageRefresh;

    function scheduleAutomaticPageRefresh(delayMs) {
        var page = App.currentPage || "overview";
        var scopeKey = automaticRefreshScopeKey(page);
        var delay = nonNegativeInt(delayMs, AUTOMATIC_PAGE_REFRESH_DELAY_MS);
        if (delay <= 0) delay = AUTOMATIC_PAGE_REFRESH_DELAY_MS;
        var requestedDueAtEpochMs = Date.now() + delay;
        if (automaticPageRefreshTimer !== null
            && automaticPageRefreshKey === scopeKey
            && automaticPageRefreshDueAtEpochMs > 0
            && automaticPageRefreshDueAtEpochMs <= requestedDueAtEpochMs) {
            return;
        }
        clearScheduledAutomaticPageRefresh();
        automaticPageRefreshKey = scopeKey;
        automaticPageRefreshDueAtEpochMs = requestedDueAtEpochMs;
        automaticPageRefreshTimer = window.setTimeout(function () {
            automaticPageRefreshTimer = null;
            automaticPageRefreshKey = "";
            automaticPageRefreshDueAtEpochMs = 0;
            if (App.currentPage !== page || automaticRefreshScopeKey(page) !== scopeKey) return;
            if (!pageNeedsRefresh(page) || !automaticRefreshAllowedForPage(page)) return;
            refreshCurrentPageData(null, pageRefreshOptions(page, { automatic: true }));
        }, delay);
    }

    function pageRefreshOptions(page, options) {
        var result = Object.assign({}, options || {});
        var policy = pageRefreshPolicy(page);
        if (policy.preservePresentation === true
            && (result.automatic === true || result.navigation === true)) {
            result.preservePresentation = true;
        }
        return result;
    }

    function pageRuntimeRefreshChanged(page, previous, accepted) {
        var capability = pageCapability(page);
        if (!capability || typeof capability.runtimeRefreshIdentity !== "function") return false;
        return !!previous
            && capability.runtimeRefreshIdentity(previous)
                !== capability.runtimeRefreshIdentity(accepted);
    }

    function dispatchAutomaticRefresh(changedKeys, previous, accepted) {
        var page = App.currentPage || "overview";
        var policy = pageRefreshPolicy(page);
        var semanticChange = intersects(changedKeys, policy.automaticGenerations);
        if (pageRuntimeRefreshChanged(page, previous, accepted)) semanticChange = true;
        if (!semanticChange || !automaticRefreshAllowedForPage(page)) return;
        if (policy.deferred) {
            scheduleAutomaticPageRefresh();
            return;
        }
        clearScheduledAutomaticPageRefresh();
        refreshCurrentPageData(null, pageRefreshOptions(page, { automatic: true }));
    }

    function frozenRuntime(value) {
        if (!value || typeof value !== "object") return null;
        var copy = Object.assign({}, value);
        [
            "liveClock", "currentActivity", "currentProject",
            "collector", "workers", "generations", "revisions"
        ].forEach(function (field) {
            if (copy[field] && typeof copy[field] === "object") {
                copy[field] = Object.freeze(Object.assign({}, copy[field]));
            }
        });
        if (Array.isArray(copy.errorCodes)) copy.errorCodes = Object.freeze(copy.errorCodes.slice());
        return Object.freeze(copy);
    }

    function rawRuntimeEnvelope(value) {
        if (!value || typeof value !== "object") return null;
        if (!value.runtime || typeof value.runtime !== "object") return null;
        return value.runtime;
    }

    function normalizeRuntimeEnvelope(value, page, reportDate) {
        var envelope = rawRuntimeEnvelope(value);
        if (!envelope || Number(envelope.schema_version) !== 2) return null;
        var surface = String(envelope.surface || page || App.currentPage || "overview");
        var runtimePage = String(page || App.currentPage || surface || "overview");
        var scopeDate = String(envelope.scope_report_date || reportDate || "");
        var liveDate = String(envelope.live_report_date || scopeDate || "");
        var snapshot = objectValue(envelope.snapshot);
        var revisions = objectValue(envelope.revisions);
        var collector = objectValue(envelope.collector);
        var sourceClock = envelope.clock;
        var liveClock = App.validateLiveClock(sourceClock);
        var malformed = !liveClock;
        if (malformed) {
            App.recordLiveClockContractViolation(
                sourceClock && typeof sourceClock.display_span_id === "string"
                    ? sourceClock.display_span_id
                    : "",
                surface,
                "runtime_clock_invalid",
                envelope.schema_version
            );
        }
        return {
            schemaVersion: 2,
            surface: surface,
            page: runtimePage,
            reportDate: scopeDate,
            liveReportDate: liveDate,
            acceptedAtEpochMs: Date.now(),
            liveClock: liveClock,
            displaySpanId: liveClock ? liveClock.display_span_id : "",
            stableLiveKeyHash: liveClock ? liveClock.stable_live_key_hash : "",
            liveRevision: String(snapshot.revision || ""),
            structureRevision: String(revisions.structure || ""),
            pageRevision: String(revisions.page || ""),
            sampleId: String(snapshot.id || ""),
            currentActivity: objectValue(envelope.current_activity),
            currentProject: envelope.current_project && typeof envelope.current_project === "object"
                ? envelope.current_project
                : null,
            collector: collector,
            runtimePhase: String(envelope.runtime_phase || "unavailable"),
            workers: objectValue(envelope.workers),
            generations: objectValue(envelope.generations),
            databaseReplacementEpoch: nonNegativeInt(envelope.database_replacement_epoch, 0),
            errorCodes: Array.isArray(envelope.error_codes) ? envelope.error_codes : [],
            revisions: revisions,
            runtimeConsistent: envelope.runtime_consistent === true,
            needsFullRefresh: malformed || envelope.needs_full_refresh === true
        };
    }

    function runtimeVisualContinuityKey(runtime) {
        if (!runtime) return "";
        return [
            runtime.page || "",
            runtime.displaySpanId || "",
            runtime.stableLiveKeyHash || ""
        ].join("|");
    }
    App.runtimeVisualContinuityKey = runtimeVisualContinuityKey;

    var liveRuntimeStore = Object.freeze({
        get: function () { return runtimeState; },
        acceptEnvelope: function (value, page, reportDate) {
            var next = normalizeRuntimeEnvelope(value, page, reportDate);
            if (!next) return null;
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

    function liveClockProjectionAllowed(clock, nowMs) {
        var acceptedClock = App.validateLiveClock(clock);
        if (!acceptedClock || acceptedClock.is_live !== true) return true;
        var page = App.currentPage || "overview";
        if (!pageUsesLiveProjection(page)) return false;
        var runtime = liveRuntimeStore.get();
        if (!runtime || runtime.page !== page) return false;
        if (!runtimeProjectionAllowed(runtime, nowMs)) return false;
        var runtimeClock = App.validateLiveClock(runtime.liveClock);
        if (!runtimeClock || runtimeClock.is_live !== true) return false;
        return acceptedClock.display_span_id === runtimeClock.display_span_id
            && acceptedClock.stable_live_key_hash === runtimeClock.stable_live_key_hash;
    }
    App.liveClockProjectionAllowed = liveClockProjectionAllowed;

    var computeClockDurationRaw = App.computeClockDurationNow;
    if (typeof computeClockDurationRaw === "function") {
        App.computeClockDurationNow = function (clock, nowMs) {
            var acceptedClock = App.validateLiveClock(clock);
            if (acceptedClock && acceptedClock.is_live === true
                && !liveClockProjectionAllowed(acceptedClock, nowMs)) {
                return null;
            }
            return computeClockDurationRaw(clock, nowMs);
        };
    }

    function resetClientGeneration(reason) {
        if (App.requestCoordinator) App.requestCoordinator.bumpDataEpoch();
        if (App.pageLifecycle) App.pageLifecycle.resetGeneration();
        if (App.fdWork && App.fdWork.resetGeneration) App.fdWork.resetGeneration();
        App.lastRefreshState = null;
        App.activePageRefreshInFlight = false;
        App.activePageRefreshPromise = null;
        App.activePageRefreshPending = null;
        App.liveClockContractRefreshRequested = false;
        App.liveClockContractViolation = null;
        App.liveClockViolationKeys = {};
        runtimeLeaseExpired = false;
        runtimeRebasePending = false;
        clearScheduledAutomaticPageRefresh();
        Object.keys(pageRefreshDirty).forEach(function (page) {
            markPageDirty(page);
        });
        liveRuntimeStore.reset();
        App._monotonicRenderState = {};
        App.lastClientGenerationResetReason = String(reason || "data_generation_changed");
    }
    App.resetClientGeneration = resetClientGeneration;

    function payloadReportDate(payload, page, fallbackDate) {
        var envelope = rawRuntimeEnvelope(payload);
        if (envelope && envelope.scope_report_date) return String(envelope.scope_report_date);
        return App.runtimeReportDateForPage(page, fallbackDate);
    }
    App.payloadReportDate = payloadReportDate;

    function incomingRuntimeCompatible(payload, page, reportDate) {
        var envelope = rawRuntimeEnvelope(payload);
        if (!payload || payload.ok !== true || !envelope || Number(envelope.schema_version) !== 2) {
            return false;
        }
        var expectedPage = String(page || App.currentPage || "overview");
        var expectedDate = payloadReportDate(payload, expectedPage, reportDate);
        if (expectedPage !== String(App.currentPage || "overview")) return false;
        var currentDate = pageReportDate(expectedPage) || App.localTodayStr();
        if (expectedDate && currentDate && expectedDate !== currentDate) return false;
        return true;
    }
    App.isPagePayloadCompatibleWithRuntime = incomingRuntimeCompatible;

    function noteRejectedPagePayload(payload, page, reportDate) {
        var envelope = rawRuntimeEnvelope(payload) || {};
        var clock = envelope.clock && typeof envelope.clock === "object" ? envelope.clock : {};
        App.recordLiveClockContractViolation(
            typeof clock.display_span_id === "string" ? clock.display_span_id : "",
            String(page || App.currentPage || "overview"),
            "page_payload_runtime_v2_mismatch",
            envelope.schema_version || 2
        );
        App.liveClockContractViolation.reportDate = reportDate || envelope.scope_report_date || "";
    }
    App.noteRejectedPagePayload = noteRejectedPagePayload;

    function acceptLiveRuntimePayload(payload, page, reportDate, options) {
        if (!payload || payload.ok !== true) return false;
        options = options || {};
        var envelope = rawRuntimeEnvelope(payload);
        if (!envelope || Number(envelope.schema_version) !== 2) return false;
        var previous = liveRuntimeStore.get();
        var incomingEpoch = nonNegativeInt(envelope.database_replacement_epoch, 0);
        if (previous && incomingEpoch !== previous.databaseReplacementEpoch) {
            resetClientGeneration("database_replacement_epoch_changed");
            previous = null;
        }
        var previousKey = runtimeVisualContinuityKey(previous);
        var accepted = liveRuntimeStore.acceptEnvelope(
            payload,
            String(page || App.currentPage || "overview"),
            payloadReportDate(payload, page, reportDate)
        );
        if (!accepted) return false;
        App.liveDisplayModel = null;
        if (previousKey && previousKey !== runtimeVisualContinuityKey(accepted)) {
            App._monotonicRenderState = {};
        }
        reconcileRuntimeFreshness(
            previous,
            accepted,
            String(options.source || ""),
            String(page || App.currentPage || "overview")
        );
        if (accepted.needsFullRefresh) App.liveClockContractRefreshRequested = true;
        if (options.source === "refresh_state") App.lastRefreshState = payload;
        return true;
    }
    App.acceptLiveRuntimePayload = acceptLiveRuntimePayload;

    App.acceptRefreshStateRuntime = function (state) {
        if (!state || state.ok !== true) return false;
        return acceptLiveRuntimePayload(
            state,
            App.currentPage || "overview",
            payloadReportDate(state, App.currentPage || "overview"),
            { source: "refresh_state" }
        );
    };

    App.acceptPagePayloadRuntime = function (payload, page, reportDate) {
        if (!incomingRuntimeCompatible(payload, page, reportDate)) {
            noteRejectedPagePayload(payload, page, reportDate);
            return false;
        }
        return acceptLiveRuntimePayload(payload, page, reportDate, { source: "page_model" });
    };

    App.getActiveLiveClock = function () {
        var runtime = liveRuntimeStore.get();
        if (!runtime || runtime.page !== (App.currentPage || "overview")) return null;
        if (runtime.liveClock && runtime.liveClock.is_live === true
            && pageUsesLiveProjection(App.currentPage || "overview")
            && !runtimeProjectionAllowed(runtime, Date.now())) {
            return null;
        }
        return runtime.liveClock || null;
    };

    function handlePageLocalTickResult(page, result) {
        if (!result || result.refreshRequired !== true) return;
        if (App.currentPage !== page) return;
        if (!pageNeedsRefresh(page)) markPageDirty(page);
        if (!automaticRefreshAllowedForPage(page)) return;
        scheduleAutomaticPageRefresh();
    }

    App.applyLocalTicker = function () {
        var runtime = liveRuntimeStore.get();
        var tickerPage = App.currentPage || "overview";
        var projectionAllowed = !pageUsesLiveProjection(tickerPage)
            || runtimeProjectionAllowed(runtime, Date.now());
        var pageRoot = document.getElementById("page-" + tickerPage);
        var liveTargets = pageRoot
            ? pageRoot.querySelectorAll('[data-live-clock-target="1"]')
            : [];
        if (projectionAllowed) {
            for (var i = 0; i < liveTargets.length; i++) {
                var target = liveTargets[i];
                var clock = App.readLiveClockTarget(target);
                if (!clock) {
                    App.recordLiveClockContractViolation("", tickerPage, "target_clock_invalid", 2);
                    App.clearLiveClockTarget(target);
                    continue;
                }
                if (!App.liveTargetCompatibleWithRuntime(target, runtime)) {
                    App.recordLiveClockContractViolation(
                        clock.display_span_id,
                        tickerPage,
                        "live_target_runtime_mismatch",
                        2
                    );
                    App.clearLiveClockTarget(target);
                    continue;
                }
                App.renderLiveDurationTarget(target, clock, Date.now());
            }
        }
        var capability = pageCapability(tickerPage);
        if (capability && typeof capability.applyLocalTick === "function") {
            if (tickerPage === "statistics" && !projectionAllowed) return;
            var pageTick = capability.applyLocalTick();
            if (pageTick && typeof pageTick.then === "function") {
                pageTick.then(function (result) {
                    handlePageLocalTickResult(tickerPage, result);
                }).catch(function () {});
            } else {
                handlePageLocalTickResult(tickerPage, pageTick);
            }
        }
    };

    function refreshStatus() {
        var token = App.requestCoordinator.beginLatest("status", "current");
        return App.bridge.getStatus().then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return;
            var status = App.handleResult(result, function (msg) { throw new Error(msg); });
            App.showStatus(status);
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token)) App.showError("刷新失败");
        });
    }

    function refreshStatusFromRuntime(runtime) {
        if (!runtime || !runtime.collector) return refreshStatus();
        App.showStatus({
            ok: true,
            status: String(runtime.collector.status || ""),
            paused: runtime.collector.paused === true,
            display: String(runtime.collector.display || "")
        });
        return Promise.resolve();
    }

    function refreshActivePage(acceptedState, options, expectedPage) {
        var page = String(expectedPage || App.currentPage || "overview");
        if (App.currentPage !== page) return Promise.resolve(null);
        var capability = pageCapability(page);
        if (!capability) return Promise.resolve(null);
        options = pageRefreshOptions(page, options);
        var method = options.navigation === true && typeof capability.onPageEntered === "function"
            ? capability.onPageEntered
            : capability.onRefreshRequested;
        if (typeof method !== "function") return Promise.resolve(null);
        var refreshEpoch = nonNegativeInt(pageRefreshEpoch[page], 0);
        var beforeEvidence = pageRefreshEvidence(page);
        return Promise.resolve(method.call(capability, options, {
            acceptedState: acceptedState || null,
            runtime: liveRuntimeStore.get()
        })).then(function (result) {
            var accepted = App.currentPage === page
                && pageHasLoadedData(page)
                && pageRefreshEvidence(page) !== beforeEvidence;
            if (accepted) markPageFresh(page, refreshEpoch);
            return result;
        });
    }
    App.refreshActivePage = refreshActivePage;

    function _runCurrentPageRefresh(state, options) {
        options = options || {};
        var refreshPage = App.currentPage || "overview";
        var refreshScopeKey = automaticRefreshScopeKey(refreshPage);
        App.activePageRefreshInFlight = true;
        var statePromise = state && state.ok === true
            ? Promise.resolve(state)
            : App.bridge.getRefreshState(pageReportDate(refreshPage)).then(function (result) {
                return App.handleResult(result, function () { return null; });
            });
        return statePromise.then(function (acceptedState) {
            if (App.currentPage !== refreshPage
                || automaticRefreshScopeKey(refreshPage) !== refreshScopeKey) {
                return [];
            }
            if (acceptedState && acceptedState.ok === true) App.acceptRefreshStateRuntime(acceptedState);
            var promises = [
                acceptedState && acceptedState.ok === true
                    ? refreshStatusFromRuntime(liveRuntimeStore.get())
                    : refreshStatus(),
                refreshActivePage(acceptedState, options, refreshPage)
            ];
            return Promise.allSettled(promises);
        }).then(function (results) {
            results = Array.isArray(results) ? results : [];
            App.lastFullRefreshAtEpochMs = Date.now();
            var anyError = results.some(function (item) { return item.status === "rejected"; });
            if (!anyError) App.clearError();
            if (options.automatic === true
                && App.currentPage === refreshPage
                && automaticRefreshScopeKey(refreshPage) === refreshScopeKey
                && pageNeedsRefresh(refreshPage)
                && automaticRefreshAllowedForPage(refreshPage)) {
                scheduleAutomaticPageRefresh(AUTOMATIC_PAGE_REFRESH_RETRY_MS);
            }
            return results;
        });
    }

    function refreshCurrentPageData(state, options) {
        if (App.activePageRefreshInFlight) {
            App.activePageRefreshPending = { state: state, options: options };
            return App.activePageRefreshPromise || Promise.resolve();
        }
        App.activePageRefreshPromise = _runCurrentPageRefresh(state, options).finally(function () {
            App.activePageRefreshInFlight = false;
            var pending = App.activePageRefreshPending;
            App.activePageRefreshPending = null;
            App.activePageRefreshPromise = null;
            if (pending) return refreshCurrentPageData(pending.state, pending.options);
        });
        return App.activePageRefreshPromise;
    }
    App.refreshCurrentPageData = refreshCurrentPageData;
    App.refreshAll = function () { return refreshCurrentPageData(); };

    function togglePause() {
        App.bridge.togglePause().then(function (result) {
            if (!result || result.ok === false) {
                App.showGlobalAlert(App.extractBridgeError(result, "切换暂停状态失败，请稍后重试。"));
                return;
            }
            App.clearGlobalAlert();
            App.showStatus(result);
        }).catch(function () {
            App.showGlobalAlert("切换暂停状态失败，请稍后重试。");
        });
    }
    App.togglePause = togglePause;

    function resetPageTransientUi(pageId) {
        if (App.pageLifecycle) {
            App.pageLifecycle.onPageLeft(pageId, { restoreFocus: false });
        }
    }
    App.resetPageTransientUi = resetPageTransientUi;

    function switchPage(pageId) {
        var previousPage = App.currentPage;
        clearScheduledAutomaticPageRefresh();
        if (previousPage && previousPage !== pageId) resetPageTransientUi(previousPage);
        var navItems = document.querySelectorAll(".nav-item");
        var pages = document.querySelectorAll(".page");
        for (var i = 0; i < navItems.length; i++) {
            navItems[i].classList.remove("active");
            navItems[i].removeAttribute("aria-current");
        }
        for (var j = 0; j < pages.length; j++) pages[j].classList.remove("active");
        var navTarget = document.querySelector('.nav-item[data-page="' + pageId + '"]');
        var pageTarget = document.getElementById("page-" + pageId);
        if (navTarget) {
            navTarget.classList.add("active");
            navTarget.setAttribute("aria-current", "page");
        }
        if (pageTarget) pageTarget.classList.add("active");
        App.currentPage = pageId;
        liveRuntimeStore.setScope(
            pageId,
            pageReportDate(pageId)
        );
        refreshCurrentActivityFromState(App.lastRefreshState, { forceRender: true });
        if (!pageNeedsRefresh(pageId)) return;
        refreshActivePage(
            App.lastRefreshState,
            pageRefreshOptions(pageId, { navigation: true }),
            pageId
        ).catch(function () {
            App.showError("刷新失败");
        });
    }
    App.switchPage = switchPage;

    function initNav() {
        var navItems = document.querySelectorAll(".nav-item");
        for (var i = 0; i < navItems.length; i++) {
            navItems[i].addEventListener("click", function () {
                switchPage(this.getAttribute("data-page"));
            });
        }
    }
    App.initNav = initNav;

    function bind(id, event, handler) {
        var element = document.getElementById(id);
        if (element) element.addEventListener(event, handler);
    }

    function initButtons() {
        bind("toggle-pause-btn", "click", togglePause);
        bind("refresh-btn", "click", App.refreshAll);
        if (App.pageLifecycle) App.pageLifecycle.bindEvents();
        App.privacyNotice.bindEvents();
        bind("first-run-notice-accept-btn", "click", function () {
            return App.privacyNotice.acceptGate().then(function (ready) {
                return ready ? continueStartupAfterPrivacyGate() : false;
            });
        });
        bind("first-run-notice-retry-btn", "click", function () {
            return App.privacyNotice.retryGate().then(function (ready) {
                return ready ? continueStartupAfterPrivacyGate() : false;
            });
        });
    }
    App.initButtons = initButtons;

    function updateCurrentActivityFromRuntime(runtime, options) {
        if (!runtime) return;
        var capability = pageCapability(App.currentPage || "overview");
        if (capability && typeof capability.updateCurrentActivity === "function") {
            capability.updateCurrentActivity(runtime.currentActivity || {}, options || {});
        }
    }

    function currentActivityRenderIdentity(runtime) {
        runtime = runtime || {};
        var current = runtime.currentActivity || {};
        var clock = App.validateLiveClock(runtime.liveClock);
        return [
            current.active === true ? "active" : "inactive",
            clock ? clock.duration_semantic : "static",
            clock ? clock.display_span_id : "",
            clock ? clock.stable_live_key_hash : "",
            String(current.persisted_activity_id || current.activity_id || "")
        ].join("|");
    }

    function refreshCurrentActivityFromState(state, options) {
        if (!state || state.ok !== true) return;
        var runtime = liveRuntimeStore.get();
        if (!runtime) return;
        options = options || {};
        updateCurrentActivityFromRuntime(runtime, { render: options.forceRender === true });
    }
    App.refreshCurrentActivityFromState = refreshCurrentActivityFromState;
    function runRevisionCheck() {
        if (App.refreshCheckInFlight) {
            return App.activePageRefreshPromise || Promise.resolve();
        }
        App.refreshCheckInFlight = true;
        var reportDate = pageReportDate(App.currentPage);
        var token = App.requestCoordinator.beginLatest(
            "heartbeat",
            App.currentPage + "|" + (reportDate || "")
        );
        return App.bridge.getRefreshState(reportDate).then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return;
            var state = App.handleResult(result, function () { return null; });
            if (!state) return;
            var previousRuntime = liveRuntimeStore.get();
            var envelope = rawRuntimeEnvelope(state);
            if (!envelope || Number(envelope.schema_version) !== 2) return;
            var previousIdentity = currentActivityRenderIdentity(previousRuntime);
            var changedGenerations = changedGenerationKeys(
                previousRuntime ? previousRuntime.generations : null,
                objectValue(envelope.generations)
            );
            if (!App.acceptRefreshStateRuntime(state)) return;
            var acceptedRuntime = liveRuntimeStore.get();
            var renderCurrent = !previousRuntime
                || previousRuntime.liveRevision !== acceptedRuntime.liveRevision
                || previousIdentity !== currentActivityRenderIdentity(acceptedRuntime)
                || App.liveClockContractRefreshRequested;
            markPagesDirtyForGenerationChanges(changedGenerations);
            refreshCurrentActivityFromState(state, { forceRender: renderCurrent });
            refreshStatusFromRuntime(acceptedRuntime);
            if (App.liveClockContractRefreshRequested) {
                App.liveClockContractRefreshRequested = false;
                clearScheduledAutomaticPageRefresh();
                markPageDirty(App.currentPage);
                refreshCurrentPageData(state, { automatic: true });
                return;
            }
            dispatchAutomaticRefresh(changedGenerations, previousRuntime, acceptedRuntime);
        }).finally(function () {
            if (App.requestCoordinator.isCurrent(token)) App.refreshCheckInFlight = false;
        });
    }
    App.runRevisionCheck = runRevisionCheck;

    function startHeartbeat() {
        // Idempotent: the single startup entry (continueStartupAfterPrivacyGate)
        // is the only path that creates the heartbeat interval. Repeated calls
        // are no-ops so concurrent or duplicate startup requests never spawn a
        // second timer. Use restartHeartbeat() for an explicit teardown+rebuild.
        if (App.shellVisible === false || App.heartbeatTimer !== null) return;
        App.heartbeatTimer = setInterval(function () {
            try { App.applyLocalTicker(); } catch (error) {}
            try {
                Promise.resolve(runRevisionCheck()).catch(function () {});
            } catch (error) {}
        }, App.HEARTBEAT_INTERVAL_MS);
    }
    App.startHeartbeat = startHeartbeat;

    function stopHeartbeat() {
        if (App.heartbeatTimer !== null) clearInterval(App.heartbeatTimer);
        App.heartbeatTimer = null;
        clearScheduledAutomaticPageRefresh();
    }
    App.stopHeartbeat = stopHeartbeat;

    App.shellVisible = true;
    function setShellVisibility(visible) {
        visible = visible === true;
        if (App.shellVisible === visible) {
            if (visible && App.heartbeatTimer === null) startHeartbeat();
            return Promise.resolve();
        }
        App.shellVisible = visible;
        if (!visible) {
            stopHeartbeat();
            return Promise.resolve();
        }
        var revisionPromise;
        try {
            revisionPromise = typeof App.runRevisionCheck === "function"
                ? App.runRevisionCheck()
                : null;
        } catch (error) {
            revisionPromise = Promise.reject(error);
        }
        return Promise.resolve(revisionPromise)
            .catch(function () {})
            .then(function () {
                if (App.shellVisible === true) startHeartbeat();
            });
    }
    App.setShellVisibility = setShellVisibility;

    App.restartHeartbeat = function () {
        stopHeartbeat();
        startHeartbeat();
    };

    // Single idempotent post-privacy-gate startup entry: only this function
    // may run refresh state -> active-page refresh -> heartbeat.
    App.startupAfterPrivacyState = "idle";
    App.startupAfterPrivacyPromise = null;

    function showPublicStartupError(error) {
        var message = "应用启动失败，请稍后重试或重启应用。";
        if (error && typeof error.message === "string" && error.message.trim()) {
            message = error.message;
        } else if (typeof error === "string" && error.trim()) {
            message = error;
        }
        if (App.showGlobalAlert) App.showGlobalAlert(message);
    }
    App.showPublicStartupError = showPublicStartupError;

    function continueStartupAfterPrivacyGate() {
        if (App.startupAfterPrivacyState === "ready") {
            return Promise.resolve(true);
        }
        if (App.startupAfterPrivacyPromise) {
            return App.startupAfterPrivacyPromise;
        }

        App.startupAfterPrivacyState = "starting";

        Promise.resolve(App.bridge.getFDWorkStatus())
            .then(function (result) {
                if (result && result.ok === true && App.receiveFDWorkStatus) {
                    App.receiveFDWorkStatus(result.status);
                }
            })
            .catch(function () {});

        App.startupAfterPrivacyPromise = Promise.resolve()
            .then(function () {
                return App.bridge.getRefreshState(pageReportDate(App.currentPage));
            })
            .then(function (result) {
                var state = App.handleResult(result, function () { return null; });
                if (state) App.acceptRefreshStateRuntime(state);
                return refreshCurrentPageData(state);
            })
            .then(function () {
                startHeartbeat();
            })
            .then(function () {
                App.startupAfterPrivacyState = "ready";
                return true;
            })
            .catch(function (error) {
                App.startupAfterPrivacyState = "failed";
                showPublicStartupError(error);
                return false;
            })
            .then(function (result) {
                App.startupAfterPrivacyPromise = null;
                return result;
            });

        return App.startupAfterPrivacyPromise;
    }
    App.continueStartupAfterPrivacyGate = continueStartupAfterPrivacyGate;

    function init() {
        initNav();
        initButtons();
        App.privacyNotice.loadGate().then(function (ready) {
            return ready ? continueStartupAfterPrivacyGate() : null;
        });
    }
    App.init = init;

    var initStarted = false;
    function isBridgeReady() { return !!(window.pywebview && window.pywebview.api); }
    function bootstrap() {
        if (initStarted) return;
        initStarted = true;
        init();
    }
    function onBridgeReady() {
        window.removeEventListener("pywebviewready", onBridgeReady);
        bootstrap();
    }
    function onDomReady() {
        if (isBridgeReady()) bootstrap();
        else window.addEventListener("pywebviewready", onBridgeReady);
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", onDomReady);
    else onDomReady();
})();
