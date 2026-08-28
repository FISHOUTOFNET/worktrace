// WorkTrace compatibility asset.
// Statistics live projection is owned exclusively by statistics.js.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    if (!App.statistics || !App.statisticsLiveProjection) {
        if (window.console && console.error) {
            console.error("statistics live projection owner missing");
        }
    }
})();
