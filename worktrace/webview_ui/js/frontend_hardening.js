// Cross-module async coordination that must load after init.js.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    var rawLoadProjects = App.loadProjects;
    if (typeof rawLoadProjects === "function") {
        App.loadProjects = function () {
            var promise = rawLoadProjects.apply(App, arguments);
            if (promise && typeof promise.then === "function") {
                var tracked = Promise.resolve(promise).finally(function () {
                    if (App.projectsLoadPromise === tracked) {
                        App.projectsLoadPromise = null;
                    }
                });
                App.projectsLoadPromise = tracked;
                return tracked;
            }
            return Promise.resolve(promise);
        };
    }

    var rawInvalidateProjectCatalog = App.invalidateProjectCatalog;
    if (typeof rawInvalidateProjectCatalog === "function") {
        App.invalidateProjectCatalog = function () {
            App.projectsCache = null;
            App.projectsLoading = false;
            App.projectsLoadPromise = null;
            if (typeof App.loadProjects === "function") {
                return App.loadProjects();
            }
            return rawInvalidateProjectCatalog.apply(App, arguments);
        };
    }

    function closestTimelineItem(target) {
        while (target && target !== document) {
            if (target.classList && target.classList.contains("timeline-item")) {
                return target;
            }
            target = target.parentElement;
        }
        return null;
    }

    var sessionList = document.getElementById("timeline-sessions-list");
    if (sessionList) {
        sessionList.addEventListener("click", function (event) {
            if (!App.projectsLoading || !App.projectsLoadPromise) return;
            var item = closestTimelineItem(event.target);
            if (!item) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            var epoch = App.dataEpoch || 0;
            App.projectsLoadPromise.then(function () {
                if (epoch !== (App.dataEpoch || 0)) return;
                if (document.body.contains(item)) item.click();
            });
        }, true);
    }
})();
