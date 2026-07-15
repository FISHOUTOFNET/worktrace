(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function absoluteDate(value) {
        if (!value || value === "--") return null;
        return String(value);
    }

    function nextTimelineOwner(date) {
        App.timelineEpoch = (App.timelineEpoch || 0) + 1;
        App.timelineOwner = {
            timelineEpoch: App.timelineEpoch,
            absoluteReportDate: absoluteDate(date)
        };
        return App.timelineOwner;
    }

    function nextSelectionOwner(date, projectionInstanceKey, projectionRevision) {
        App.selectionEpoch = (App.selectionEpoch || 0) + 1;
        App.detailsOwner = {
            dataEpoch: App.dataEpoch || 0,
            timelineEpoch: App.timelineEpoch || 0,
            selectionEpoch: App.selectionEpoch,
            absoluteReportDate: absoluteDate(date),
            projectionInstanceKey: projectionInstanceKey || "",
            projectionRevision: projectionRevision || ""
        };
        return App.detailsOwner;
    }

    function isCurrentDetailsOwner(owner) {
        return !!owner
            && App.detailsOwner === owner
            && owner.dataEpoch === (App.dataEpoch || 0)
            && owner.timelineEpoch === (App.timelineEpoch || 0)
            && owner.selectionEpoch === (App.selectionEpoch || 0)
            && owner.absoluteReportDate === absoluteDate(App.timelineDate)
            && owner.projectionInstanceKey === App.selectedProjectionInstanceKey
            && owner.projectionRevision === (App.selectedProjectionRevision || "");
    }

    function detailRequestKey(owner) {
        return [
            String(owner.dataEpoch || 0),
            String(owner.timelineEpoch || 0),
            owner.absoluteReportDate || "",
            owner.projectionInstanceKey || "",
            owner.projectionRevision || ""
        ].join("|");
    }

    function newRequestId() {
        if (window.crypto && typeof window.crypto.randomUUID === "function") {
            return window.crypto.randomUUID();
        }
        var bytes = new Uint8Array(16);
        if (window.crypto && typeof window.crypto.getRandomValues === "function") {
            window.crypto.getRandomValues(bytes);
        } else {
            for (var i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
        }
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        var hex = Array.prototype.map.call(bytes, function (b) {
            return ("0" + b.toString(16)).slice(-2);
        }).join("");
        return hex.slice(0, 8) + "-" + hex.slice(8, 12) + "-" + hex.slice(12, 16)
            + "-" + hex.slice(16, 20) + "-" + hex.slice(20);
    }

    function mutationIntentKey(method, date, projectionInstanceKey, projectionRevision, argsSignature) {
        return [
            method || "",
            absoluteDate(date) || "",
            projectionInstanceKey || "",
            projectionRevision || "",
            argsSignature || ""
        ].join("|");
    }

    function nextMutationOwner(method, date, projectionInstanceKey, projectionRevision, argsSignature) {
        var intentKey = mutationIntentKey(method, date, projectionInstanceKey, projectionRevision, argsSignature);
        if (App.mutationOwner && (App.mutationOwner.state === "pending" || App.mutationOwner.state === "unknown")) {
            if (App.mutationOwner.intentKey !== intentKey) return null;
            App.mutationOwner.state = "pending";
            App.mutationState = "pending";
            return App.mutationOwner;
        }
        App.mutationEpoch = (App.mutationEpoch || 0) + 1;
        App.mutationOwner = {
            dataEpoch: App.dataEpoch || 0,
            mutationEpoch: App.mutationEpoch,
            method: method || "",
            absoluteReportDate: absoluteDate(date),
            projectionInstanceKey: projectionInstanceKey || "",
            projectionRevision: projectionRevision || "",
            intentKey: intentKey,
            requestId: newRequestId(),
            state: "pending",
            payload: null,
            result: null
        };
        App.mutationState = "pending";
        return App.mutationOwner;
    }

    function isCurrentMutationOwner(owner) {
        return !!owner && App.mutationOwner === owner
            && owner.dataEpoch === (App.dataEpoch || 0)
            && (owner.state === "pending" || owner.state === "unknown");
    }

    function transitionMutation(owner, state, result) {
        if (!owner || App.mutationOwner !== owner) return false;
        owner.state = state;
        App.mutationState = state;
        if (result !== undefined) owner.result = result;
        return true;
    }

    function markMutationUnknown(owner) {
        return transitionMutation(owner, "unknown");
    }

    function releaseMutationOwner(owner, finalState, result) {
        if (owner && App.mutationOwner === owner) {
            transitionMutation(owner, finalState || "confirmed_failure", result);
            App.mutationOwner = null;
            return true;
        }
        return false;
    }

    function RequestCoordinator() {
        this.dataEpoch = 0;
        this.latest = Object.create(null);
        this.shared = Object.create(null);
        this.queued = Object.create(null);
    }

    RequestCoordinator.prototype.beginLatest = function (channel, logicalKey) {
        var current = this.latest[channel] || 0;
        var token = {
            channel: channel,
            logicalKey: logicalKey || "",
            sequence: current + 1,
            dataEpoch: this.dataEpoch
        };
        this.latest[channel] = token.sequence;
        return token;
    };

    RequestCoordinator.prototype.isCurrent = function (token) {
        return !!token
            && token.dataEpoch === this.dataEpoch
            && this.latest[token.channel] === token.sequence;
    };

    RequestCoordinator.prototype.share = function (channel, logicalKey, factory) {
        var key = channel + "|" + this.dataEpoch + "|" + (logicalKey || "");
        if (this.shared[key]) return this.shared[key];
        var self = this;
        var promise = Promise.resolve().then(factory).finally(function () {
            if (self.shared[key] === promise) delete self.shared[key];
        });
        this.shared[key] = promise;
        return promise;
    };

    RequestCoordinator.prototype.queueLatest = function (channel, logicalKey, runner) {
        var state = this.queued[channel];
        if (!state) {
            state = this.queued[channel] = { running: false, pending: null, promise: null };
        }
        state.pending = { logicalKey: logicalKey || "", runner: runner, dataEpoch: this.dataEpoch };
        if (state.running) return state.promise || Promise.resolve();
        var self = this;
        function drain() {
            var request = state.pending;
            state.pending = null;
            if (!request || request.dataEpoch !== self.dataEpoch) {
                state.running = false;
                state.promise = null;
                return Promise.resolve();
            }
            state.running = true;
            return Promise.resolve().then(request.runner).then(function (result) {
                if (state.pending) return drain().then(function () { return result; });
                state.running = false;
                state.promise = null;
                return result;
            }, function (error) {
                if (state.pending) return drain();
                state.running = false;
                state.promise = null;
                throw error;
            });
        }
        state.promise = drain();
        return state.promise;
    };

    RequestCoordinator.prototype.bumpDataEpoch = function () {
        this.dataEpoch += 1;
        App.dataEpoch = this.dataEpoch;
        this.latest = Object.create(null);
        this.shared = Object.create(null);
        this.queued = Object.create(null);
        return this.dataEpoch;
    };

    RequestCoordinator.prototype.invalidate = function (channel) {
        this.latest[channel] = (this.latest[channel] || 0) + 1;
        var prefix = channel + "|";
        for (var key in this.shared) {
            if (Object.prototype.hasOwnProperty.call(this.shared, key) && key.indexOf(prefix) === 0) {
                delete this.shared[key];
            }
        }
    };

    App.dataEpoch = App.dataEpoch || 0;
    App.timelineEpoch = App.timelineEpoch || 0;
    App.selectionEpoch = App.selectionEpoch || 0;
    App.detailsOwner = App.detailsOwner || null;
    App.mutationEpoch = App.mutationEpoch || 0;
    App.mutationOwner = App.mutationOwner || null;
    App.mutationState = App.mutationState || "idle";
    App.requestCoordinator = App.requestCoordinator || new RequestCoordinator();
    App.requestCoordinator.dataEpoch = App.dataEpoch;
    App.MUTATION_STATES = Object.freeze([
        "idle", "pending", "unknown", "confirmed_success", "confirmed_failure"
    ]);
    App.timelineRequestState = {
        absoluteDate: absoluteDate,
        detailRequestKey: detailRequestKey,
        isCurrentDetailsOwner: isCurrentDetailsOwner,
        isCurrentMutationOwner: isCurrentMutationOwner,
        mutationIntentKey: mutationIntentKey,
        markMutationUnknown: markMutationUnknown,
        newRequestId: newRequestId,
        nextMutationOwner: nextMutationOwner,
        nextSelectionOwner: nextSelectionOwner,
        nextTimelineOwner: nextTimelineOwner,
        releaseMutationOwner: releaseMutationOwner,
        transitionMutation: transitionMutation
    };

    App.invalidateProjectCatalog = function () {
        App.projectsCache = null;
        App.projectsLoading = false;
        App.requestCoordinator.invalidate("project-catalog");
    };

    // Install cross-page wrappers after the remaining modules have registered
    // their concrete functions but before ordinary user events are processed.
    setTimeout(function () {
        if (typeof App.resetFrontendAfterLocalDataReplacement === "function") {
            var originalReset = App.resetFrontendAfterLocalDataReplacement;
            App.resetFrontendAfterLocalDataReplacement = function () {
                App.requestCoordinator.bumpDataEpoch();
                App.overviewRequestToken = (App.overviewRequestToken || 0) + 1;
                App.recentRequestToken = (App.recentRequestToken || 0) + 1;
                App.timelineRequestToken = (App.timelineRequestToken || 0) + 1;
                App.statisticsRequestToken = (App.statisticsRequestToken || 0) + 1;
                App.settingsRequestToken = (App.settingsRequestToken || 0) + 1;
                App.rulesRequestToken = (App.rulesRequestToken || 0) + 1;
                App.timelineEpoch = (App.timelineEpoch || 0) + 1;
                App.selectionEpoch = (App.selectionEpoch || 0) + 1;
                App.detailsOwner = null;
                App.detailsInFlight = {};
                App.activePageRefreshInFlight = false;
                App.activePageRefreshPromise = null;
                App.pendingPageRefresh = null;
                App.lastRefreshState = null;
                App.liveRuntime = null;
                App._monotonicRenderState = {};
                App.statisticsLoading = false;
                App.rulesLoading = false;
                App.projectsLoading = false;
                App.invalidateProjectCatalog();
                return originalReset.apply(this, arguments);
            };
        }

        if (typeof App.refreshCurrentPageData === "function") {
            var originalRefresh = App.refreshCurrentPageData;
            App.refreshCurrentPageData = function (state, options) {
                var page = App.currentPage || "overview";
                var date = page === "timeline" ? (App.timelineDate || "") : "";
                return App.requestCoordinator.queueLatest(
                    "page-refresh",
                    page + "|" + date,
                    function () { return originalRefresh(state, options); }
                );
            };
            App.refreshAll = function () { return App.refreshCurrentPageData(); };
        }

        if (typeof App.loadProjects === "function") {
            var originalLoadProjects = App.loadProjects;
            App.loadProjects = function () {
                if (App.projectsCache) return Promise.resolve(App.projectsCache);
                return App.requestCoordinator.share(
                    "project-catalog",
                    "active",
                    function () { return originalLoadProjects(); }
                );
            };
        }

        if (typeof App.loadProjectRules === "function") {
            var originalLoadRules = App.loadProjectRules;
            App.loadProjectRules = function () {
                return App.requestCoordinator.share(
                    "project-rules",
                    "all",
                    function () { return originalLoadRules(); }
                );
            };
        }

        if (typeof App.callBridge === "function") {
            var originalCallBridge = App.callBridge;
            App.callBridge = function (method) {
                var args = Array.prototype.slice.call(arguments, 1);
                var promise = originalCallBridge.apply(this, [method].concat(args));
                if (/^(create|update|delete|archive|enable|disable)_project/.test(String(method || ""))) {
                    return Promise.resolve(promise).then(function (result) {
                        if (result && result.ok !== false) App.invalidateProjectCatalog();
                        return result;
                    });
                }
                return promise;
            };
        }
    }, 0);
})();
