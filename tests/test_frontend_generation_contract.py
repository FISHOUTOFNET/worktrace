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


def test_client_generation_reset_clears_all_runtime_owners():
    source = (JS / "init.js").read_text(encoding="utf-8")
    start = source.index("function resetClientGeneration(reason)")
    end = source.index("App.resetClientGeneration = resetClientGeneration", start)
    body = source[start:end]
    for required in (
        "bumpDataEpoch()",
        "selectedProjectionInstanceKey = null",
        "detailsOwner = null",
        "mutationOwner = null",
        "projectsCache = null",
        "lastRefreshState = null",
        "activePageRefreshPending = null",
        "liveRuntimeStore.reset()",
        "_monotonicRenderState = {}",
    ):
        assert required in body


def test_first_run_notice_failure_remains_retryable():
    source = (JS / "settings.js").read_text(encoding="utf-8")
    start = source.index("function loadFirstRunNotice()")
    end = source.index("App.loadFirstRunNotice = loadFirstRunNotice", start)
    body = source[start:end]
    failure_check = body.index("if (!result || result.ok === false)")
    loaded_assignment = body.index("App.firstRunNoticeLoaded = true")
    assert failure_check < loaded_assignment
