from __future__ import annotations

from worktrace import PRODUCT_DISPLAY_NAME
from worktrace import webview_main


def test_navigation_brand_uses_product_display_name_and_hides_wide_mark() -> None:
    script = webview_main._navigation_brand_script()

    assert PRODUCT_DISPLAY_NAME in script
    assert "brand-mark" in script
    assert "max-width: 959px" in script
    assert "compactSidebar.matches ? '' : 'none'" in script


def test_navigation_brand_projection_is_best_effort() -> None:
    calls: list[str] = []

    class Window:
        def evaluate_js(self, script: str) -> None:
            calls.append(script)

    webview_main._apply_navigation_brand(Window())

    assert calls == [webview_main._navigation_brand_script()]
