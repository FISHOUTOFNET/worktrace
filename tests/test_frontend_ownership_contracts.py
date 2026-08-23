from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "worktrace" / "webview_ui" / "js"
INIT = JS_DIR / "init_fd_work_v5.js"
RULES = JS_DIR / "rules.js"


def shipping_js():
    return {path.name: path.read_text(encoding="utf-8") for path in JS_DIR.glob("*.js")}


def between(text, start, end):
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def test_obsolete_reconcile_and_project_cache_aliases_are_tombstoned():
    sources = shipping_js()
    forbidden = (
        "RECONCILE_INTERVAL_MS",
        "lastReconcileAtEpochMs",
        "reconcileInFlight",
        "projectsCache",
        "editingProjectsCache",
        "filterProjectsCache",
        "projectsLoading",
        "projectsLoadPromise",
        "listProjectsForTimeline",
        "App.loadProjects",
        "App.refreshProjectCatalogs",
        "refreshSharedProjectCatalog",
    )
    for filename, source in sources.items():
        for token in forbidden:
            assert token not in source, f"{filename} resurrects obsolete frontend ownership token {token}"


def test_project_catalog_is_the_canonical_frontend_directory_owner():
    catalog = (JS_DIR / "project_catalog.js").read_text(encoding="utf-8")
    init = INIT.read_text(encoding="utf-8")
    timeline = (JS_DIR / "timeline.js").read_text(encoding="utf-8")
    assert "var editingProjects = null;" in catalog
    assert "var filterProjects = null;" in catalog
    assert "return App.bridge.listProjectCatalog();" in catalog
    assert 'listProjectCatalog: fixedBridgeMethod("list_project_catalog")' in init
    assert "App.projectCatalog.load()" in timeline
    assert "App.projectCatalog.getEditing()" in timeline


def test_switch_page_delegates_data_refresh_without_page_fetch_knowledge():
    init = INIT.read_text(encoding="utf-8")
    switch = between(init, "    function switchPage(pageId) {", "    App.switchPage = switchPage;")
    assert "pageNeedsRefresh(pageId)" in switch
    assert "refreshActivePage(" in switch
    assert "pageRefreshOptions(pageId, { navigation: true })" in switch
    assert "refreshCurrentPageData(" not in switch
    for direct_fetch in (
        "loadTimelineReport(",
        "loadStatisticsExportSummary(",
        "loadProjectRules(",
        "loadSettingsPrivacyStatus(",
    ):
        assert direct_fetch not in switch


def test_revision_check_owns_periodic_business_refresh():
    init = INIT.read_text(encoding="utf-8")
    revision = between(init, "    function runRevisionCheck() {", "    App.runRevisionCheck = runRevisionCheck;")
    heartbeat = between(init, "    function startHeartbeat() {", "    App.startHeartbeat = startHeartbeat;")
    assert "changedGenerationKeys(" in revision
    assert "markPagesDirtyForGenerationChanges(changedGenerations);" in revision
    assert "dispatchAutomaticRefresh(changedGenerations, previousRuntime, acceptedRuntime);" in revision
    assert "App.liveClockContractRefreshRequested" in revision
    assert "runRevisionCheck();" in heartbeat
    for direct_fetch in (
        "getOverview(",
        "loadTimelineReport(",
        "loadStatisticsExportSummary(",
        "loadProjectRules(",
        "loadSettingsPrivacyStatus(",
    ):
        assert direct_fetch not in heartbeat


def test_active_page_capabilities_keep_fetches_out_of_init_dispatch():
    init = INIT.read_text(encoding="utf-8")
    dispatch = between(
        init,
        "    function refreshActivePage(acceptedState, options, expectedPage) {",
        "    App.refreshActivePage = refreshActivePage;",
    )
    assert "pageCapability(page)" in dispatch
    assert "capability.onPageEntered" in dispatch
    assert "capability.onRefreshRequested" in dispatch
    assert "method.call(capability, options" in dispatch
    for direct_fetch in (
        "refreshOverview(",
        "loadTimelineReport(",
        "loadStatisticsExportSummary(",
        "loadProjectRules(",
        "loadSettingsPrivacyStatus(",
    ):
        assert direct_fetch not in dispatch

    for owner_name in ("overview", "timeline", "statistics", "rules", "settings"):
        owner = (JS_DIR / f"{owner_name}.js").read_text(encoding="utf-8")
        assert "onRefreshRequested" in owner


def test_rules_read_does_not_invalidate_catalog_but_write_reload_does():
    rules = RULES.read_text(encoding="utf-8")
    load_block = between(rules, "    function loadProjectRules(options) {", "    App.loadProjectRules = loadProjectRules;")
    reload_block = between(rules, "    App.reloadProjectRules = function () {", "    function sortProjectsForRulesHome")
    assert "projectCatalog.invalidate" not in load_block
    assert "App.projectCatalog.invalidate();" in reload_block
    panel = (JS_DIR / "rules_create_panel_v5.js").read_text(encoding="utf-8")
    assert "if (App.reloadProjectRules) return App.reloadProjectRules();" in panel
