from __future__ import annotations

import runpy
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate_brand_icon.py"
SPEC_PATH = REPO_ROOT / "WorkTrace.spec"


def _generator_namespace() -> dict:
    return runpy.run_path(str(GENERATOR_PATH))


def test_brand_gradient_stays_close_to_shipping_accent() -> None:
    namespace = _generator_namespace()

    assert namespace["BRAND_GRADIENT_START"] == (40, 117, 173)
    assert namespace["BRAND_GRADIENT_END"] == (30, 101, 155)

    midpoint = tuple(
        round((start + end) / 2)
        for start, end in zip(
            namespace["BRAND_GRADIENT_START"],
            namespace["BRAND_GRADIENT_END"],
        )
    )
    ui_accent = (34, 109, 168)  # #226DA8
    assert max(abs(value - accent) for value, accent in zip(midpoint, ui_accent)) <= 5


def test_paused_icon_derivative_is_true_grayscale_and_preserves_alpha() -> None:
    namespace = _generator_namespace()
    image = Image.new("RGBA", (2, 1))
    image.putdata([(40, 117, 173, 255), (255, 255, 255, 96)])

    grayscale = namespace["_grayscale_image"](image)
    pixels = list(grayscale.getdata())

    assert all(red == green == blue for red, green, blue, _alpha in pixels)
    assert [pixel[3] for pixel in pixels] == [255, 96]


def test_spec_generates_and_bundles_paused_icon_beside_active_icon() -> None:
    spec = SPEC_PATH.read_text(encoding="utf-8")

    assert "paused_brand_icon = root / 'build' / 'brand' / 'worktrace-paused.ico'" in spec
    assert "icon_generator['generate_icon'](paused_brand_icon, grayscale=True)" in spec
    assert "(str(paused_brand_icon), 'worktrace/assets')" in spec
