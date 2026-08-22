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
    var AUTOMATIC_PAGE_REFRESH_DELAY_MS = 1500;
    var AUTOMATIC_PAGE_REFRESH_RETRY_MS = 5000;
    var automaticPageRefreshTimer = null;
    var automaticPageRefreshKey = "";
    var PAGE_REFRESH_POLICIES = Object.freeze({
        overview: Object.freeze({
            entryGenerations: Object.freeze(["report_structure"]),
            automaticGenerations: Object.freeze(["report_structure"]),
            deferred: true
        }),
        timeline: Object.freeze({
            entryGenerations: Object.freeze(["report_structure"]),
            automaticGenerations: Object.freeze(["report_structure"]),
            deferred: true
        }),
        statistics: Object.freeze({
            entryGenerations: Object.freeze(["report_structure"]),
            automaticGenerations: Object.freeze(["report_structure"]),
            deferred: true
        }),
        rules: Object.freeze({
            // Activity changes affect last-used ordering, so remember the page is
            // stale for the next entry. Do not rebuild Rules while the user is
            // merely switching external apps.
            entryGenerations: Object.freeze([
                "classification_catalog", "privacy_catalog", "report_structure"
            ]),
            automaticGenerations: Object.freeze([
                "classification_catalog", "privacy_catalog"
            ]),
            deferred: false
        }),
        settings: Object.freeze({
            entryGenerations: Object.freeze(["settings", "privacy_catalog"]),
            automaticGenerations: Object.freeze(["settings", "privacy_catalog"]),
            deferred: false
        })
    });
    var pageRefreshDirty = {
        overview: true,
        timeline: true,
        statistics: true,
        rules: true,
        settings: true
    };
    var pageRefreshEpoch = {
        overview: 0,
        timeline: 0,
        statistics: 0,
        rules: 0,
        settings: 0
    };

    function nonNegativeInt(value, fallback) {
        return typeof value === "number" && Number.isInteger(value) && value >= 0
            ? value
            : (fallback || 0);
    }

    function objectValue(value) {
        return value && typeof value === "object" && !Array.isArray(value) ? value : {};
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
        Object.keys(PAGE_REFRESH_POLICIES).forEach(function (page) {
            var policy = PAGE_REFRESH_POLICIES[page];
            if (intersects(changedKeys, policy.entryGenerations)) markPageDirty(page);
        });
    }

    function pageCapability(page) {
        var capability = App[page];
        return capability && typeof capability === "object" ? capability : null;
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

    function pageIsLoading(page) {
        var capability = pageCapability(page);
        return !!(
            capability
            && typeof capability.isLoading === "function"
            && capability.isLoading()
        );
    }

    function pageIsEditing(page) {
        var capability = pageCapability(page);
        return !!(
            capability
            && typeof capability.isEditing === "function"
            && capability.isEditing()
        );
    }

    function updatePageCurrentActivity(page, activity) {
        var capability = pageCapability(page);
        if (capability && typeof capability.updateCurrentActivity === "function") {
            capability.updateCurrentActivity(activity || {});
        }
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
    }
    App.clearScheduledAutomaticPageRefresh = clearScheduledAutomaticPageRefresh;

    function scheduleAutomaticPageRefresh(delayMs) {
        var page = App.currentPage || "overview";
        var scopeKey = automaticRefreshScopeKey(page);
        var delay = nonNegativeInt(delayMs, AUTOMATIC_PAGE_REFRESH_DELAY_MS);
        if (delay <= 0) delay = AUTOMATIC_PAGE_REFRESH_DELAY_MS;
        clearScheduledAutomaticPageRefresh();
        automaticPageRefreshKey = scopeKey;
        automaticPageRefreshTimer = window.setTimeout(function () {
            automaticPageRefreshTimer = null;
            automaticPageRefreshKey = "";
            if (App.currentPage !== page || automaticRefreshScopeKey(page) !== scopeKey) return;
            if (!pageNeedsRefresh(page) || !automaticRefreshAllowedForPage(page)) return;
            refreshCurrentPageData(null, {
                automatic: true,
                preservePresentation: page === "statistics"
            });
        }, delay);
    }

    function settingsRuntimeIdentity(runtime) {
        if (!runtime) return "";
        var collector = objectValue(runtime.collector);
        return [
            String(collector.status || ""),
            collector.paused === true ? "paused" : "running",
            String(collector.display || ""),
            String(runtime.runtimePhase || ""),
            (Array.isArray(runtime.errorCodes) ? runtime.errorCodes : []).join(",")
        ].join("|");
    }

    function dispatchAutomaticRefresh(changedKeys, settingsRuntimeChanged) {
        var page = App.currentPage || "overview";
        var policy = PAGE_REFRESH_POLICIES[page];
        if (!policy) return;
        var semanticChange = intersects(changedKeys, policy.automaticGenerations);
        if (page === "settings" && settingsRuntimeChanged) semanticChange = true;
        if (!semanticChange || !automaticRefreshAllowedForPage(page)) return;
        if (policy.deferred) {
            scheduleAutomaticPageRefresh();
            return;
        }
        clearScheduledAutomaticPageRefresh();
        refreshCurrentPageData(null, { automatic: true });
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

    function sameRuntimeContinuity(previous, next) {
        if (!previous || !next) return false;
        return !!(
            previous.displaySpanId
            && next.displaySpanId
            && previous.displaySpanId === next.displaySpanId
            && previous.stableLiveKeyHash
            && previous.stableLiveKeyHash === next.stableLiveKeyHash
        );
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
    App.runtimeContinuityKey = runtimeVisualContinuityKey;

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

    App.projectClockSeconds = function (clock, nowMs) {
        return App.computeClockDurationNow(clock, nowMs);
    };
    App.sameLiveContinuity = function (previousClock, incomingClock) {
        var previous = App.validateLiveClock(previousClock);
        var incoming = App.validateLiveClock(incomingClock);
        return sameRuntimeContinuity(
            previous ? {
                displaySpanId: previous.display_span_id,
                stableLiveKeyHash: previous.stable_live_key_hash
            } : null,
            incoming ? {
                displaySpanId: incoming.display_span_id,
                stableLiveKeyHash: incoming.stable_live_key_hash
            } : null
        );
    };

    function resetClientGeneration(reason) {
        if (App.requestCoordinator) App.requestCoordinator.bumpDataEpoch();
        if (App.overview && App.overview.resetGeneration) App.overview.resetGeneration();
        if (App.timeline && App.timeline.resetGeneration) App.timeline.resetGeneration();
        if (App.statistics && App.statistics.resetGeneration) App.statistics.resetGeneration();
        if (App.rules && App.rules.resetGeneration) App.rules.resetGeneration();
        if (App.settings && App.settings.resetGeneration) App.settings.resetGeneration();
        if (App.fdWork && App.fdWork.resetGeneration) App.fdWork.resetGeneration();
        if (typeof App.setRulesLoading === "function") App.setRulesLoading(false);
        if (typeof App.setSettingsLoading === "function") App.setSettingsLoading(false);
        App.lastRefreshState = null;
        App.activePageRefreshInFlight = false;
        App.activePageRefreshPromise = null;
        App.activePageRefreshPending = null;
        App.liveClockContractRefreshRequested = false;
        App.liveClockContractViolation = null;
        App.liveClockViolationKeys = {};
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

    function runtimeIdentityFromPayload(payload) {
        var envelope = rawRuntimeEnvelope(payload);
        if (!envelope || Number(envelope.schema_version) !== 2) return null;
        var snapshot = objectValue(envelope.snapshot);
        var revisions = objectValue(envelope.revisions);
        var clock = App.validateLiveClock(envelope.clock);
        return {
            displaySpanId: clock ? clock.display_span_id : "",
            stableLiveKeyHash: clock ? clock.stable_live_key_hash : "",
            liveRevision: String(snapshot.revision || ""),
            pageRevision: String(revisions.page || ""),
            sampleId: String(snapshot.id || "")
        };
    }
    App.runtimeIdentityFromPayload = runtimeIdentityFromPayload;

    function incomingRuntimeCompatible(payload, page, reportDate) {
        var envelope = rawRuntimeEnvelope(payload);
        if (!payload || payload.ok !== true || !envelope || Number(envelope.schema_version) !== 2) {
            return false;
        }
        var expectedPage = String(page || App.currentPage || "overview");
        var expectedDate = payloadReportDate(payload, expectedPage, reportDate);
        if (expectedPage !== String(App.currentPage || "overview")) return false;
        if (expectedPage === "timeline") {
            var currentDate = App.runtimeReportDateForPage("timeline", reportDate);
            if (expectedDate && currentDate && expectedDate !== currentDate) return false;
        } else if (expectedDate && expectedDate !== App.localTodayStr()) {
            return false;
        }
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

    App.setLiveRuntimeScope = function (page, reportDate) {
        liveRuntimeStore.setScope(page, reportDate);
    };

    App.getActiveLiveClock = function () {
        var runtime = liveRuntimeStore.get();
        if (!runtime || runtime.page !== (App.currentPage || "overview")) return null;
        return runtime.liveClock || null;
    };

    App.applyLocalTicker = function () {
        var runtime = liveRuntimeStore.get();
        var tickerPage = App.currentPage || "overview";
        var pageRoot = document.getElementById("page-" + tickerPage);
        var liveTargets = pageRoot
            ? pageRoot.querySelectorAll('[data-live-clock-target="1"]')
            : [];
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
    };

    function invalidateProjectCatalog() {
        if (App.projectCatalog && typeof App.projectCatalog.invalidate === "function") {
            App.projectCatalog.invalidate();
        }
    }
    App.invalidateProjectCatalog = invalidateProjectCatalog;

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

    function refreshStatusFromRefreshState(state) {
        if (!state || state.ok !== true) return refreshStatus();
        return refreshStatusFromRuntime(liveRuntimeStore.get());
    }
    App.refreshStatusFromRefreshState = refreshStatusFromRefreshState;

    function refreshOverview() {
        var token = App.requestCoordinator.beginLatest("overview", "today");
        return App.bridge.getOverview().then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return;
            var bundle = App.handleResult(result, function (msg) { throw new Error(msg); });
            if (!bundle || !App.acceptPagePayloadRuntime(bundle, "overview", bundle.date)) return;
            var runtime = liveRuntimeStore.get();
            var overview = Object.assign({}, bundle.overview || {});
            overview.date = bundle.date || overview.date;
            overview.current_activity = runtime ? runtime.currentActivity : {};
            overview.current_session = bundle.current_session || null;
            overview.project_distribution = bundle.project_distribution || {
                total_seconds: 0,
                segments: []
            };
            overview.recent = bundle.recent || [];
            overview.kpi_live_targets = bundle.kpi_live_targets || {};
            if (overview.today_total_seconds === undefined) overview.today_total_seconds = bundle.today_total_seconds || 0;
            if (overview.classified_seconds === undefined) overview.classified_seconds = bundle.classified_seconds || 0;
            if (overview.uncategorized_seconds === undefined) overview.uncategorized_seconds = bundle.uncategorized_seconds || 0;
            App.showOverview(overview);
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token)) App.showError("刷新失败");
        });
    }
    App.refreshOverview = refreshOverview;

    function refreshTimeline() {
        return typeof App.refreshTimeline === "function" ? App.refreshTimeline() : Promise.resolve();
    }

    var ACTIVE_PAGE_REFRESHERS = Object.freeze({
        overview: function () {
            return refreshOverview();
        },
        timeline: function (acceptedState) {
            if (!pageHasLoadedData("timeline")
                && !pageIsLoading("timeline")
                && typeof App.loadTimelineReport === "function") {
                return App.loadTimelineReport(pageReportDate("timeline"), { showLoading: true });
            }
            if (!pageHasLoadedData("timeline")) return Promise.resolve();
            if (pageIsEditing("timeline")) {
                refreshCurrentActivityFromState(acceptedState || App.lastRefreshState);
                return Promise.resolve();
            }
            return refreshTimeline();
        },
        statistics: function (_acceptedState, options) {
            if (!pageHasLoadedData("statistics") && typeof App.initStatisticsDefaults === "function") {
                App.initStatisticsDefaults();
            }
            return typeof App.loadStatisticsExportSummary === "function"
                ? App.loadStatisticsExportSummary(
                    options && options.preservePresentation === true
                        ? { preservePresentation: true }
                        : undefined
                )
                : Promise.resolve();
        },
        rules: function (_acceptedState, options) {
            var capability = pageCapability("rules");
            return capability && typeof capability.onRefreshRequested === "function"
                ? capability.onRefreshRequested(options || {})
                : Promise.resolve();
        },
        settings: function () {
            return typeof App.loadSettingsPrivacyStatus === "function"
                ? App.loadSettingsPrivacyStatus()
                : Promise.resolve();
        }
    });

    function refreshActivePage(acceptedState, options, expectedPage) {
        var page = String(expectedPage || App.currentPage || "overview");
        if (App.currentPage !== page) return Promise.resolve(null);
        var refresher = ACTIVE_PAGE_REFRESHERS[page];
        if (typeof refresher !== "function") return Promise.resolve(null);
        var refreshEpoch = nonNegativeInt(pageRefreshEpoch[page], 0);
        var beforeEvidence = pageRefreshEvidence(page);
        return Promise.resolve(refresher(acceptedState, options)).then(function (result) {
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
            : App.bridge.getRefreshState(
                refreshPage === "timeline" ? pageReportDate("timeline") : null
            ).then(function (result) {
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
                    ? refreshStatusFromRefreshState(acceptedState)
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

    var PAGE_LEAVE_RESETTERS = Object.freeze({
        timeline: "resetTimelineTransientUi",
        statistics: "resetStatisticsTransientUi",
        rules: "resetRulesTransientUi",
        settings: "resetSettingsTransientUi"
    });

    function resetPageTransientUi(pageId) {
        var resetterName = PAGE_LEAVE_RESETTERS[pageId];
        var resetter = resetterName && App[resetterName];
        if (typeof resetter === "function") resetter({ restoreFocus: false });
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
            pageId === "timeline" ? pageReportDate("timeline") : null
        );
        refreshCurrentActivityFromState(App.lastRefreshState, { forceRender: true });
        if (!pageNeedsRefresh(pageId)) return;
        refreshActivePage(App.lastRefreshState, { navigation: true }, pageId).catch(function () {
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
        bind("timeline-prev-btn", "click", App.goPrevDay);
        bind("timeline-next-btn", "click", App.goNextDay);
        bind("timeline-today-btn", "click", App.goToday);
        bind("timeline-date-input", "change", function (event) {
            App.goToDate(event.target.value || null);
        });
        [
            ["timeline-merge-previous", "merge", "previous"],
            ["timeline-merge-next", "merge", "next"],
            ["timeline-split-session", "split"],
            ["timeline-copy-session", "copy"]
        ].forEach(function (action) {
            bind(action[0], "click", function () {
                App.runTimelineSessionOperation(action[1], action[2] ? { direction: action[2] } : undefined);
            });
        });
        bind("timeline-hide-session", "click", function (event) {
            App.confirmTimelineDeletion("hide", {}, event.currentTarget);
        });
        bind("edit-project-select", "change", function () {
            App.fdWorkStatusOverride = null;
            App.updateFDWorkEntryButton();
            App.scheduleTimelineAutosave(0);
        });
        bind("edit-note-text", "compositionstart", App.handleTimelineCompositionStart);
        bind("edit-note-text", "compositionend", App.handleTimelineCompositionEnd);
        bind("edit-note-text", "input", App.handleTimelineNoteInput);
        bind("edit-note-text", "blur", App.handleTimelineNoteBlur);
        bind("edit-duration-input", "change", App.handleTimelineDurationChange);
        bind("fd-work-entry-btn", "click", App.openFDWorkEntryForSelection);
        bind("timeline-project-filter", "change", App.applyTimelineProjectFilter);
        bind("timeline-details-close", "click", App.closeTimelineDrawer);
        bind("timeline-drawer-backdrop", "click", App.closeTimelineDrawer);
        bind("timeline-advanced-toggle", "click", App.toggleTimelineAdvancedMenu);
        bind("statistics-today-btn", "click", function () { App.applyStatisticsQuickRange("today"); });
        bind("statistics-week-btn", "click", function () { App.applyStatisticsQuickRange("week"); });
        bind("statistics-month-btn", "click", function () { App.applyStatisticsQuickRange("month"); });
        bind("statistics-all-btn", "click", function () { App.applyStatisticsQuickRange("all"); });
        bind("statistics-apply-range-btn", "click", App.applyStatisticsDraftSelection);
        bind("stats-export-action-btn", "click", App.exportStatisticsCsv);
        bind("settings-clipboard-toggle", "change", App.handleCaptureToggleChange);
        bind("settings-launch-at-login-toggle", "change", App.handleLaunchAtLoginToggleChange);
        bind("settings-fd-work-toggle", "change", App.handleFDWorkToggleChange);
        bind("settings-fd-work-reconnect", "click", App.reconnectFDWork);
        bind("settings-backup-export-btn", "click", App.exportEncryptedBackup);
        bind("settings-backup-manifest-btn", "click", App.previewEncryptedBackupManifest);
        bind("settings-backup-import-btn", "click", App.importEncryptedBackup);
        bind("settings-clear-local-data-btn", "click", App.clearAllLocalData);
        bind("settings-clear-all-btn", "click", App.clearAllLocalData);
        if (App.initRulesPanelEvents) App.initRulesPanelEvents();
        if (App.initTimelineAccessibility) App.initTimelineAccessibility();
        if (App.initSettingsCategories) App.initSettingsCategories();
        if (App.initPasswordRevealControls) App.initPasswordRevealControls();
        bind("first-run-notice-accept-btn", "click", App.acceptFirstRunNotice);
        bind("first-run-notice-retry-btn", "click", App.retryFirstRunNotice);
        bind("first-run-notice-close-btn", "click", function () {
            if (App.firstRunNoticeViewingFromSettings) App.hideFirstRunNotice();
        });
        bind("settings-privacy-notice-btn", "click", App.openPrivacyNoticeFromSettings);
        bind("settings-recovery-btn", "click", App.recoverDatabaseMaintenance);
    }
    App.initButtons = initButtons;

    function updateCurrentActivityCacheFromRuntime(runtime) {
        if (!runtime) return;
        updatePageCurrentActivity(
            App.currentPage || "overview",
            runtime.currentActivity || {}
        );
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
        updateCurrentActivityCacheFromRuntime(runtime);
        if (options.forceRender !== true) return;
        var element = App.currentPage === "overview"
            ? document.getElementById("current-activity")
            : App.currentPage === "timeline"
            ? document.getElementById("timeline-current")
            : null;
        if (element) App.renderCurrentActivityElement(element, runtime.currentActivity || {}, App.currentPage);
    }
    App.refreshCurrentActivityFromState = refreshCurrentActivityFromState;
    App.refreshTimelineCurrentActivityFromState = function (state) {
        if (App.currentPage !== "timeline") return;
        refreshCurrentActivityFromState(state, { forceRender: true });
    };

    function runRevisionCheck() {
        if (App.refreshCheckInFlight) {
            return App.activePageRefreshPromise || Promise.resolve();
        }
        App.refreshCheckInFlight = true;
        var timelineDate = pageReportDate("timeline");
        var token = App.requestCoordinator.beginLatest(
            "heartbeat",
            App.currentPage + "|" + (timelineDate || "")
        );
        return App.bridge.getRefreshState(
            App.currentPage === "timeline" ? timelineDate : null
        ).then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return;
            var state = App.handleResult(result, function () { return null; });
            if (!state) return;
            var previousRuntime = liveRuntimeStore.get();
            var envelope = rawRuntimeEnvelope(state);
            if (!envelope || Number(envelope.schema_version) !== 2) return;
            var snapshot = objectValue(envelope.snapshot);
            var incomingIdentity = runtimeIdentityFromPayload(state) || {};
            var incomingCurrent = objectValue(envelope.current_activity);
            var nextIdentity = [
                incomingCurrent.active === true ? "active" : "inactive",
                incomingIdentity.displaySpanId || "",
                incomingIdentity.stableLiveKeyHash || "",
                String(incomingCurrent.persisted_activity_id || incomingCurrent.activity_id || "")
            ].join("|");
            var previousIdentity = currentActivityRenderIdentity(previousRuntime);
            var liveStateChanged = !previousRuntime
                || previousRuntime.liveRevision !== String(snapshot.revision || "");
            var currentActivityIdentityChanged = previousIdentity !== nextIdentity;
            var changedGenerations = changedGenerationKeys(
                previousRuntime ? previousRuntime.generations : null,
                objectValue(envelope.generations)
            );
            var previousSettingsRuntimeIdentity = settingsRuntimeIdentity(previousRuntime);
            var renderCurrent = liveStateChanged
                || currentActivityIdentityChanged
                || App.liveClockContractRefreshRequested;
            if (!App.acceptRefreshStateRuntime(state)) return;
            var acceptedRuntime = liveRuntimeStore.get();
            var settingsRuntimeChanged = !!previousRuntime
                && previousSettingsRuntimeIdentity !== settingsRuntimeIdentity(acceptedRuntime);
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
            dispatchAutomaticRefresh(changedGenerations, settingsRuntimeChanged);
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
            try { runRevisionCheck(); } catch (error) {}
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
        if (App.shellVisible === visible) return Promise.resolve();
        App.shellVisible = visible;
        if (!visible) {
            stopHeartbeat();
            return Promise.resolve();
        }
        return Promise.resolve(
            typeof App.runRevisionCheck === "function"
                ? App.runRevisionCheck()
                : null
        ).then(function () {
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
                return App.bridge.getRefreshState(
                    App.currentPage === "timeline" ? pageReportDate("timeline") : null
                );
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

    // Retry for privacy notice load failure; cannot bypass authorization.
    function retryFirstRunNotice() {
        if (App.firstRunNoticeLoading) return Promise.resolve(false);
        App.firstRunNoticeLoaded = false;
        return App.loadFirstRunNotice({ force: true }).then(function () {
            if (App.privacyGateState === "accepted_ready") {
                return continueStartupAfterPrivacyGate();
            }
            // acceptance_required: the gate is shown again by loadFirstRunNotice.
            // load_failed: the blocking error is shown again. Either way, do
            // not continue startup.
            return false;
        });
    }
    App.retryFirstRunNotice = retryFirstRunNotice;

    function init() {
        initNav();
        initButtons();
        App.loadFirstRunNotice().then(function () {
            // Only accepted_ready continues startup; other states stay fail-closed.
            if (App.privacyGateState === "accepted_ready") {
                return continueStartupAfterPrivacyGate();
            }
            return null;
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
