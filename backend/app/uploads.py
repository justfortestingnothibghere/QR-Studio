"""User uploads: theme artwork and logos. Images are fully decoded and re-encoded with Pillow (never stored as sent),
so metadata, polyglot payloads and oversized images do not reach disk."""
import json
import secrets
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from . import config, db
from .render import engine
from .render.layouts import layout
from .security import ApiError

Image.MAX_IMAGE_PIXELS = None  # we enforce our own limit below
SAFE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}
HEX = __import__("re").compile(r"^#[0-9a-fA-F]{6}$")


def open_image(data: bytes) -> Image.Image:
    max_mb = int(config.get("storage.max_upload_mb", 8))
    if len(data) > max_mb * 1024 * 1024:
        raise ApiError(413, "Image is larger than %d MB" % max_mb)
    try:
        probe = Image.open(BytesIO(data))
        fmt = probe.format
        if fmt not in SAFE_FORMATS:
            raise ApiError(415, "Use a JPG, PNG or WebP image")
        w, h = probe.size
        if w < 16 or h < 16 or w * h > int(config.get("storage.max_image_megapixels", 40)) * 1_000_000:
            raise ApiError(413, "Image dimensions are out of range")
        im = Image.open(BytesIO(data))
        im.load()
    except ApiError:
        raise
    except Exception:
        raise ApiError(415, "That file is not a readable image")
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
    else:
        im = im.convert("RGB")
    return im


def _user_dir(kind: str, owner_id: int) -> Path:
    p = config.data_dir() / kind / str(owner_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_logo(owner_id: int, data: bytes) -> str:
    n = db.one("SELECT COUNT(*) n FROM logos WHERE owner_id=?", (owner_id,))["n"]
    if n >= int(config.get("limits.max_logos_per_user", 10)):
        raise ApiError(409, "Logo limit reached. Delete an old logo first.")
    im = open_image(data)
    im.thumbnail((512, 512), Image.LANCZOS)
    lid = "lg" + secrets.token_hex(6)
    im.save(_user_dir("logos", owner_id) / (lid + ".png"), "PNG", optimize=True)
    db.run("INSERT INTO logos(id,owner_id,created) VALUES(?,?,?)", (lid, owner_id, time.time()))
    return lid


def load_logo(owner_id: int, logo_id: str):
    if not logo_id or not logo_id.isalnum():
        return None
    row = db.one("SELECT id FROM logos WHERE id=? AND owner_id=?", (logo_id, owner_id))
    if not row:
        return None
    p = config.data_dir() / "logos" / str(owner_id) / (logo_id + ".png")
    return Image.open(p).convert("RGBA") if p.exists() else None


def save_theme(owner_id: int, data: bytes, name: str, tpl: str, accent: str, ink: str, soft: str, qr_box=None) -> dict:
    n = db.one("SELECT COUNT(*) n FROM user_themes WHERE owner_id=?", (owner_id,))["n"]
    if n >= int(config.get("limits.max_custom_themes_per_user", 5)):
        raise ApiError(409, "You can keep %d custom themes. Delete one to add another." % config.get("limits.max_custom_themes_per_user", 5))
    if tpl not in ("A", "B", "C", "D"):
        raise ApiError(400, "Pick a layout")
    for c in (accent, ink, soft):
        if not HEX.match(c):
            raise ApiError(400, "Colours must look like #aabbcc")
    im = open_image(data).convert("RGB")
    target = 2 / 3
    w, h = im.size
    if w / h > target:
        nw = int(h * target)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / target)
        im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    im = im.resize((2048, 3072), Image.LANCZOS)
    tid = "u" + secrets.token_hex(6)
    im.save(_user_dir("user_themes", owner_id) / (tid + ".jpg"), "JPEG", quality=92, optimize=True)
    lay = layout("C" if tpl == "D" else tpl, {"acc": accent, "soft": soft, "ink": ink})
    manifest = {"id": tid, "owner_id": owner_id, "name": (name or "My theme")[:30], "category": "Mine", "layout": tpl, "accent": accent,
                "qr": lay["qr"], "texts": lay["texts"], "draw_frame": tpl in ("A", "C"), "frame": lay.get("frame") or {"x": lay["qr"]["x"] - 28, "y": lay["qr"]["y"] - 28, "w": lay["qr"]["w"] + 56, "h": lay["qr"]["h"] + 56, "r": 36}}
    if tpl == "D":
        manifest["texts"] = []
        manifest["draw_frame"] = False
        if qr_box:
            s = max(200, min(760, int(qr_box.get("size", 500))))
            x = max(0, min(1024 - s, int(qr_box.get("x", 262))))
            y = max(0, min(1536 - s, int(qr_box.get("y", 430))))
            manifest["qr"] = {"x": x, "y": y, "w": s, "h": s, "r": 30}
    if tpl == "A":
        manifest["draw_frame"] = True
    db.run("INSERT INTO user_themes(id,owner_id,name,manifest,created) VALUES(?,?,?,?,?)", (tid, owner_id, manifest["name"], json.dumps(manifest), time.time()))
    return manifest


def get_theme(theme_id: str, user=None):
    t = engine.builtin_themes().get(theme_id)
    if t:
        return t
    if user and theme_id and theme_id.startswith("u"):
        r = db.one("SELECT manifest FROM user_themes WHERE id=? AND owner_id=?", (theme_id, user["id"]))
        if r:
            return json.loads(r["manifest"])
    return None


def delete_theme(owner_id: int, tid: str):
    if db.run("DELETE FROM user_themes WHERE id=? AND owner_id=?", (tid, owner_id))[1]:
        p = config.data_dir() / "user_themes" / str(owner_id) / (tid + ".jpg")
        p.unlink(missing_ok=True)
        return True
    return False
