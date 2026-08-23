"""有迹 application package."""

from .version import __version__

PRODUCT_NAME = "有迹"
PRODUCT_NAME_EN = "Trace"
PRODUCT_DISPLAY_NAME = f"{PRODUCT_NAME} · {PRODUCT_NAME_EN}"

__all__ = ["PRODUCT_DISPLAY_NAME", "PRODUCT_NAME", "PRODUCT_NAME_EN", "__version__"]
