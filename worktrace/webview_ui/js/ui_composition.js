// WorkTrace frontend composition root for cross-surface capability notifications.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function applicationReleaseLabel(channel) {
        channel = String(channel || "").trim().toLowerCase();
        if (channel === "beta") return "测试版";
        if (channel === "stable" || channel === "release") return "";
        return channel;
    }

    function applicationVersionLabel(metadata) {
        metadata = metadata || {};
        var version = String(metadata.version || "").trim();
        if (!version) return "";
        var parts = ["v" + version];
        var releaseLabel = applicationReleaseLabel(metadata.release_channel);
        if (releaseLabel) parts.push(releaseLabel);
        return parts.join(" · ");
    }

    function ensureApplicationMetadataStyles() {
        if (document.getElementById("application-metadata-styles")) return;
        var style = document.createElement("style");
        style.id = "application-metadata-styles";
        style.textContent = [
            ".application-version-label{margin-top:7px;color:var(--color-text-secondary);font-size:var(--font-size-xs);line-height:1.25;text-align:center;white-space:nowrap;}",
            ".settings-about{margin-top:18px;padding-top:12px;border-top:1px solid var(--color-border);}",
            ".settings-about h2{margin:0 0 6px;font-size:var(--font-size-lg);font-weight:650;}",
            ".settings-about-product{display:block;font-weight:650;}",
            ".settings-about-meta,.settings-about-creator{display:block;margin-top:2px;color:var(--color-text-secondary);font-size:var(--font-size-xs);}",
            "@media (max-width:959px){.application-version-label{display:none;}}"
        ].join("");
        document.head.appendChild(style);
    }

    function ensureApplicationVersionProjection() {
        var footer = document.querySelector(".nav-footer");
        if (!footer) return null;
        var target = document.getElementById("application-version-label");
        if (target) return target;
        target = document.createElement("div");
        target.id = "application-version-label";
        target.className = "application-version-label";
        footer.appendChild(target);
        return target;
    }

    function ensureApplicationAboutProjection() {
        var content = document.querySelector(".settings-content");
        if (!content) return null;
        var target = document.getElementById("settings-about-application");
        if (target) return target;

        target = document.createElement("section");
        target.id = "settings-about-application";
        target.className = "settings-about";
        target.setAttribute("aria-labelledby", "settings-about-application-title");

        var title = document.createElement("h2");
        title.id = "settings-about-application-title";
        title.textContent = "关于有迹";
        target.appendChild(title);

        var product = document.createElement("span");
        product.className = "settings-about-product";
        product.textContent = "有迹 · Trace";
        target.appendChild(product);

        var version = document.createElement("span");
        version.className = "settings-about-meta";
        version.setAttribute("data-application-version", "settings");
        target.appendChild(version);

        var creator = document.createElement("span");
        creator.className = "settings-about-creator";
        creator.setAttribute("data-application-creator", "settings");
        target.appendChild(creator);

        content.appendChild(target);
        return target;
    }

    function renderApplicationMetadata(metadata) {
        if (!metadata || typeof metadata !== "object") return false;
        var versionLabel = applicationVersionLabel(metadata);
        if (!versionLabel) return false;
        ensureApplicationMetadataStyles();

        var sidebarVersion = ensureApplicationVersionProjection();
        if (sidebarVersion) sidebarVersion.textContent = versionLabel;

        var about = ensureApplicationAboutProjection();
        if (about) {
            var settingsVersion = about.querySelector('[data-application-version="settings"]');
            var settingsCreator = about.querySelector('[data-application-creator="settings"]');
            if (settingsVersion) settingsVersion.textContent = versionLabel;
            if (settingsCreator) {
                var creator = String(metadata.creator || "").trim();
                settingsCreator.textContent = creator ? "Created by " + creator : "";
                settingsCreator.hidden = !creator;
            }
        }
        return true;
    }

    function syncFDWorkConsumers(status) {
        if (App.settings && typeof App.settings.onFDWorkStatusChanged === "function") {
            App.settings.onFDWorkStatusChanged(status || App.fdWorkStatus || null);
        }
        if (App.timelineFDWork && typeof App.timelineFDWork.onStatusChanged === "function") {
            App.timelineFDWork.onStatusChanged(status || App.fdWorkStatus || null);
        }
        if (typeof App.updateFDWorkEntryButton === "function") {
            App.updateFDWorkEntryButton();
        }
        if (App.projectIdentity && typeof App.projectIdentity.syncStatus === "function") {
            App.projectIdentity.syncStatus();
        }
    }
    App.syncFDWorkConsumers = syncFDWorkConsumers;

    function nonNegativeInt(value) {
        var parsed = parseInt(value, 10);
        return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
    }

    function runtimeGeneration(runtime, name) {
        var generations = runtime && runtime.generations;
        return nonNegativeInt(generations && generations[name]);
    }

    function handleAcceptedRuntimeTransition(previous, accepted, source) {
        var current = App.liveRuntimeStore && App.liveRuntimeStore.get
            ? App.liveRuntimeStore.get()
            : null;
        if (!accepted || !previous || !current) return accepted;

        var structureChanged = String(previous.structureRevision || "")
            !== String(current.structureRevision || "");
        var liveChanged = String(previous.liveRevision || "")
            !== String(current.liveRevision || "");
        var reportStructureChanged = runtimeGeneration(previous, "report_structure")
            !== runtimeGeneration(current, "report_structure");
        var classificationChanged = runtimeGeneration(previous, "classification_catalog")
            !== runtimeGeneration(current, "classification_catalog");
        var settingsChanged = runtimeGeneration(previous, "settings")
            !== runtimeGeneration(current, "settings");
        var rulesDataChanged = structureChanged || classificationChanged;
        var page = String(App.currentPage || "");

        // Project-rule presentation includes activity-backed last_used_at, so it
        // depends on report structure as well as on the classification catalog.
        if (rulesDataChanged && App.rules && typeof App.rules.onDataChanged === "function") {
            App.rules.onDataChanged({
                source: source,
                structureChanged: structureChanged,
                classificationChanged: classificationChanged
            });
        }
        if (settingsChanged && App.settings && typeof App.settings.onDataChanged === "function") {
            App.settings.onDataChanged({
                source: source,
                settingsChanged: true
            });
        }

        // A page payload is itself the authoritative refresh for the active page.
        // Cross-surface invalidation still applies, but current-page reconcile is
        // reserved for heartbeat refresh-state transitions to avoid double fetches.
        if (source !== "refresh-state") return accepted;

        if (page === "timeline" && App.timeline
            && typeof App.timeline.onRuntimeTransition === "function") {
            App.timeline.onRuntimeTransition({
                source: source,
                structureChanged: structureChanged,
                liveChanged: liveChanged
            });
        }

        if (page === "overview" && App.overview
            && typeof App.overview.onRuntimeTransition === "function") {
            App.overview.onRuntimeTransition({
                source: source,
                structureChanged: structureChanged,
                liveChanged: liveChanged
            });
        }

        if (page === "statistics" && App.statistics
            && typeof App.statistics.onRuntimeTransition === "function") {
            App.statistics.onRuntimeTransition({
                source: source,
                structureChanged: structureChanged,
                liveChanged: liveChanged,
                reportStructureChanged: reportStructureChanged
            });
        }

        return accepted;
    }

    function wrapRuntimeAcceptance(methodName, source) {
        var base = App[methodName];
        if (typeof base !== "function") return;
        App[methodName] = function () {
            var previous = App.liveRuntimeStore && App.liveRuntimeStore.get
                ? App.liveRuntimeStore.get()
                : null;
            var accepted = base.apply(App, arguments);
            return handleAcceptedRuntimeTransition(previous, accepted, source);
        };
    }

    wrapRuntimeAcceptance("acceptRefreshStateRuntime", "refresh-state");
    wrapRuntimeAcceptance("acceptPagePayloadRuntime", "page-payload");

    var baseShowStatus = App.showStatus;
    if (typeof baseShowStatus === "function") {
        App.showStatus = function (statusResult) {
            if (!statusResult) return;
            if (statusResult.application) renderApplicationMetadata(statusResult.application);
            var signature = JSON.stringify([
                String(statusResult.status || ""),
                statusResult.paused === true,
                String(statusResult.display || "")
            ]);
            if (App.lastStatusRenderSignature === signature) return;
            App.lastStatusRenderSignature = signature;
            return baseShowStatus.apply(App, arguments);
        };
    }

    if (App.fdWork && typeof App.fdWork.bindStatusHost === "function") {
        App.fdWork.bindStatusHost({ onStatusChanged: syncFDWorkConsumers });
    }
    if (App.fdWorkStatus) syncFDWorkConsumers(App.fdWorkStatus);
})();
