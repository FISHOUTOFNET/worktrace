from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "worktrace" / "webview_ui" / "js"


def test_settings_uses_single_client_generation_reset():
    source = (JS / "settings.js").read_text(encoding="utf-8")
    assert "resetFrontendAfterLocalDataReplacement" not in source
    assert source.count('App.resetClientGeneration("database_replacement")') == 2
    assert "database_clear" not in source
    assert "secure_import" not in source
    assert "clear_all_local_data" not in source


def test_shipping_js_has_no_retired_replacement_reset_reason():
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(JS.glob("*.js"))
    )
    assert 'resetClientGeneration("secure_import")' not in source
    assert 'resetClientGeneration("clear_all_local_data")' not in source
    assert 'resetClientGeneration("database_clear")' not in source


def test_client_generation_reset_delegates_page_state_to_fixed_owners():
    source = (JS / "init_fd_work_v5.js").read_text(encoding="utf-8")
    start = source.index("function resetClientGeneration(reason)")
    end = source.index("App.resetClientGeneration = resetClientGeneration", start)
    body = source[start:end]
    for required in (
        "bumpDataEpoch()",
        "App.pageLifecycle.resetGeneration()",
        "App.fdWork.resetGeneration()",
        "lastRefreshState = null",
        "activePageRefreshPending = null",
        "liveRuntimeStore.reset()",
        "_monotonicRenderState = {}",
    ):
        assert required in body
    for retired_direct_hook in (
        "App.overview.resetGeneration()",
        "App.timeline.resetGeneration()",
        "App.statistics.resetGeneration()",
        "App.rules.resetGeneration()",
        "App.settings.resetGeneration()",
    ):
        assert retired_direct_hook not in body
    for page_private_field in (
        "selectedProjectionInstanceKey",
        "detailsOwner",
        "mutationOwner",
        "projectsCache",
        "rulesLoadPromise",
        "statisticsDraftSelection",
        "timelineAutosaveQueued",
    ):
        assert page_private_field not in body


def test_first_run_notice_failure_remains_retryable():
    source = (JS / "settings.js").read_text(encoding="utf-8")
    start = source.index("function loadFirstRunNotice(")
    end = source.index("App.loadFirstRunNotice = loadFirstRunNotice", start)
    body = source[start:end]
    failure_check = body.index("if (!result || result.ok === false)")
    loaded_assignment = body.index("App.firstRunNoticeLoaded = true")
    assert failure_check < loaded_assignment
