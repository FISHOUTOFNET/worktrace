// WorkTrace shared frontend project catalog.
// Owns catalog state only; page modules decide how to render their projections.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var editingProjects = null;
    var filterProjects = null;
    var loadPromise = null;
    var generation = 0;
    var acceptedDataEpoch = null;

    function currentDataEpoch() {
        return Number.isInteger(App.dataEpoch) ? App.dataEpoch : 0;
    }

    function snapshot() {
        return {
            editingProjects: editingProjects || [],
            filterProjects: filterProjects || []
        };
    }

    function publishLegacyProjection() {
        // Temporary aliases only for the legacy Timeline renderer. The catalog
        // remains the sole state owner and no feature module writes these.
        App.editingProjectsCache = editingProjects;
        App.filterProjectsCache = filterProjects;
        App.projectsCache = editingProjects;
        App.projectsLoading = !!loadPromise;
        App.projectsLoadPromise = loadPromise;
    }

    function invalidate() {
        generation += 1;
        acceptedDataEpoch = null;
        editingProjects = null;
        filterProjects = null;
        loadPromise = null;
        publishLegacyProjection();
    }

    function rejectStaleEpoch() {
        if (acceptedDataEpoch !== null && acceptedDataEpoch !== currentDataEpoch()) {
            invalidate();
        }
    }

    function accept(result, requestGeneration, requestDataEpoch) {
        if (requestGeneration !== generation
                || requestDataEpoch !== currentDataEpoch()
                || !result
                || result.ok === false) return null;
        editingProjects = Array.isArray(result.editing_projects) ? result.editing_projects : [];
        filterProjects = Array.isArray(result.filter_projects) ? result.filter_projects : [];
        acceptedDataEpoch = requestDataEpoch;
        publishLegacyProjection();
        return snapshot();
    }

    function catalogRequest() {
        if (!App.bridge) return Promise.reject(new Error("project_catalog_bridge_unavailable"));
        if (typeof App.bridge.listProjectCatalog === "function") {
            return App.bridge.listProjectCatalog();
        }
        return App.bridge.listProjectsForTimeline();
    }

    function load() {
        rejectStaleEpoch();
        if (editingProjects && filterProjects) return Promise.resolve(snapshot());
        if (loadPromise) return loadPromise;
        var requestGeneration = generation;
        var requestDataEpoch = currentDataEpoch();
        loadPromise = catalogRequest().then(function (result) {
            return accept(result, requestGeneration, requestDataEpoch);
        }).catch(function () {
            return null;
        }).finally(function () {
            if (requestGeneration === generation) loadPromise = null;
            publishLegacyProjection();
        });
        publishLegacyProjection();
        return loadPromise;
    }

    function resetGeneration() {
        invalidate();
    }

    App.projectCatalog = Object.freeze({
        load: load,
        invalidate: invalidate,
        resetGeneration: resetGeneration,
        getEditing: function () { rejectStaleEpoch(); return (editingProjects || []).slice(); },
        getFilter: function () { rejectStaleEpoch(); return (filterProjects || []).slice(); }
    });

    // Compatibility boundary while the large Timeline renderer is migrated.
    App.loadProjects = function () {
        return load().then(function (catalog) {
            return catalog ? catalog.editingProjects : null;
        });
    };
    App.refreshProjectCatalogs = function () {
        invalidate();
        return App.loadProjects();
    };
})();
