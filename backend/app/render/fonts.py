"""Font loading. Font keys map to files in backend/assets/fonts (override in backend/config.json -> render.fonts)."""
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from .. import config

FONT_DIR = config.BASE / "assets" / "fonts"
DEFAULTS = {
    "script": "Poppins-BoldItalic.ttf",
    "display": "Poppins-Bold.ttf",
    "body": "Poppins-Medium.ttf",
    "mono": "DejaVuSansMono-Bold.ttf",
    "kanji": "KanjiBlack-subset.otf",
}


def _path(key: str) -> Path:
    override = (config.get("render.fonts", {}) or {}).get(key)
    name = override or DEFAULTS.get(key, DEFAULTS["body"])
    p = Path(name)
    return p if p.is_absolute() else FONT_DIR / name


@lru_cache(maxsize=256)
def font(key: str, size: int) -> ImageFont.FreeTypeFont:
    size = max(6, int(size))
    try:
        return ImageFont.truetype(str(_path(key)), size)
    except OSError:
        return ImageFont.truetype(str(FONT_DIR / DEFAULTS["body"]), size)
