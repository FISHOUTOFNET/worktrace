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
        listProjectsForTimeline: fixedBridgeMethod("list_projects_for_timeline"),
        mergeTimelineSession: fixedBridgeMethod("merge_timeline_session"),
        previewEncryptedBackupManifest: fixedBridgeMethod("preview_encrypted_backup_manifest"),
        previewProjectRuleImpact: fixedBridgeMethod("preview_project_rule_impact"),
        previewProjectRulesBatchImpact: fixedBridgeMethod("preview_project_rules_batch_impact"),
        saveTimelineSessionEdit: fixedBridgeMethod("save_timeline_session_edit"),
        setClipboardCaptureEnabled: fixedBridgeMethod("set_clipboard_capture_enabled"),
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

    function nonNegativeInt(value, fallback) {
        var parsed = parseInt(value, 10);
        return isNaN(parsed) || parsed < 0 ? (fallback || 0) : parsed;
    }

    function objectValue(value) {
        return value && typeof value === "object" ? value : {};
    }

    function frozenRuntime(value) {
        if (!value || typeof value !== "object") return null;
        var copy = Object.assign({}, value);
        [
            "liveClock", "currentActivity", "recentFirstRow", "currentProject",
            "collector", "workerHealth", "generations", "identity", "revisions"
        ].forEach(function (field) {
            if (copy[field] && typeof copy[field] === "object") {
                copy[field] = Object.freeze(Object.assign({}, copy[field]));
            }
        });
        if (Array.isArray(copy.degradedWorkers)) copy.degradedWorkers = Object.freeze(copy.degradedWorkers.slice());
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
        if (previous.displaySpanId && next.displaySpanId) {
            return previous.displaySpanId === next.displaySpanId;
        }
        return !!(
            previous.stableLiveKeyHash
            && next.stableLiveKeyHash
            && previous.stableLiveKeyHash === next.stableLiveKeyHash
        );
    }

    function projectAcceptedClock(clock, nowMs) {
        if (!clock) return 0;
        var base = nonNegativeInt(clock.carry_seconds, clock.duration_seconds_at_sample);
        if (clock.is_live !== true || !clock.live_started_at_epoch_ms) return base;
        var elapsed = Math.floor((nonNegativeInt(nowMs, Date.now()) - clock.live_started_at_epoch_ms) / 1000);
        return base + Math.max(0, elapsed);
    }

    function normalizeRuntimeClock(envelope, collector, previousRuntime, nowMs) {
        var source = objectValue(envelope.clock);
        if (!Object.keys(source).length) return null;
        var identity = objectValue(envelope.identity);
        var snapshot = objectValue(envelope.snapshot);
        var durationAtSample = Math.max(
            nonNegativeInt(source.duration_seconds_at_sample, 0),
            nonNegativeInt(source.current_live_duration_seconds, 0),
            nonNegativeInt(source.persisted_duration_seconds, 0)
        );
        var sampleEpochMs = nonNegativeInt(
            source.sample_epoch_ms,
            nonNegativeInt(snapshot.timestamp_epoch_ms, 0)
        );
        var collectorRunning = String(collector.status || "") === "running";
        var ticking = source.is_live === true
            && collector.paused !== true
            && collectorRunning
            && String(envelope.runtime_phase || "") !== "stopped"
            && String(envelope.runtime_phase || "") !== "stopping";
        var acceptedSeconds = durationAtSample;
        if (ticking && sampleEpochMs > 0) {
            acceptedSeconds += Math.max(0, Math.floor((nowMs - sampleEpochMs) / 1000));
        }
        var continuityCandidate = {
            displaySpanId: String(identity.display_span_id || source.display_span_id || ""),
            stableLiveKeyHash: String(identity.stable_live_key_hash || source.stable_live_key_hash || "")
        };
        if (previousRuntime && previousRuntime.liveClock && sameRuntimeContinuity(previousRuntime, continuityCandidate)) {
            acceptedSeconds = Math.max(
                acceptedSeconds,
                projectAcceptedClock(previousRuntime.liveClock, nowMs)
            );
        }
        var normalized = Object.assign({}, source, {
            display_span_id: continuityCandidate.displaySpanId,
            stable_live_key_hash: continuityCandidate.stableLiveKeyHash,
            duration_seconds_at_sample: acceptedSeconds,
            current_live_duration_seconds: acceptedSeconds,
            current_elapsed_at_sample: acceptedSeconds,
            active_elapsed_at_sample: acceptedSeconds,
            carry_seconds: acceptedSeconds,
            source_live_started_at_epoch_ms: nonNegativeInt(source.live_started_at_epoch_ms, 0),
            live_started_at_epoch_ms: ticking ? nowMs : 0,
            sample_epoch_ms: sampleEpochMs,
            is_live: ticking,
            current_duration_live: ticking && source.current_duration_live === true,
            project_duration_live: ticking && (
                source.project_duration_live === true
                || source.is_project_duration_live === true
            ),
            is_project_duration_live: ticking && (
                source.project_duration_live === true
                || source.is_project_duration_live === true
            )
        });
        return App.normalizeLiveClock ? App.normalizeLiveClock(normalized) : normalized;
    }

    function normalizeRuntimeEnvelope(value, page, reportDate, previousRuntime) {
        var envelope = rawRuntimeEnvelope(value);
        if (!envelope || Number(envelope.schema_version || 0) !== 2) return null;
        var surface = String(envelope.surface || page || App.currentPage || "overview");
        var runtimePage = String(page || App.currentPage || surface || "overview");
        var scopeDate = String(
            envelope.scope_report_date
            || reportDate
            || App.runtimeReportDateForPage(runtimePage, reportDate)
            || ""
        );
        var liveDate = String(envelope.live_report_date || scopeDate || "");
        var snapshot = objectValue(envelope.snapshot);
        var identity = objectValue(envelope.identity);
        var revisions = objectValue(envelope.revisions);
        var collector = objectValue(envelope.collector);
        var nowMs = Date.now();
        var liveClock = scopeDate && liveDate && scopeDate !== liveDate
            ? null
            : normalizeRuntimeClock(envelope, collector, previousRuntime, nowMs);
        return {
            schemaVersion: 2,
            surface: surface,
            page: runtimePage,
            reportDate: scopeDate,
            liveReportDate: liveDate,
            acceptedAtEpochMs: nowMs,
            liveClock: liveClock,
            displaySpanId: String(identity.display_span_id || (liveClock && liveClock.display_span_id) || ""),
            stableLiveKeyHash: String(identity.stable_live_key_hash || (liveClock && liveClock.stable_live_key_hash) || ""),
            liveRevision: String(snapshot.revision || ""),
            structureRevision: String(revisions.structure || ""),
            pageRevision: String(revisions.page || ""),
            sampleId: String(snapshot.id || ""),
            currentActivityDisplaySpanId: String(identity.current_activity_display_span_id || ""),
            currentResourceIdentityHash: String(identity.current_resource_identity_hash || ""),
            currentActivity: objectValue(envelope.current_activity),
            recentFirstRow: envelope.recent_first_row && typeof envelope.recent_first_row === "object"
                ? envelope.recent_first_row
                : null,
            currentProject: envelope.current_project && typeof envelope.current_project === "object"
                ? envelope.current_project
                : null,
            collector: collector,
            runtimePhase: String(envelope.runtime_phase || "unavailable"),
            workerHealth: objectValue(envelope.worker_health),
            degradedWorkers: Array.isArray(envelope.degraded_workers) ? envelope.degraded_workers : [],
            generations: objectValue(envelope.generations),
            databaseReplacementEpoch: nonNegativeInt(envelope.database_replacement_epoch, 0),
            errorCodes: Array.isArray(envelope.error_codes) ? envelope.error_codes : [],
            identity: identity,
            revisions: revisions
        };
    }

    function runtimeVisualContinuityKey(runtime) {
        if (!runtime) return "";
        return [
            runtime.page || "",
            runtime.displaySpanId || "",
            runtime.stableLiveKeyHash || "",
            runtime.currentActivityDisplaySpanId || "",
            runtime.currentResourceIdentityHash || ""
        ].join("|");
    }
    App.runtimeVisualContinuityKey = runtimeVisualContinuityKey;
    App.runtimeContinuityKey = runtimeVisualContinuityKey;

    var liveRuntimeStore = Object.freeze({
        get: function () { return runtimeState; },
        acceptEnvelope: function (value, page, reportDate) {
            var next = normalizeRuntimeEnvelope(value, page, reportDate, runtimeState);
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

    App.projectClockSeconds = projectAcceptedClock;
    App.computeActiveElapsedNow = projectAcceptedClock;
    App.activeElapsedNow = projectAcceptedClock;
    App.activeElapsedAtSample = function (clock) {
        return clock ? nonNegativeInt(clock.carry_seconds, clock.duration_seconds_at_sample) : 0;
    };
    App.sameLiveContinuity = function (previousClock, incomingClock) {
        if (!previousClock || !incomingClock) return false;
        return sameRuntimeContinuity(
            {
                displaySpanId: String(previousClock.display_span_id || ""),
                stableLiveKeyHash: String(previousClock.stable_live_key_hash || "")
            },
            {
                displaySpanId: String(incomingClock.display_span_id || ""),
                stableLiveKeyHash: String(incomingClock.stable_live_key_hash || "")
            }
        );
    };

    function resetClientGeneration(reason) {
        if (App.requestCoordinator) App.requestCoordinator.bumpDataEpoch();
        App.timelineLoaded = false;
        App.statisticsLoaded = false;
        App.rulesLoaded = false;
        App.settingsLoaded = false;
        App.currentSessions = [];
        App.selectedProjectionInstanceKey = null;
        App.selectedProjectionRevision = null;
        App.editingSession = null;
        App.detailsOwner = null;
        App.timelineOwner = null;
        App.mutationOwner = null;
        App.mutationState = "idle";
        App.detailsInFlight = {};
        App.projectsCache = null;
        App.projectsLoading = false;
        App.projectsLoadPromise = null;
        App.lastTimelineData = null;
        App.lastProjectRulesData = null;
        App.lastSessionDetailsViewModel = null;
        App.lastSessionActivitySummaryViewModel = null;
        App.lastRefreshState = null;
        App.statisticsAcceptedPayload = null;
        App.rulesLoadPromise = null;
        App.activePageRefreshInFlight = false;
        App.activePageRefreshPromise = null;
        App.activePageRefreshPending = null;
        App.reconcileInFlight = false;
        App.liveClockContractRefreshRequested = false;
        App.liveClockContractViolation = null;
        App.firstRunNoticeLoaded = false;
        App.firstRunNoticeLoading = false;
        liveRuntimeStore.reset();
        App._monotonicRenderState = {};
        App.overviewRequestToken = (App.overviewRequestToken || 0) + 1;
        App.timelineRequestToken = (App.timelineRequestToken || 0) + 1;
        App.statisticsRequestToken = (App.statisticsRequestToken || 0) + 1;
        App.rulesRequestToken = (App.rulesRequestToken || 0) + 1;
        App.settingsRequestToken = (App.settingsRequestToken || 0) + 1;
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
        if (!envelope || Number(envelope.schema_version || 0) !== 2) return null;
        var identity = objectValue(envelope.identity);
        var snapshot = objectValue(envelope.snapshot);
        var revisions = objectValue(envelope.revisions);
        return {
            displaySpanId: String(identity.display_span_id || ""),
            stableLiveKeyHash: String(identity.stable_live_key_hash || ""),
            liveRevision: String(snapshot.revision || ""),
            pageRevision: String(revisions.page || ""),
            sampleId: String(snapshot.id || ""),
            currentActivityDisplaySpanId: String(identity.current_activity_display_span_id || ""),
            currentResourceIdentityHash: String(identity.current_resource_identity_hash || "")
        };
    }
    App.runtimeIdentityFromPayload = runtimeIdentityFromPayload;

    function incomingRuntimeCompatible(payload, page, reportDate) {
        var envelope = rawRuntimeEnvelope(payload);
        if (!payload || payload.ok !== true || !envelope || Number(envelope.schema_version || 0) !== 2) {
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
        var currentRuntime = liveRuntimeStore.get();
        if (!currentRuntime || !currentRuntime.liveClock) return true;
        var incoming = runtimeIdentityFromPayload(payload);
        if (!incoming) return false;
        if (currentRuntime.displaySpanId && incoming.displaySpanId) {
            return currentRuntime.displaySpanId === incoming.displaySpanId;
        }
        if (currentRuntime.stableLiveKeyHash && incoming.stableLiveKeyHash) {
            return currentRuntime.stableLiveKeyHash === incoming.stableLiveKeyHash;
        }
        return objectValue(envelope.current_activity).active !== true;
    }
    App.isPagePayloadCompatibleWithRuntime = incomingRuntimeCompatible;

    function noteRejectedPagePayload(payload, page, reportDate) {
        var envelope = rawRuntimeEnvelope(payload) || {};
        var identity = objectValue(envelope.identity);
        App.liveClockContractRefreshRequested = true;
        App.liveClockContractViolation = {
            spanId: String(identity.display_span_id || ""),
            page: String(page || App.currentPage || "overview"),
            reason: "page_payload_runtime_v2_mismatch",
            reportDate: reportDate || envelope.scope_report_date || ""
        };
    }
    App.noteRejectedPagePayload = noteRejectedPagePayload;

    function acceptLiveRuntimePayload(payload, page, reportDate, options) {
        if (!payload || payload.ok !== true) return false;
        options = options || {};
        var envelope = rawRuntimeEnvelope(payload);
        if (!envelope || Number(envelope.schema_version || 0) !== 2) return false;
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
        var clock = App.getActiveLiveClock();
        var tickerPage = App.currentPage || "overview";
        var pageRoot = document.getElementById("page-" + tickerPage);
        var liveTargets = pageRoot
            ? pageRoot.querySelectorAll('[data-live-duration-target="1"]')
            : [];
        if (!clock || clock.is_live !== true) return;
        var activeElapsedNowValue = projectAcceptedClock(clock, Date.now());
        for (var i = 0; i < liveTargets.length; i++) {
            var target = liveTargets[i];
            if (!App.liveTargetCompatibleWithRuntime(target, runtime)) {
                App.recordLiveClockContractViolation(
                    target.getAttribute("data-display-span-id") || "",
                    tickerPage,
                    "live_target_runtime_mismatch"
                );
                continue;
            }
            var baseAttr = target.getAttribute("data-display-base-seconds");
            if (baseAttr === null || baseAttr === "") {
                baseAttr = target.getAttribute("data-live-base-seconds");
            }
            if (baseAttr === null || baseAttr === "") continue;
            var displayBaseSeconds = parseInt(baseAttr, 10);
            if (isNaN(displayBaseSeconds)) continue;
            var semantic = target.getAttribute("data-duration-semantic") || "";
            if (semantic === "current-live" && displayBaseSeconds !== 0) {
                App.recordLiveClockContractViolation(
                    target.getAttribute("data-display-span-id") || "",
                    tickerPage,
                    "current_live_target_nonzero_base"
                );
                continue;
            }
            App.renderLiveDurationTarget(target, displayBaseSeconds, activeElapsedNowValue);
        }
    };

    function invalidateProjectCatalog() {
        App.projectsCache = null;
        App.projectsLoading = false;
        App.projectsLoadPromise = null;
        if (typeof App.loadProjects === "function") {
            Promise.resolve().then(function () { return App.loadProjects(); });
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
        var runtime = liveRuntimeStore.get();
        return refreshStatusFromRuntime(runtime);
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
            overview.live_clock = runtime ? runtime.liveClock : null;
            overview.display_span_id = runtime ? runtime.displaySpanId : "";
            overview.sample_id = runtime ? runtime.sampleId : "";
            overview.kpi_live_base = bundle.kpi_live_base || overview.kpi_live_base;
            overview.kpi_live_targets = bundle.kpi_live_targets || overview.kpi_live_targets;
            if (overview.today_total_seconds === undefined) overview.today_total_seconds = bundle.today_total_seconds || 0;
            if (overview.classified_seconds === undefined) overview.classified_seconds = bundle.classified_seconds || 0;
            if (overview.uncategorized_seconds === undefined) overview.uncategorized_seconds = bundle.uncategorized_seconds || 0;
            App.showOverview(overview);
            App.showRecent({ activities: bundle.activities || [] });
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token)) App.showError("刷新失败");
        });
    }
    App.refreshOverview = refreshOverview;

    function refreshTimeline() {
        return typeof App.refreshTimeline === "function" ? App.refreshTimeline() : Promise.resolve();
    }

    function _runCurrentPageRefresh(state, options) {
        App.activePageRefreshInFlight = true;
        var statePromise = state && state.ok === true
            ? Promise.resolve(state)
            : App.bridge.getRefreshState(
                App.currentPage === "timeline" ? App.timelineDate : null
            ).then(function (result) {
                return App.handleResult(result, function () { return null; });
            });
        return statePromise.then(function (acceptedState) {
            if (acceptedState && acceptedState.ok === true) App.acceptRefreshStateRuntime(acceptedState);
            var promises = [
                acceptedState && acceptedState.ok === true
                    ? refreshStatusFromRefreshState(acceptedState)
                    : refreshStatus()
            ];
            if (App.currentPage === "overview") {
                promises.push(refreshOverview());
            } else if (App.currentPage === "timeline" && App.timelineLoaded) {
                if (typeof App._timelineEditingActive !== "function" || !App._timelineEditingActive()) {
                    promises.push(refreshTimeline());
                } else {
                    refreshCurrentActivityFromState(acceptedState || App.lastRefreshState);
                }
            }
            return Promise.allSettled(promises);
        }).then(function (results) {
            App.lastFullRefreshAtEpochMs = Date.now();
            var anyError = results.some(function (item) { return item.status === "rejected"; });
            if (!anyError) App.clearError();
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

    function fullReconcileCollectionViews(reason) {
        if (App.reconcileInFlight) return App.activePageRefreshPromise || Promise.resolve();
        App.reconcileInFlight = true;
        return refreshCurrentPageData(null, { reason: reason || "reconcile" }).then(function () {
            App.lastReconcileAtEpochMs = Date.now();
        }).finally(function () {
            App.reconcileInFlight = false;
        });
    }
    App.fullReconcileCollectionViews = fullReconcileCollectionViews;

    function togglePause() {
        App.bridge.togglePause().then(function (result) {
            var status = App.handleResult(result, function (msg) { App.showError(msg); });
            App.showStatus(status);
        }).catch(function () {
            App.showError("切换暂停状态失败，请稍后重试。");
        });
    }
    App.togglePause = togglePause;

    function switchPage(pageId) {
        var navItems = document.querySelectorAll(".nav-item");
        var pages = document.querySelectorAll(".page");
        for (var i = 0; i < navItems.length; i++) navItems[i].classList.remove("active");
        for (var j = 0; j < pages.length; j++) pages[j].classList.remove("active");
        var navTarget = document.querySelector('.nav-item[data-page="' + pageId + '"]');
        var pageTarget = document.getElementById("page-" + pageId);
        if (navTarget) navTarget.classList.add("active");
        if (pageTarget) pageTarget.classList.add("active");
        App.currentPage = pageId;
        liveRuntimeStore.setScope(pageId, pageId === "timeline" ? App.timelineDate : null);
        if (pageId === "timeline" && !App.timelineLoaded && !App.timelineLoading) {
            App.loadTimelineReport(App.timelineDate, { showLoading: true });
        }
        if (pageId === "statistics" && !App.statisticsLoaded) {
            App.initStatisticsDefaults();
            App.loadStatisticsExportSummary();
        }
        if (pageId === "rules" && !App.rulesLoaded) App.loadProjectRules();
        if (pageId === "settings" && !App.settingsLoaded && !App.settingsLoading) {
            App.loadSettingsPrivacyStatus();
        }
        if (pageId === "overview" || (pageId === "timeline" && App.timelineLoaded)) {
            refreshCurrentPageData();
        }
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
            App.loadTimelineReport(event.target.value || null, { resetSelection: true, showLoading: true });
        });
        bind("edit-save-btn", "click", App.saveEdit);
        bind("edit-cancel-btn", "click", App.cancelEdit);
        [
            ["timeline-hide-session", "hide"],
            ["timeline-merge-previous", "merge", "previous"],
            ["timeline-merge-next", "merge", "next"],
            ["timeline-split-session", "split"],
            ["timeline-copy-session", "copy"]
        ].forEach(function (action) {
            bind(action[0], "click", function () {
                App.runTimelineSessionOperation(action[1], action[2] ? { direction: action[2] } : undefined);
            });
        });
        bind("edit-note-text", "input", App.updateNoteCount);
        bind("statistics-load-btn", "click", App.loadStatisticsExportSummary);
        bind("statistics-today-btn", "click", function () { App.applyStatisticsQuickRange("today"); });
        bind("statistics-7d-btn", "click", function () { App.applyStatisticsQuickRange("7d"); });
        bind("statistics-month-btn", "click", function () { App.applyStatisticsQuickRange("month"); });
        bind("stats-export-action-btn", "click", App.exportStatisticsCsv);
        bind("settings-clipboard-toggle", "change", App.handleCaptureToggleChange);
        bind("settings-backup-export-btn", "click", App.exportEncryptedBackup);
        bind("settings-backup-manifest-btn", "click", App.previewEncryptedBackupManifest);
        bind("settings-backup-import-btn", "click", App.importEncryptedBackup);
        bind("settings-clear-local-data-btn", "click", App.clearAllLocalData);
        bind("settings-clear-all-btn", "click", App.clearAllLocalData);
        if (App.initRulesPanelEvents) App.initRulesPanelEvents();
        bind("first-run-notice-accept-btn", "click", App.acceptFirstRunNotice);
        bind("first-run-notice-close-btn", "click", function () {
            if (App.firstRunNoticeViewingFromSettings) App.hideFirstRunNotice();
        });
        bind("settings-privacy-notice-btn", "click", App.openPrivacyNoticeFromSettings);
    }
    App.initButtons = initButtons;

    function updateCurrentActivityCacheFromRuntime(runtime) {
        if (!runtime) return;
        if (App.currentPage === "overview") {
            if (!App.lastOverviewSnapshot) App.lastOverviewSnapshot = {};
            App.lastOverviewSnapshot.current_activity = runtime.currentActivity || {};
        } else if (App.currentPage === "timeline") {
            if (!App.lastTimelineData) App.lastTimelineData = {};
            App.lastTimelineData.current_activity = runtime.currentActivity || {};
        }
    }

    function currentActivityRenderIdentity(runtime) {
        runtime = runtime || {};
        var current = runtime.currentActivity || {};
        return [
            current.active === true ? "active" : "inactive",
            runtime.liveClock && runtime.liveClock.current_duration_live === true ? "live" : "static",
            String(current.live_state || ""),
            String(runtime.displaySpanId || ""),
            String(runtime.currentActivityDisplaySpanId || ""),
            String(runtime.currentResourceIdentityHash || ""),
            String(runtime.stableLiveKeyHash || "")
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
        if (App.refreshCheckInFlight) return;
        App.refreshCheckInFlight = true;
        var token = App.requestCoordinator.beginLatest("heartbeat", App.currentPage + "|" + (App.timelineDate || ""));
        App.bridge.getRefreshState(App.currentPage === "timeline" ? App.timelineDate : null).then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return;
            var state = App.handleResult(result, function () { return null; });
            if (!state) return;
            var previousRuntime = liveRuntimeStore.get();
            var envelope = rawRuntimeEnvelope(state);
            if (!envelope || Number(envelope.schema_version || 0) !== 2) return;
            var snapshot = objectValue(envelope.snapshot);
            var revisions = objectValue(envelope.revisions);
            var incomingIdentity = runtimeIdentityFromPayload(state) || {};
            var incomingCurrent = objectValue(envelope.current_activity);
            var nextIdentity = [
                incomingCurrent.active === true ? "active" : "inactive",
                String(incomingCurrent.live_state || ""),
                incomingIdentity.displaySpanId || "",
                incomingIdentity.currentActivityDisplaySpanId || "",
                incomingIdentity.currentResourceIdentityHash || "",
                incomingIdentity.stableLiveKeyHash || ""
            ].join("|");
            var previousIdentity = currentActivityRenderIdentity(previousRuntime);
            var isFirstCheck = !previousRuntime;
            var liveStateChanged = isFirstCheck || previousRuntime.liveRevision !== String(snapshot.revision || "");
            var pageStructureChanged = isFirstCheck || previousRuntime.pageRevision !== String(revisions.page || "");
            var currentActivityIdentityChanged = previousIdentity !== nextIdentity;
            var renderCurrent = liveStateChanged
                || pageStructureChanged
                || currentActivityIdentityChanged
                || App.liveClockContractRefreshRequested;
            if (!App.acceptRefreshStateRuntime(state)) return;
            refreshCurrentActivityFromState(state, { forceRender: renderCurrent });
            refreshStatusFromRuntime(liveRuntimeStore.get());
            var triggered = false;
            if (pageStructureChanged || App.liveClockContractRefreshRequested) {
                triggered = true;
                App.liveClockContractRefreshRequested = false;
                refreshCurrentPageData(state);
            }
            var now = Date.now();
            if (!triggered && !App.reconcileInFlight
                && now - App.lastReconcileAtEpochMs >= App.RECONCILE_INTERVAL_MS) {
                fullReconcileCollectionViews("heartbeat-lowfreq");
            }
        }).finally(function () {
            if (App.requestCoordinator.isCurrent(token)) App.refreshCheckInFlight = false;
        });
    }
    App.runRevisionCheck = runRevisionCheck;

    function startHeartbeat() {
        if (App.heartbeatTimer !== null) clearInterval(App.heartbeatTimer);
        App.heartbeatTimer = setInterval(function () {
            try { App.applyLocalTicker(); } catch (error) {}
            try { runRevisionCheck(); } catch (error) {}
        }, App.HEARTBEAT_INTERVAL_MS);
    }
    App.startHeartbeat = startHeartbeat;

    function init() {
        initNav();
        initButtons();
        App.loadFirstRunNotice().then(function (noticeConfirmed) {
            if (!noticeConfirmed) return;
            var preload = typeof App.loadProjects === "function" ? App.loadProjects() : Promise.resolve();
            return preload.then(function () {
                return App.bridge.getRefreshState(
                    App.currentPage === "timeline" ? App.timelineDate : null
                );
            }).then(function (result) {
                var state = App.handleResult(result, function () { return null; });
                if (state) App.acceptRefreshStateRuntime(state);
                return refreshCurrentPageData(state);
            }).then(function () {
                App.lastReconcileAtEpochMs = Date.now();
                startHeartbeat();
            }, startHeartbeat);
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
