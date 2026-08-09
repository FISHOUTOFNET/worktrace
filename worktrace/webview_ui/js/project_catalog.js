// WorkTrace shared frontend project catalog.
// Owns catalog state only; page modules decide how to render their projections.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var editingProjects = null;
    var filterProjects = null;
    var loadPromise = null;
    var generation = 0;

    function snapshot() {
        return {
            editingProjects: editingProjects || [],
            filterProjects: filterProjects || []
        };
    }

    function publishLegacyProjection() {
        // Temporary aliases for consumers being migrated in this refactor.
        App.editingProjectsCache = editingProjects;
        App.filterProjectsCache = filterProjects;
        App.projectsCache = editingProjects;
        App.projectsLoading = !!loadPromise;
        App.projectsLoadPromise = loadPromise;
    }

    function accept(result, requestGeneration) {
        if (requestGeneration !== generation || !result || result.ok === false) return null;
        editingProjects = Array.isArray(result.editing_projects) ? result.editing_projects : [];
        filterProjects = Array.isArray(result.filter_projects) ? result.filter_projects : [];
        publishLegacyProjection();
        return snapshot();
    }

    function load() {
        if (editingProjects && filterProjects) return Promise.resolve(snapshot());
        if (loadPromise) return loadPromise;
        var requestGeneration = generation;
        loadPromise = App.bridge.listProjectsForTimeline().then(function (result) {
            return accept(result, requestGeneration);
        }).catch(function () {
            return null;
        }).finally(function () {
            if (requestGeneration === generation) loadPromise = null;
            publishLegacyProjection();
        });
        publishLegacyProjection();
        return loadPromise;
    }

    function invalidate() {
        generation += 1;
        editingProjects = null;
        filterProjects = null;
        loadPromise = null;
        publishLegacyProjection();
    }

    function resetGeneration() {
        invalidate();
    }

    App.projectCatalog = Object.freeze({
        load: load,
        invalidate: invalidate,
        resetGeneration: resetGeneration,
        getEditing: function () { return (editingProjects || []).slice(); },
        getFilter: function () { return (filterProjects || []).slice(); }
    });

    // Compatibility boundary while Timeline/Statistics callers are migrated.
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
