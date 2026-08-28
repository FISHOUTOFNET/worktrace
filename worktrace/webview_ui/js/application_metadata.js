// WorkTrace immutable application metadata presentation and bootstrap owner.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var loadPromise = null;
    var loaded = false;

    function releaseLabel(channel) {
        channel = String(channel || "").trim().toLowerCase();
        if (channel === "beta") return "测试版";
        if (channel === "stable" || channel === "release") return "";
        return channel;
    }

    function versionLabel(metadata) {
        metadata = metadata || {};
        var version = String(metadata.version || "").trim();
        if (!version) return "";
        var parts = ["v" + version];
        var channel = releaseLabel(metadata.release_channel);
        if (channel) parts.push(channel);
        return parts.join(" · ");
    }

    function render(metadata) {
        if (!metadata || typeof metadata !== "object") return false;
        var label = versionLabel(metadata);
        if (!label) return false;

        var sidebarVersion = document.getElementById("application-version-label");
        var settingsVersion = document.getElementById("settings-application-version");
        var settingsCreator = document.getElementById("settings-application-creator");

        if (sidebarVersion) sidebarVersion.textContent = label;
        if (settingsVersion) settingsVersion.textContent = label;
        if (settingsCreator) {
            var creator = String(metadata.creator || "").trim();
            settingsCreator.textContent = creator ? "Created By " + creator : "";
            settingsCreator.hidden = !creator;
        }
        loaded = true;
        return true;
    }

    function load() {
        if (loaded) return Promise.resolve(true);
        if (loadPromise) return loadPromise;
        loadPromise = Promise.resolve(App.bridge.getApplicationMetadata())
            .then(function (result) {
                if (!result || result.ok !== true) return false;
                return render(result.application);
            })
            .catch(function () {
                return false;
            })
            .then(function (result) {
                loadPromise = null;
                return result;
            });
        return loadPromise;
    }

    App.applicationMetadata = Object.freeze({
        load: load,
        render: render,
        versionLabel: versionLabel
    });
})();
