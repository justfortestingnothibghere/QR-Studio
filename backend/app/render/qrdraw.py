"""QR matrix + styled drawing (square / dots / rounded) with optional centre logo."""
from __future__ import annotations

from io import BytesIO
from typing import List, Optional

import numpy as np
from PIL import Image, ImageDraw

from . import fonts

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

try:
    import segno  # optional fallback
except Exception:  # pragma: no cover
    segno = None


def qr_matrix(payload: str) -> List[List[bool]]:
    """Error-correction level H. Returns n x n booleans, True = dark, no quiet zone."""
    if cv2 is not None and hasattr(cv2, "QRCodeEncoder_create"):
        p = cv2.QRCodeEncoder_Params()
        p.correction_level = cv2.QRCodeEncoder_CORRECT_LEVEL_H
        enc = cv2.QRCodeEncoder_create(p)
        arr = enc.encode(payload)
        if arr is None or arr.size == 0:
            raise ValueError("encode failed")
        dark = arr < 128
        ys, xs = np.where(dark)
        sub = dark[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        side = sub.shape[0]
        run = 0
        while run < sub.shape[1] and sub[0, run]:
            run += 1
        mod = max(1, run // 7)
        n = side // mod
        if mod > 1:
            sub = sub[::mod, ::mod][:n, :n]
        return sub.tolist()
    if segno is not None:  # pragma: no cover
        q = segno.make(payload, error="h", micro=False, boost_error=False)
        return [[bool(v) for v in row] for row in q.matrix]
    raise RuntimeError("Install opencv-python-headless (or segno) for QR encoding")


def _hex(c: str, a: int = 255):
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), a)


def _in_finder(x, y, n):
    return (x < 7 and y < 7) or (x >= n - 7 and y < 7) or (x < 7 and y >= n - 7)


def logo_hole(n: int, logo_kind: str) -> int:
    return 0 if logo_kind == "none" else max(5, round(n * 0.2))


def draw_panel(w: int, h: int, matrix, style: dict, radius: int, logo_img: Optional[Image.Image] = None,
               ss: int = 3, panel_color: str = "#ffffff", pad_frac: float = 0.07) -> Image.Image:
    """Return an RGBA panel (white rounded card + styled QR) of size w x h (supersampled then reduced)."""
    W, H = w * ss, h * ss
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=radius * ss, fill=_hex(panel_color))
    n = len(matrix)
    ink = _hex(style.get("ink", "#0b0b10"))
    dot = style.get("dot", "dot")
    logo_kind = style.get("logo", "none")
    pad = int(min(W, H) * pad_frac)
    size = min(W, H) - 2 * pad
    m = size / n
    ox = (W - size) / 2
    oy = (H - size) / 2
    hs = logo_hole(n, logo_kind)
    lo = (n - hs) // 2

    def finder(fx, fy):
        x0 = ox + fx * m
        y0 = oy + fy * m
        rad = 0 if dot == "square" else 2.4 * m
        d.rounded_rectangle((x0, y0, x0 + 7 * m - 1, y0 + 7 * m - 1), radius=rad, outline=ink, width=max(1, int(round(m))))
        ix, iy = ox + (fx + 2) * m, oy + (fy + 2) * m
        d.rounded_rectangle((ix, iy, ix + 3 * m, iy + 3 * m), radius=(0 if dot == "square" else m), fill=ink)

    finder(0, 0)
    finder(n - 7, 0)
    finder(0, n - 7)
    for y in range(n):
        row = matrix[y]
        for x in range(n):
            if not row[x] or _in_finder(x, y, n):
                continue
            if hs and lo <= x < lo + hs and lo <= y < lo + hs:
                continue
            px, py = ox + x * m, oy + y * m
            if dot == "dot":
                d.ellipse((px + m * 0.03, py + m * 0.03, px + m * 0.97, py + m * 0.97), fill=ink)
            elif dot == "round":
                d.rounded_rectangle((px + m * 0.04, py + m * 0.04, px + m * 0.96, py + m * 0.96), radius=m * 0.32, fill=ink)
            else:
                d.rectangle((px - 0.4, py - 0.4, px + m + 0.4, py + m + 0.4), fill=ink)

    if hs:
        cx, cy = ox + size / 2, oy + size / 2
        diam = hs * m * 0.96
        d.ellipse((cx - diam / 2, cy - diam / 2, cx + diam / 2, cy + diam / 2), fill=(255, 255, 255, 255))
        inner = diam / 2 - 4 * ss / 3
        if logo_kind == "letter":
            d.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill=ink)
            letter = (style.get("letter") or "Q")[:1].upper()
            f = fonts.font("display", int(diam * 0.5))
            d.text((cx, cy), letter, font=f, fill=(255, 255, 255, 255), anchor="mm")
        elif logo_kind == "image" and logo_img is not None:
            s = int(inner * 2)
            lg = logo_img.convert("RGBA")
            sc = max(s / lg.width, s / lg.height)
            lg = lg.resize((max(1, int(lg.width * sc)), max(1, int(lg.height * sc))), Image.LANCZOS)
            left, top = (lg.width - s) // 2, (lg.height - s) // 2
            lg = lg.crop((left, top, left + s, top + s))
            mask = Image.new("L", (s, s), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, s - 1, s - 1), fill=255)
            img.paste(lg, (int(cx - s / 2), int(cy - s / 2)), mask)
    return img.resize((w, h), Image.LANCZOS)


def _lum(hexc: str) -> float:
    r, g, b = [int(hexc.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast_ok(ink: str, minimum: float = 4.5) -> bool:
    """Ink against the white panel. Light inks decode on a screen but fail on printed, creased or sun-faded posters."""
    return (1.05) / (_lum(ink) + 0.05) >= minimum


def reads_anything(panel: Image.Image) -> bool:
    """True if a scanner can decode ANY text from the panel (used to prove the decoy is dead)."""
    if cv2 is None:
        return False
    base = panel.convert("RGB")
    bg = Image.new("RGB", (base.width + 120, base.height + 120), (255, 255, 255))
    bg.paste(base, (60, 60))
    bgr = cv2.cvtColor(np.array(bg), cv2.COLOR_RGB2BGR)
    try:
        if hasattr(cv2, "wechat_qrcode_WeChatQRCode"):
            res, _ = cv2.wechat_qrcode_WeChatQRCode().detectAndDecode(bgr)
            if res and any(res):
                return True
        text, _, _ = cv2.QRCodeDetector().detectAndDecode(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
        return bool(text)
    except Exception:
        return False


def decoy_matrix(matrix, seed: int):
    """Preview-only QR: same size and look as the real one, but the data and format bits are scrambled so no phone can read it.
    Finder, timing and alignment structure stay, so it still looks like a normal QR in a screenshot."""
    import random
    rnd = random.Random(seed)
    n = len(matrix)
    out = [row[:] for row in matrix]
    fmt = set()
    for i in range(9):                                   # format information, both copies
        for (x, y) in ((i, 8), (8, i), (n - 1 - i, 8), (8, n - 1 - i)):
            if 0 <= x < n and 0 <= y < n and x != 6 and y != 6:
                fmt.add((x, y))
    for y in range(n):
        for x in range(n):
            if _in_finder(x, y, n) or x == 6 or y == 6:
                continue
            if (x, y) in fmt:
                out[y][x] = not out[y][x]                # always flip the format bits
            elif rnd.random() < 0.42:
                out[y][x] = not out[y][x]
    return out


def decode_ok(panel: Image.Image, expected: str, ink: str = "#000000") -> bool:
    """Scan check: decode the clean panel. Uses OpenCV's WeChat decoder (ZXing based, close to what phone scanners do)
    and falls back to the basic OpenCV detector if the contrib module is missing."""
    if cv2 is None:
        return True
    if not contrast_ok(ink):
        return False
    base = panel.convert("RGB")
    bg = Image.new("RGB", (base.width + 120, base.height + 120), (255, 255, 255))
    bg.paste(base, (60, 60))
    bgr = cv2.cvtColor(np.array(bg), cv2.COLOR_RGB2BGR)
    if hasattr(cv2, "wechat_qrcode_WeChatQRCode"):
        try:
            res, _ = cv2.wechat_qrcode_WeChatQRCode().detectAndDecode(bgr)
            if res and res[0] == expected:
                return True
        except Exception:
            pass
        return False
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    det = cv2.QRCodeDetector()
    for g in (gray, cv2.resize(gray, None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA)):
        try:
            text, _, _ = det.detectAndDecode(g)
        except Exception:
            text = ""
        if text == expected:
            return True
    return False


def svg_qr(matrix, style: dict, size: int = 1024) -> str:
    n = len(matrix)
    ink = style.get("ink", "#0b0b10")
    dot = style.get("dot", "dot")
    pad = size * 0.06
    m = (size - 2 * pad) / n
    hs = logo_hole(n, style.get("logo", "none"))
    lo = (n - hs) // 2
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">',
             f'<rect width="{size}" height="{size}" fill="#ffffff"/>', f'<g fill="{ink}">']
    for y in range(n):
        for x in range(n):
            if not matrix[y][x] or (hs and lo <= x < lo + hs and lo <= y < lo + hs):
                continue
            px, py = pad + x * m, pad + y * m
            if dot == "dot" and not _in_finder(x, y, n):
                parts.append(f'<circle cx="{px + m / 2:.2f}" cy="{py + m / 2:.2f}" r="{m * 0.47:.2f}"/>')
            elif dot == "round" and not _in_finder(x, y, n):
                parts.append(f'<rect x="{px + m * .04:.2f}" y="{py + m * .04:.2f}" width="{m * .92:.2f}" height="{m * .92:.2f}" rx="{m * .3:.2f}"/>')
            else:
                parts.append(f'<rect x="{px:.2f}" y="{py:.2f}" width="{m + .3:.2f}" height="{m + .3:.2f}"/>')
    parts.append("</g></svg>")
    return "".join(parts)


def transparent_png(matrix, style: dict, logo_img=None, px: int = 1024) -> bytes:
    panel = draw_panel(px, px, matrix, style, radius=int(px * 0.05), logo_img=logo_img)
    out = BytesIO()
    panel.save(out, "PNG")
    return out.getvalue()
