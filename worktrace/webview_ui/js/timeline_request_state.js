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
            && owner.timelineEpoch === (App.timelineEpoch || 0)
            && owner.selectionEpoch === (App.selectionEpoch || 0)
            && owner.absoluteReportDate === absoluteDate(App.timelineDate)
            && owner.projectionInstanceKey === App.selectedProjectionInstanceKey
            && owner.projectionRevision === (App.selectedProjectionRevision || "");
    }

    function detailRequestKey(owner) {
        return [
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
        if (App.mutationOwner && App.mutationOwner.inFlight) {
            return App.mutationOwner.intentKey === intentKey ? App.mutationOwner : null;
        }
        App.mutationEpoch = (App.mutationEpoch || 0) + 1;
        App.mutationOwner = {
            mutationEpoch: App.mutationEpoch,
            method: method || "",
            absoluteReportDate: absoluteDate(date),
            projectionInstanceKey: projectionInstanceKey || "",
            projectionRevision: projectionRevision || "",
            intentKey: intentKey,
            requestId: newRequestId(),
            inFlight: true
        };
        return App.mutationOwner;
    }

    function isCurrentMutationOwner(owner) {
        return !!owner && App.mutationOwner === owner && owner.inFlight === true;
    }

    function releaseMutationOwner(owner) {
        if (isCurrentMutationOwner(owner)) {
            owner.inFlight = false;
            App.mutationOwner = null;
        }
    }

    App.timelineEpoch = App.timelineEpoch || 0;
    App.selectionEpoch = App.selectionEpoch || 0;
    App.detailsOwner = App.detailsOwner || null;
    App.mutationEpoch = App.mutationEpoch || 0;
    App.mutationOwner = App.mutationOwner || null;
    App.timelineRequestState = {
        absoluteDate: absoluteDate,
        detailRequestKey: detailRequestKey,
        isCurrentDetailsOwner: isCurrentDetailsOwner,
        isCurrentMutationOwner: isCurrentMutationOwner,
        mutationIntentKey: mutationIntentKey,
        newRequestId: newRequestId,
        nextMutationOwner: nextMutationOwner,
        nextSelectionOwner: nextSelectionOwner,
        nextTimelineOwner: nextTimelineOwner,
        releaseMutationOwner: releaseMutationOwner
    };
})();
