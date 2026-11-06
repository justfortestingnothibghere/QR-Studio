"""Poster renderer. Everything is drawn from a theme manifest, so built-in and user themes use one code path.

Design space is 1024 x 1536. `scale` multiplies it (0.625 for previews, 2.0 for HD exports).
The clean (unwatermarked) image is only ever produced for paid exports, server side."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter

from .. import config
from ..payload import build_payload, id_line
from . import fonts, qrdraw

DW, DH = 1024, 1536


def _rgb(c: str, a: int = 255):
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), a)


def themes_dir() -> Path:
    return config.themes_dir()


def user_themes_dir() -> Path:
    p = config.data_dir() / "user_themes"
    p.mkdir(parents=True, exist_ok=True)
    return p


@lru_cache(maxsize=1)
def builtin_themes() -> dict:
    out = {}
    for f in sorted(themes_dir().glob("*.json")):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
            m["builtin"] = True
            out[m["id"]] = m
        except Exception:
            continue
    return out


def reload_builtin():
    builtin_themes.cache_clear()


@lru_cache(maxsize=24)
def _bg_cached(path: str, mtime: float, w: int, h: int) -> Image.Image:
    im = Image.open(path).convert("RGB")
    return im.resize((w, h), Image.LANCZOS)


def theme_bg(theme: dict, w: int, h: int) -> Image.Image:
    if theme.get("builtin"):
        path = themes_dir() / (theme["id"] + ".jpg")
    else:
        path = user_themes_dir() / str(theme["owner_id"]) / (theme["id"] + ".jpg")
    return _bg_cached(str(path), path.stat().st_mtime, w, h).copy()


# ---------- text helpers ----------
def _fit_font(key: str, text: str, size: float, maxw: float, scale: float):
    s = int(size * scale)
    mw = maxw * scale
    probe = ImageDraw.Draw(Image.new("L", (4, 4)))
    while s > 10:
        f = fonts.font(key, s)
        if probe.textlength(text, font=f) <= mw:
            return f
        s -= 2
    return fonts.font(key, 10)


def _glow(img: Image.Image, draw_fn, color, radius: float):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer), color)
    blur = layer.filter(ImageFilter.GaussianBlur(radius))
    img.alpha_composite(blur)
    img.alpha_composite(blur)


def _crown(d, x, y, s, col, w):
    pts = [(x - s, y), (x - s * .8, y - s * .9), (x - s * .4, y - s * .35), (x, y - s * 1.1),
           (x + s * .4, y - s * .35), (x + s * .8, y - s * .9), (x + s, y)]
    d.line(pts + [pts[0]], fill=col, width=w, joint="curve")
    d.line([(x - s * .9, y + s * .25), (x + s * .9, y + s * .25)], fill=col, width=w)


def _draw_texts(img: Image.Image, theme: dict, design: dict, scale: float):
    accent = _rgb(theme.get("accent", "#ffffff"))
    sources = {
        "name": design.get("name", ""),
        "title": design.get("title", ""),
        "tag": design.get("tag", ""),
        "idline": id_line(design),
    }
    for spec in theme.get("texts", []):
        text = sources.get(spec["key"], "")
        if not text:
            continue
        key = spec.get("font", "script")
        f = _fit_font(key, text, spec.get("size", 32), spec.get("maxw", 400), scale)
        x, y = spec["x"] * scale, spec["y"] * scale
        anchor = {"center": "m", "left": "l", "right": "r"}[spec.get("align", "center")] + spec.get("baseline", "m")
        col = _rgb(spec.get("color", "#ffffff"))
        if spec.get("glow"):
            _glow(img, lambda d, c: d.text((x, y), text, font=f, fill=c, anchor=anchor), accent, spec["glow"] * scale)
        d = ImageDraw.Draw(img)
        d.text((x, y), text, font=f, fill=col, anchor=anchor)
        w = d.textlength(text, font=f)
        if spec.get("rules"):
            x0, x1 = spec["rules"]
            lw = max(1, int(2 * scale))
            d.line([(x0 * scale, y), (x - w / 2 - 14 * scale, y)], fill=accent, width=lw)
            d.line([(x + w / 2 + 14 * scale, y), (x1 * scale, y)], fill=accent, width=lw)
        if spec.get("swoosh"):
            sy = y + spec["swoosh"] * scale
            pts = []
            for i in range(41):
                t = i / 40
                px = (x - 270 * scale) * (1 - t) ** 2 + x * 2 * t * (1 - t) + (x + 270 * scale) * t * t
                py = sy * (1 - t) ** 2 + (sy - 24 * scale) * 2 * t * (1 - t) + (sy + 4 * scale) * t * t
                pts.append((px, py))
            d.line(pts, fill=accent, width=max(2, int(5 * scale)), joint="curve")
        if spec.get("crown"):
            _crown(d, x, y - spec["crown"] * scale, 30 * scale, accent, max(2, int(3 * scale)))


# ---------- watermark ----------
def apply_watermark(img: Image.Image, text: str, user_tag: str = "") -> Image.Image:
    w, h = img.size
    diag = int(math.hypot(w, h)) + 40
    layer = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fsz = max(14, int(w * 0.052))
    f = fonts.font("display", fsz)
    step_y = int(fsz * 3.1)
    step_x = int(d.textlength(text, font=f) * 1.5)
    row = 0
    for y in range(-step_y, diag + step_y, step_y):
        shift = step_x // 2 if row % 2 else 0
        for x in range(-step_x, diag + step_x, step_x):
            d.text((x + shift, y), text, font=f, fill=(255, 255, 255, 92), stroke_width=max(1, fsz // 14),
                   stroke_fill=(0, 0, 0, 96))
        row += 1
    layer = layer.rotate(28, resample=Image.BICUBIC)
    ox, oy = (diag - w) // 2, (diag - h) // 2
    base = img.convert("RGBA")
    base.alpha_composite(layer.crop((ox, oy, ox + w, oy + h)))
    d2 = ImageDraw.Draw(base)
    small = fonts.font("mono", max(10, int(w * 0.022)))
    d2.text((w / 2, h - w * 0.03), ("qr studio · preview" + (" · " + user_tag if user_tag else "")), font=small,
            fill=(255, 255, 255, 200), anchor="mm", stroke_width=1, stroke_fill=(0, 0, 0, 160))
    return base.convert("RGB")


# ---------- main render ----------
def _decoy_seed(payload: str, tag: str, bump: int = 0) -> int:
    import hashlib
    return int(hashlib.sha256(("%s|%s|%s|%s" % (config.get("security.secret_key"), payload, tag, bump)).encode()).hexdigest()[:15], 16)


def _panel(theme: dict, design: dict, payload: str, scale: float, logo_img=None, decoy_tag=None):
    q = theme["qr"]
    pw, ph = max(40, int(q["w"] * scale)), max(40, int(q["h"] * scale))
    matrix = qrdraw.qr_matrix(payload)
    if decoy_tag is not None:
        # unpaid preview: scramble data + format bits (42% flips, ECC-H cannot recover). Verified unreadable by tests/decoy_check.py
        matrix = qrdraw.decoy_matrix(matrix, _decoy_seed(payload, decoy_tag))
    style = dict(design["style"])
    style["letter"] = ((design.get("name") or "Q").strip() or "Q")[0]
    return qrdraw.draw_panel(pw, ph, matrix, style, radius=int(q.get("r", 26) * scale), logo_img=logo_img), matrix


def render_poster(theme: dict, design: dict, payload: str, scale: float, watermark: bool,
                  logo_img: Optional[Image.Image] = None, user_tag: str = "") -> Image.Image:
    W, H = int(DW * scale), int(DH * scale)
    img = theme_bg(theme, W, H).convert("RGBA")
    q = theme["qr"]
    panel, _ = _panel(theme, design, payload, scale, logo_img, decoy_tag=(user_tag or "guest") if watermark else None)
    x, y = int(q["x"] * scale), int(q["y"] * scale)
    accent = _rgb(theme.get("accent", "#4da3ff"))
    gl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(gl).rounded_rectangle((x - 4, y - 4, x + panel.width + 4, y + panel.height + 4),
                                         radius=int(q.get("r", 26) * scale), fill=accent[:3] + (190,))
    img.alpha_composite(gl.filter(ImageFilter.GaussianBlur(max(4, 22 * scale))))
    fr = theme.get("frame")
    if theme.get("draw_frame") and fr:
        box = (fr["x"] * scale, fr["y"] * scale, (fr["x"] + fr["w"]) * scale, (fr["y"] + fr["h"]) * scale)
        fl = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(fl).rounded_rectangle(box, radius=fr["r"] * scale, fill=(4, 2, 8, 232), outline=accent, width=max(2, int(3 * scale)))
        img.alpha_composite(fl)
    img.alpha_composite(panel, (x, y))
    _draw_texts(img, theme, design, scale)
    out = img.convert("RGB")
    if watermark:
        out = apply_watermark(out, config.get("render.watermark_text", "TEAMDEV · PREVIEW"), user_tag)
    return out


def scan_check(theme: dict, design: dict, payload: str, logo_img=None) -> bool:
    panel, _ = _panel(theme, design, payload, 1.0, logo_img)
    return qrdraw.decode_ok(panel, payload, design["style"].get("ink", "#000000"))


def to_bytes(img: Image.Image, fmt: str, quality: int = 90, dpi: int = 300) -> bytes:
    buf = BytesIO()
    if fmt == "png":
        img.save(buf, "PNG", compress_level=6, dpi=(dpi, dpi))
    elif fmt == "jpg":
        img.save(buf, "JPEG", quality=quality, optimize=True, dpi=(dpi, dpi))
    elif fmt == "pdf":
        img.save(buf, "PDF", resolution=float(dpi), quality=95)
    else:
        raise ValueError(fmt)
    return buf.getvalue()
