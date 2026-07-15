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
            dataEpoch: App.dataEpoch || 0,
            timelineEpoch: App.timelineEpoch,
            absoluteReportDate: absoluteDate(date)
        };
        return App.timelineOwner;
    }

    function detailTuple(owner) {
        return [
            owner.absoluteReportDate || "",
            owner.projectionInstanceKey || "",
            owner.projectionRevision || ""
        ].join("|");
    }

    function nextSelectionOwner(date, projectionInstanceKey, projectionRevision) {
        var candidate = {
            dataEpoch: App.dataEpoch || 0,
            timelineEpoch: App.timelineEpoch || 0,
            absoluteReportDate: absoluteDate(date),
            projectionInstanceKey: projectionInstanceKey || "",
            projectionRevision: projectionRevision || ""
        };
        // The same logical selection reuses its owner. Network de-duplication
        // may therefore safely retain the first request callback while a
        // repeated click waits on the same Promise.
        if (App.detailsOwner
            && App.detailsOwner.dataEpoch === candidate.dataEpoch
            && App.detailsOwner.timelineEpoch === candidate.timelineEpoch
            && detailTuple(App.detailsOwner) === detailTuple(candidate)) {
            return App.detailsOwner;
        }
        App.selectionEpoch = (App.selectionEpoch || 0) + 1;
        candidate.selectionEpoch = App.selectionEpoch;
        App.detailsOwner = candidate;
        return candidate;
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
            detailTuple(owner)
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

    var requestSequences = App.requestSequences || {};
    var sharedPromises = App.sharedPromises || {};

    function beginLatest(channel, logicalKey) {
        requestSequences[channel] = (requestSequences[channel] || 0) + 1;
        return {
            channel: channel,
            logicalKey: String(logicalKey || ""),
            sequence: requestSequences[channel],
            dataEpoch: App.dataEpoch || 0
        };
    }

    function isCurrentRequest(token) {
        return !!token
            && token.dataEpoch === (App.dataEpoch || 0)
            && token.sequence === requestSequences[token.channel];
    }

    function share(channel, logicalKey, factory) {
        var key = [App.dataEpoch || 0, channel, logicalKey || ""].join("|");
        if (sharedPromises[key]) return sharedPromises[key];
        var promise;
        try {
            promise = Promise.resolve().then(factory);
        } catch (error) {
            promise = Promise.reject(error);
        }
        sharedPromises[key] = promise.finally(function () {
            if (sharedPromises[key] === sharedPromises[key]) delete sharedPromises[key];
        });
        return sharedPromises[key];
    }

    function bumpDataEpoch() {
        App.dataEpoch = (App.dataEpoch || 0) + 1;
        App.timelineEpoch = (App.timelineEpoch || 0) + 1;
        App.selectionEpoch = (App.selectionEpoch || 0) + 1;
        App.detailsOwner = null;
        App.timelineOwner = null;
        App.mutationOwner = null;
        App.mutationState = "idle";
        App.detailsInFlight = {};
        App.projectsCache = null;
        App.projectsLoading = false;
        App.projectsLoadPromise = null;
        App.statisticsAcceptedPayload = null;
        App.rulesLoadPromise = null;
        App.activePageRefreshPending = null;
        for (var key in sharedPromises) delete sharedPromises[key];
        for (var channel in requestSequences) requestSequences[channel] += 1;
        return App.dataEpoch;
    }

    App.dataEpoch = App.dataEpoch || 0;
    App.timelineEpoch = App.timelineEpoch || 0;
    App.selectionEpoch = App.selectionEpoch || 0;
    App.detailsOwner = App.detailsOwner || null;
    App.mutationEpoch = App.mutationEpoch || 0;
    App.mutationOwner = App.mutationOwner || null;
    App.mutationState = App.mutationState || "idle";
    App.MUTATION_STATES = Object.freeze([
        "idle", "pending", "unknown", "confirmed_success", "confirmed_failure"
    ]);
    App.requestCoordinator = {
        beginLatest: beginLatest,
        bumpDataEpoch: bumpDataEpoch,
        isCurrent: isCurrentRequest,
        share: share
    };
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
})();
