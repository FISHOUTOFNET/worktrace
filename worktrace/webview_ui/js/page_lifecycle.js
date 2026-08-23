// WorkTrace frontend — stateless page lifecycle capability registry.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var PAGE_NAMES = Object.freeze([
        "overview", "timeline", "statistics", "rules", "settings"
    ]);

    function capability(name) {
        var owner = App[String(name || "")];
        return owner && typeof owner === "object" ? owner : null;
    }

    function forEach(method, args) {
        PAGE_NAMES.forEach(function (name) {
            var owner = capability(name);
            if (owner && typeof owner[method] === "function") {
                owner[method].apply(owner, args || []);
            }
        });
    }

    App.pageLifecycle = Object.freeze({
        names: PAGE_NAMES,
        capability: capability,
        forEach: forEach,
        bindEvents: function () { forEach("bindEvents"); },
        onPageLeft: function (name, options) {
            var owner = capability(name);
            if (owner && typeof owner.onPageLeft === "function") owner.onPageLeft(options || {});
        },
        resetGeneration: function () { forEach("resetGeneration"); }
    });
})();
