#!/usr/bin/env python3
"""Generates the built-in poster themes (original artwork, drawn in code) into data/themes.
Usage: python scripts/gen_themes.py [--force] [theme-id ...]
Each theme = <id>.jpg (2048x3072 background, no QR) + <id>_thumb.jpg + <id>.json manifest."""
import json
import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402
from app.render import fonts  # noqa: E402

K = 2
W, H = 1024 * K, 1536 * K


def rgb(h, a=255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def sc(v):
    return int(round(v * K))


def pts(seq):
    return [(x * K, y * K) for x, y in seq]


def bez(p0, p1, p2, p3, n=24):
    out = []
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def qbez(p0, p1, p2, n=24):
    return [(((1 - t) ** 2) * p0[0] + 2 * t * (1 - t) * p1[0] + t * t * p2[0],
             ((1 - t) ** 2) * p0[1] + 2 * t * (1 - t) * p1[1] + t * t * p2[1]) for t in [i / n for i in range(n + 1)]]


def gradient_bg(stops, glows=()):
    w, h = W // 4, H // 4
    ys = np.linspace(0, 1, h)
    arr = np.zeros((h, w, 3), np.float32)
    for c in range(3):
        arr[:, :, c] = np.interp(ys, [s[0] for s in stops], [rgb(s[1])[c] for s in stops])[:, None]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    for (cx, cy, r, strength, col) in glows:
        d = np.hypot((xx - cx * K / 4) / (r * K / 4), (yy - cy * K / 4) / (r * K / 4))
        a = np.clip(1 - d, 0, 1) ** 2 * strength
        for c in range(3):
            arr[:, :, c] += a * rgb(col)[c]
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
    return im.convert("RGBA")


def specks(im, rng, col, n=520, maxa=0.35):
    d = ImageDraw.Draw(im)
    for _ in range(n):
        s = rng.random() * 3 * K
        x, y = rng.random() * W, rng.random() * H
        d.rectangle((x, y, x + s, y + s), fill=col[:3] + (int(255 * rng.random() * maxa),))


def glow_over(im, layer, radius):
    im.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius * K)))


def bolts(im, rng, acc, count=56, cx=512, cy=880, rx=300, ry=400):
    wide = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    core = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    thin = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dw, dc, dt = ImageDraw.Draw(wide), ImageDraw.Draw(core), ImageDraw.Draw(thin)
    for _ in range(count):
        th = rng.random() * math.tau
        x = cx + math.cos(th) * (rx - 10 + rng.random() * 60)
        y = cy + math.sin(th) * (ry - 20 + rng.random() * 60)
        ang = th + (rng.random() - .5) * .8
        steps = 6 + int(rng.random() * 8)
        ln = 80 + rng.random() * 190
        p = [(x * K, y * K)]
        for _i in range(steps):
            ang += (rng.random() - .5) * 1.2
            l = ln / steps * (.6 + rng.random() * .8)
            x += math.cos(ang) * l
            y += math.sin(ang) * l
            p.append((x * K, y * K))
        dw.line(p, fill=acc[:3] + (110,), width=sc(8), joint="curve")
        dc.line(p, fill=acc[:3] + (240,), width=sc(2.4), joint="curve")
        dt.line(p, fill=(255, 255, 255, 190), width=max(1, sc(.9)), joint="curve")
    glow_over(im, wide, 12)
    glow_over(im, core, 3)
    im.alpha_composite(core)
    im.alpha_composite(thin)


def ribbons(im, rng, acc, n=9):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for i in range(n):
        left = i % 2 == 0
        x0, y0 = (-20 if left else 1044), 520 + rng.random() * 700
        x1, y1 = (460 if left else 560), y0 + (rng.random() - .5) * 520
        ctrl = (100 if left else 920, y0 + (rng.random() - .5) * 500)
        d.line(pts(qbez((x0, y0), ctrl, (x1, y1), 40)), fill=acc[:3] + (int(255 * (.25 + rng.random() * .4)),),
               width=sc(2 + rng.random() * 10), joint="curve")
    glow_over(im, lay, 8)
    im.alpha_composite(lay)


def manga_panel(im, rng, acc, poly, fx, fy, eye, tint=.2):
    tile = Image.new("RGBA", (W, H), (200, 200, 208, 255))
    d = ImageDraw.Draw(tile)
    for _ in range(170):
        a = rng.random() * math.tau
        r0, r1 = 24 + rng.random() * 90, 300 + rng.random() * 500
        d.line([((fx + math.cos(a) * r0) * K, (fy + math.sin(a) * r0) * K),
                ((fx + math.cos(a) * r1) * K, (fy + math.sin(a) * r1) * K)],
               fill=(8, 8, 12, int(255 * (.2 + rng.random() * .55))), width=max(1, sc(.5 + rng.random() * 2.4)))
    if eye:
        almond = qbez((fx - 120, fy), (fx, fy - 78), (fx + 120, fy)) + qbez((fx + 120, fy), (fx, fy + 78), (fx - 120, fy))
        d.polygon(pts(almond), fill=(244, 244, 247, 255))
        for i in range(30):
            r = 46 * (1 - i / 30)
            t = i / 30
            col = tuple(int(255 * t + acc[c] * (1 - t)) for c in range(3))
            d.ellipse(((fx - r) * K, (fy - r) * K, (fx + r) * K, (fy + r) * K), fill=col + (255,))
        d.ellipse(((fx - 14) * K, (fy - 14) * K, (fx + 14) * K, (fy + 14) * K), fill=(5, 5, 8, 255))
        d.line(pts(almond), fill=(10, 10, 16, 255), width=sc(5))
    else:
        d.polygon(pts(qbez((fx - 70, fy + 170), (fx - 80, fy - 20), (fx, fy - 70)) + qbez((fx, fy - 70), (fx + 90, fy - 20), (fx + 70, fy + 170))),
                  fill=(6, 6, 12, 225))
    tl = Image.new("RGBA", (W, H), acc[:3] + (int(255 * tint),))
    tile.alpha_composite(tl)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon(pts(poly), fill=255)
    im.paste(tile, (0, 0), mask)
    edge = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(edge).line(pts(poly + [poly[0]]), fill=acc, width=sc(2.5), joint="curve")
    glow_over(im, edge, 5)
    im.alpha_composite(edge)


def burst(im, rng, acc, cx=512, cy=262):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for i in range(30):
        a = i / 30 * math.tau
        l = 130 + rng.random() * 130
        tri = [(cx + math.cos(a - .09) * 70, cy + math.sin(a - .09) * 70), (cx + math.cos(a) * l, cy + math.sin(a) * l),
               (cx + math.cos(a + .09) * 70, cy + math.sin(a + .09) * 70)]
        d.polygon(pts(tri), fill=(4, 4, 10, 235), outline=acc)
    glow_over(im, lay, 6)
    im.alpha_composite(lay)
    d = ImageDraw.Draw(im)
    for i in range(46):
        t = i / 46
        r = 92 * (1 - t)
        col = tuple(int(255 * t * t * 0 + (255 if t > .9 else 0) + 0) for _ in range(3))
        c = tuple(int(acc[k] * (t ** .6) + (4 * (1 - t))) for k in range(3))
        d.ellipse(((cx - r) * K, (cy - r) * K, (cx + r) * K, (cy + r) * K), fill=c + (255,))
    d.ellipse(((cx - 20) * K, (cy - 20) * K, (cx + 20) * K, (cy + 20) * K), fill=(255, 255, 255, 235))
    d.ellipse(((cx - 118) * K, (cy - 118) * K, (cx + 118) * K, (cy + 118) * K), outline=(255, 255, 255, 190), width=sc(3))


def skyline(im, rng, acc, top=1200):
    h = H - top * K
    a = np.linspace(0, 1, h, dtype=np.float32)
    alpha = np.interp(a, [0, .6, 1], [0, .34, .9])
    layer = np.zeros((h, W, 4), np.uint8)
    layer[..., 0:3] = np.array([acc[0], acc[1], acc[2]], np.uint8)
    layer[..., 3] = (alpha[:, None] * 255).astype(np.uint8)
    # fade the bottom into dark
    dark = np.array([4, 4, 12], np.float32)
    mix = np.clip((a - .6) / .4, 0, 1)[:, None, None]
    layer[..., 0:3] = (layer[..., 0:3] * (1 - mix) + dark * mix).astype(np.uint8)
    im.alpha_composite(Image.fromarray(layer, "RGBA"), (0, top * K))
    d = ImageDraw.Draw(im)
    x = -10
    while x < 1024:
        bw, bh = 36 + rng.random() * 58, 60 + rng.random() * 250
        d.rectangle((x * K, (1536 - bh) * K, (x + bw) * K, H), fill=(4, 5, 12, 240))
        wy = 1536 - bh + 10
        while wy < 1528:
            wx = x + 6
            while wx < x + bw - 8:
                if rng.random() < .22:
                    d.rectangle((wx * K, wy * K, (wx + 4) * K, (wy + 7) * K), fill=acc[:3] + (int(255 * (.25 + rng.random() * .5)),))
                wx += 12
            wy += 16
        x += bw + rng.random() * 8


def figure(im, acc):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    body = bez((372, 1536), (384, 1450), (442, 1412), (512, 1406)) + bez((512, 1406), (582, 1412), (640, 1450), (652, 1536))
    d.polygon(pts(body), fill=(4, 4, 10, 255))
    d.ellipse((468 * K, 1326 * K, 556 * K, 1414 * K), fill=(4, 4, 10, 255))
    glow_over(im, lay, 10)
    im.alpha_composite(lay)
    d = ImageDraw.Draw(im)
    d.line(pts(bez((384, 1470), (398, 1430), (448, 1412), (512, 1408)) + bez((512, 1408), (576, 1412), (626, 1430), (640, 1470))),
           fill=acc[:3] + (180,), width=sc(2.5), joint="curve")


def crown(d, x, y, s, col, w=3):
    p = [(x - s, y), (x - s * .8, y - s * .9), (x - s * .4, y - s * .35), (x, y - s * 1.1),
         (x + s * .4, y - s * .35), (x + s * .8, y - s * .9), (x + s, y)]
    d.line(pts(p + [p[0]]), fill=col, width=sc(w), joint="curve")
    d.line(pts([(x - s * .9, y + s * .25), (x + s * .9, y + s * .25)]), fill=col, width=sc(w))


def text_block(im, lines, x, y, rot, align, acc, soft):
    if not lines:
        return
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    yy = 0
    for i, ln in enumerate(lines):
        big = i == 0 and len(ln) <= 5
        size = 84 if big else 34
        f = fonts.font("script", sc(size))
        yy += size * 1.12
        col = acc if (i == 0) else soft
        d.text((x * K, (y + yy) * K), ln, font=f, fill=col, anchor=("ls" if align == "left" else "rs"))
    sx = x - 190 if align == "right" else x
    d.line(pts([(sx, y + yy + 16), (sx + 190, y + yy + 6)]), fill=acc, width=sc(4))
    glow = lay.filter(ImageFilter.GaussianBlur(sc(7)))
    lay = lay.rotate(rot, resample=Image.BICUBIC, center=(x * K, y * K))
    glow = glow.rotate(rot, resample=Image.BICUBIC, center=(x * K, y * K))
    im.alpha_composite(glow)
    im.alpha_composite(lay)


def kanji(im, pair, pos, acc):
    if not pair:
        return
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    f = fonts.font("kanji", sc(120))
    d.text((pos[0] * K, pos[1] * K), pair[0], font=f, fill=acc, anchor="mm")
    d.text((pos[0] * K, (pos[1] + 130) * K), pair[1], font=f, fill=acc, anchor="mm")
    glow_over(im, lay, 10)
    im.alpha_composite(lay)


def corners(im, t, acc, soft):
    d = ImageDraw.Draw(im)
    if t.get("tl"):
        crown(d, 66, 96, 22, acc)
        text_block(im, t["tl"], 48, 100, 5.7, "left", acc, soft)
    if t.get("tr"):
        crown(d, 950, 86, 22, acc)
        text_block(im, t["tr"], 976, 92, 5.7, "right", acc, soft)
    if t.get("bl"):
        crown(d, 70, 1264, 22, acc)
        text_block(im, t["bl"], 48, 1270, 6.9, "left", acc, soft)
    if t.get("br"):
        text_block(im, t["br"], 976, 1262, 5.7, "right", acc, soft)
    if t.get("kanji"):
        kanji(im, t["kanji"], t.get("kpos", (925, 690)), acc)


# ---------- motifs ----------
def motif_surge(t, rng):
    acc = rgb(t["acc"])
    im = gradient_bg([(0, t["b0"]), (.5, t["b1"]), (1, t["b0"])], [(512, 800, 640, .42, t["acc"])])
    specks(im, rng, acc)
    manga_panel(im, rng, acc, [(0, 250), (282, 296), (248, 640), (0, 664)], 150, 470, False)
    manga_panel(im, rng, acc, [(790, 330), (1024, 296), (1024, 580), (760, 540)], 900, 430, True)
    manga_panel(im, rng, acc, [(1024, 1020), (860, 1060), (820, 1230), (1024, 1240)], 930, 1130, False)
    burst(im, rng, acc)
    ribbons(im, rng, acc)
    bolts(im, rng, acc)
    skyline(im, rng, acc)
    figure(im, acc)
    return im


def motif_grid(t, rng):
    acc, acc2 = rgb(t["acc"]), rgb(t.get("acc2", t["acc"]))
    im = gradient_bg([(0, t["b0"]), (.62, t["b1"]), (1, t["b0"])], [(512, 300, 560, .55, t["acc"]), (512, 1000, 600, .25, t.get("acc2", t["acc"]))])
    specks(im, rng, (255, 255, 255, 255), n=260, maxa=.8)
    d = ImageDraw.Draw(im)
    cx, cy, r = 512, 330, 230
    for i in range(60):
        tt = i / 60
        rr = r * (1 - tt)
        col = tuple(int(acc[k] * (1 - tt) + acc2[k] * tt) for k in range(3))
        d.ellipse(((cx - r) * K, (cy - r) * K, (cx + r) * K, (cy + r) * K), fill=col + (255,)) if i == 0 else None
    # sun as vertical gradient disc
    sun = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sun)
    for y in range(int((cy - r) * K), int((cy + r) * K)):
        tt = (y - (cy - r) * K) / (2 * r * K)
        col = tuple(int(acc[k] * (1 - tt) + acc2[k] * tt) for k in range(3))
        half = math.sqrt(max(0, (r * K) ** 2 - (y - cy * K) ** 2))
        sd.line([(cx * K - half, y), (cx * K + half, y)], fill=col + (255,))
    cut = ImageDraw.Draw(sun)
    for i in range(10):
        yy = (cy + 40 + i * 18) * K
        cut.rectangle((0, yy, W, yy + sc(2 + i * 1.6)), fill=(0, 0, 0, 0))
    mask = Image.new("L", (W, H), 255)
    md = ImageDraw.Draw(mask)
    for i in range(10):
        yy = (cy + 40 + i * 18) * K
        md.rectangle((0, yy, W, yy + sc(2 + i * 1.6)), fill=0)
    sun.putalpha(ImageChops.multiply(sun.getchannel("A"), mask))
    glow_over(im, sun, 24)
    im.alpha_composite(sun)
    # mountains + perspective floor
    d = ImageDraw.Draw(im)
    hz = 1290
    mt = [(0, hz)]
    xx = 0
    while xx < 1024:
        xx += 40 + rng.random() * 60
        mt.append((xx, hz - 30 - rng.random() * 120))
        xx += 40 + rng.random() * 60
        mt.append((xx, hz - 4))
    mt.append((1024, hz))
    d.polygon(pts(mt + [(1024, hz + 4), (0, hz + 4)]), fill=(6, 4, 16, 255), outline=acc2)
    d.rectangle((0, hz * K, W, H), fill=(6, 4, 18, 255))
    lines = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lines)
    for i in range(-14, 15):
        ld.line([(512 * K, hz * K), ((512 + i * 130) * K, H)], fill=acc2[:3] + (200,), width=sc(2))
    for j in range(1, 14):
        y = hz + (1536 - hz) * (j / 13) ** 2
        ld.line([(0, y * K), (W, y * K)], fill=acc[:3] + (200,), width=sc(2))
    glow_over(im, lines, 4)
    im.alpha_composite(lines)
    return im


def motif_bloom(t, rng):
    acc = rgb(t["acc"])
    im = gradient_bg([(0, t["b0"]), (.5, t["b1"]), (1, t["b0"])], [(300, 400, 520, .5, t["acc"]), (760, 1100, 560, .4, t.get("acc2", t["acc"]))])
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for _ in range(14):
        x, y, r = rng.random() * 1024, rng.random() * 1536, 60 + rng.random() * 160
        c = rgb(t["acc"] if rng.random() < .6 else t.get("acc2", t["acc"]))
        d.ellipse(((x - r) * K, (y - r) * K, (x + r) * K, (y + r) * K), fill=c[:3] + (int(255 * (.1 + rng.random() * .2)),))
    glow_over(im, lay, 30)
    bok = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bok)
    for _ in range(90):
        x, y, r = rng.random() * 1024, rng.random() * 1536, 5 + rng.random() * 26
        a = int(255 * (.12 + rng.random() * .4))
        bd.ellipse(((x - r) * K, (y - r) * K, (x + r) * K, (y + r) * K), outline=acc[:3] + (a,), width=max(1, sc(1.5)))
        if rng.random() < .5:
            bd.ellipse(((x - r * .5) * K, (y - r * .5) * K, (x + r * .5) * K, (y + r * .5) * K), fill=acc[:3] + (a // 2,))
    glow_over(im, bok, 2)
    im.alpha_composite(bok)
    arc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ad = ImageDraw.Draw(arc)
    for i in range(7):
        y0 = 200 + i * 30
        ad.line(pts(qbez((-20, y0 + 300), (512, y0 - 220 + i * 40), (1044, y0 + 400), 60)), fill=acc[:3] + (int(255 * (.35 - i * .03)),), width=sc(2))
        ad.line(pts(qbez((-20, 1250 - i * 26), (512, 1500 + i * 30), (1044, 1180 - i * 20), 60)), fill=acc[:3] + (int(255 * (.35 - i * .03)),), width=sc(2))
    glow_over(im, arc, 5)
    im.alpha_composite(arc)
    specks(im, rng, (255, 255, 255, 255), n=300, maxa=.5)
    return im


def motif_waves(t, rng):
    acc, acc2 = rgb(t["acc"]), rgb(t.get("acc2", t["acc"]))
    im = gradient_bg([(0, t["b0"]), (.55, t["b1"]), (1, t["b0"])], [(512, 700, 640, .35, t["acc"])])
    for band, (base, amp, col, a) in enumerate([(1180, 70, acc, 60), (1240, 60, acc2, 70), (1300, 50, acc, 90), (1370, 40, acc2, 120), (1440, 30, acc, 170)]):
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        ph = rng.random() * 6
        p = [(x, base + math.sin(x / 150 + ph) * amp + math.sin(x / 61 + ph * 2) * amp * .3) for x in range(-10, 1040, 8)]
        d.polygon(pts(p + [(1034, 1536), (-10, 1536)]), fill=col[:3] + (a,))
        d.line(pts(p), fill=col[:3] + (255,), width=sc(3))
        glow_over(im, lay, 4)
        im.alpha_composite(lay)
    for band, (base, amp) in enumerate([(300, 70), (240, 50), (190, 40)]):
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        ph = rng.random() * 6
        p = [(x, base - math.sin(x / 130 + ph) * amp) for x in range(-10, 1040, 8)]
        d.polygon(pts(p + [(1034, 0), (-10, 0)]), fill=(acc2 if band % 2 else acc)[:3] + (55 + band * 25,))
        d.line(pts(p), fill=(acc2 if band % 2 else acc)[:3] + (230,), width=sc(2.5))
        glow_over(im, lay, 4)
        im.alpha_composite(lay)
    d = ImageDraw.Draw(im)
    for _ in range(160):
        x, y, r = rng.random() * 1024, 330 + rng.random() * 800, 1 + rng.random() * 3
        d.ellipse(((x - r) * K, (y - r) * K, (x + r) * K, (y + r) * K), fill=acc[:3] + (int(255 * (.2 + rng.random() * .5)),))
    return im


def motif_mono(t, rng):
    acc = rgb(t["acc"])
    im = gradient_bg([(0, t["b0"]), (1, t["b1"])], [(512, 760, 600, .18, t["acc"])])
    d = ImageDraw.Draw(im)
    step = 34
    for gy in range(0, 1536 + step, step):
        for gx in range(0, 1024 + step, step):
            dist = math.hypot(gx - 512, gy - 780) / 780
            r = max(0, min(1, dist)) ** 1.6 * 11
            if r > .8:
                off = (step / 2) if (gy // step) % 2 else 0
                d.ellipse(((gx + off - r) * K, (gy - r) * K, (gx + off + r) * K, (gy + r) * K), fill=acc[:3] + (110,))
    d.rectangle((24 * K, 24 * K, (1024 - 24) * K, (1536 - 24) * K), outline=acc[:3] + (200,), width=sc(3))
    d.rectangle((40 * K, 40 * K, (1024 - 40) * K, (1536 - 40) * K), outline=acc[:3] + (90,), width=sc(1.5))
    return im


def motif_light(t, rng):
    acc = rgb(t["acc"])
    im = gradient_bg([(0, t["b0"]), (1, t["b1"])])
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.polygon(pts([(0, 0), (1024, 0), (1024, 260), (0, 420)]), fill=acc[:3] + (255,))
    d.polygon(pts([(0, 1536), (1024, 1536), (1024, 1300), (0, 1420)]), fill=acc[:3] + (255,))
    for i in range(14):
        x = 40 + i * 70
        d.ellipse((x * K, 1330 * K, (x + 34) * K, 1364 * K), fill=(255, 255, 255, 70))
        d.ellipse(((x + 20) * K, 90 * K, (x + 52) * K, 122 * K), fill=(255, 255, 255, 60))
    im.alpha_composite(lay)
    return im


MOTIFS = {"surge": motif_surge, "grid": motif_grid, "bloom": motif_bloom, "waves": motif_waves, "mono": motif_mono, "light": motif_light}


from app.render.layouts import layout  # noqa: E402


def bake_frame(im, lay, acc):
    f = lay.get("frame")
    if not f:
        return
    g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(g)
    box = (f["x"] * K, f["y"] * K, (f["x"] + f["w"]) * K, (f["y"] + f["h"]) * K)
    gd.rounded_rectangle(box, radius=f["r"] * K, outline=acc[:3] + (255,), width=sc(6))
    glow_over(im, g, 16)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(box, radius=f["r"] * K, fill=(3, 0, 6, 240), outline=acc, width=sc(3))


def sample_text_colors(t):
    return t["acc"], t.get("soft", "#ffffff")


THEMES = [
    dict(id="crimson-surge", name="Crimson Surge", cat="Energy", layout="A", motif="surge", acc="#ff2638", soft="#ffe1e3", b0="#080204", b1="#2b050c", seed=11,
         tl=["SCAN", "TO RECEIVE", "PAYMENTS"], tr=["FAST", "SECURE", "EASY"], bl=["SMALL", "STEPS", "BIG", "DREAMS"], br=["PAYMENT", "MAKES", "LIFE", "EASIER"], kanji=("最", "強"), kpos=(925, 690)),
    dict(id="azure-void", name="Azure Void", cat="Energy", layout="B", motif="surge", acc="#4da3ff", soft="#e6f0ff", b0="#03040f", b1="#0b0f3a", seed=23,
         tl=["GOOD VIBES", "GOOD PAYMENTS", "BETTER FUTURE"], tr=["ONE SCAN", "NO CASH", "NO WAIT"], bl=["DREAM", "BUILD", "ACHIEVE"], br=["SCAN", "PAY", "DONE"], kanji=("決", "済"), kpos=(92, 830)),
    dict(id="violet-storm", name="Violet Storm", cat="Energy", layout="C", motif="surge", acc="#b46bff", soft="#f0e3ff", b0="#07030f", b1="#1d0a3a", seed=37,
         tl=["PAY IN", "ONE SCAN"], tr=["FAST", "SAFE"], bl=["GOOD", "VIBES", "ONLY"], br=["THANK", "YOU"], kanji=("光", "速"), kpos=(925, 700)),
    dict(id="ember-rush", name="Ember Rush", cat="Energy", layout="A", motif="surge", acc="#ff8a1f", soft="#ffe9d2", b0="#0a0402", b1="#33140a", seed=41,
         tl=["SCAN", "AND GO"], tr=["QUICK", "PAY"], bl=["KEEP", "IT", "MOVING"], br=["SHOP", "SMART"], kanji=("炎", "力"), kpos=(925, 690)),
    dict(id="toxic-volt", name="Toxic Volt", cat="Energy", layout="B", motif="surge", acc="#7dff3a", soft="#eaffd9", b0="#030a03", b1="#0d2a0a", seed=53,
         tl=["PAY", "WITH", "A SCAN"], tr=["NO", "CASH", "NEEDED"], bl=["LEVEL", "UP"], br=["GG", "WELL", "PAID"], kanji=("雷", "速"), kpos=(92, 830)),
    dict(id="neon-horizon", name="Neon Horizon", cat="Retro", layout="A", motif="grid", acc="#ff3ea5", acc2="#26e6ff", soft="#d7f7ff", b0="#0a0320", b1="#2a0a4a", seed=61,
         tl=["SCAN", "TO PAY"], tr=["RETRO", "FAST"], bl=[], br=[], kanji=None),
    dict(id="cyan-drive", name="Cyan Drive", cat="Retro", layout="B", motif="grid", acc="#25f0ff", acc2="#7b5cff", soft="#d5fbff", b0="#020816", b1="#0b1d4a", seed=67,
         tl=["NIGHT", "DRIVE"], tr=["PAY", "SMOOTH"], bl=[], br=[], kanji=None),
    dict(id="sakura-drift", name="Sakura Drift", cat="Soft", layout="C", motif="bloom", acc="#ff7eb6", acc2="#c9a0ff", soft="#ffe6f1", b0="#1a0a14", b1="#3a1230", seed=71,
         tl=["SOFT", "PAYMENTS"], tr=[], bl=["SCAN", "AND", "SMILE"], br=[], kanji=("花", "月"), kpos=(925, 690)),
    dict(id="golden-hour", name="Golden Hour", cat="Soft", layout="A", motif="bloom", acc="#ffc247", acc2="#ff7a45", soft="#fff1d2", b0="#120a02", b1="#35200a", seed=73,
         tl=["GOLDEN", "VIBES"], tr=["THANK", "YOU"], bl=[], br=[], kanji=("福", "運"), kpos=(925, 690)),
    dict(id="mint-mist", name="Mint Mist", cat="Soft", layout="B", motif="bloom", acc="#4dffc3", acc2="#4da3ff", soft="#e0fff5", b0="#02100d", b1="#0a3a33", seed=79,
         tl=["FRESH", "PAY"], tr=[], bl=["SCAN", "ME"], br=[], kanji=None),
    dict(id="ocean-pulse", name="Ocean Pulse", cat="Calm", layout="C", motif="waves", acc="#2ee6d6", acc2="#3a7bff", soft="#d9fffb", b0="#020c14", b1="#06304a", seed=83,
         tl=["RIDE", "THE", "WAVE"], tr=["EASY", "PAY"], bl=[], br=[], kanji=None),
    dict(id="aurora-flow", name="Aurora Flow", cat="Calm", layout="A", motif="waves", acc="#8affc1", acc2="#a56bff", soft="#eafff4", b0="#030a10", b1="#10143a", seed=89,
         tl=["NORTHERN", "LIGHTS"], tr=["SCAN", "NOW"], bl=[], br=[], kanji=None),
    dict(id="free-wifi-pulse", name="Free WiFi Pulse", cat="Cafe & Wi-Fi", layout="C", motif="waves", acc="#ffd23f", acc2="#ff5d8f", soft="#fff6d6", b0="#07060f", b1="#241446", seed=97,
         tl=["FREE", "WIFI"], tr=["SCAN", "TO JOIN"], bl=[], br=[], kanji=None),
    dict(id="mono-ink", name="Mono Ink", cat="Minimal", layout="A", motif="mono", acc="#ffffff", soft="#cfd3dc", b0="#050506", b1="#16171b", seed=101,
         tl=["SCAN", "TO PAY"], tr=[], bl=[], br=[], kanji=None),
    dict(id="noir-gold", name="Noir Gold", cat="Minimal", layout="C", motif="mono", acc="#e8c872", soft="#f3e6bf", b0="#060504", b1="#1a150b", seed=103,
         tl=["PREMIUM", "PAYMENTS"], tr=[], bl=[], br=[], kanji=None),
    dict(id="shop-fresh", name="Shop Fresh", cat="Shop", layout="C", motif="light", acc="#ff5a36", soft="#5b3a2e", ink="#2b1710", b0="#fff7ee", b1="#ffe9d6", seed=107, dark_text=True,
         tl=["WELCOME"], tr=[], bl=[], br=[], kanji=None),
    dict(id="chai-stall", name="Chai Stall", cat="Shop", layout="B", motif="light", acc="#c2410c", soft="#6b3a1a", ink="#3a1f0d", b0="#fff2d6", b1="#ffe0a8", seed=109, dark_text=True,
         tl=["CHAI", "SUTTA"], tr=[], bl=[], br=[], kanji=None),
    dict(id="diwali-glow", name="Diwali Glow", cat="Festive", layout="B", motif="bloom", acc="#ffb020", acc2="#ff4d2e", soft="#fff0cc", b0="#12030a", b1="#3a0f12", seed=113,
         tl=["SHUBH", "DIWALI"], tr=[], bl=["LIGHT", "UP"], br=["SCAN", "TO PAY"], kanji=None),
]


def build(t, out):
    rng = random.Random(t["seed"])
    im = MOTIFS[t["motif"]](t, rng)
    acc = rgb(t["acc"])
    soft = rgb(t.get("soft", "#ffffff"))
    # light themes: darker text blocks
    tcol = rgb(t["ink"]) if t.get("dark_text") else acc
    corners(im, t, tcol, soft)
    lay = layout(t["layout"], t)
    bake_frame(im, lay, acc)
    bg = im.convert("RGB")
    bg.save(out / (t["id"] + ".jpg"), "JPEG", quality=93, optimize=True)
    manifest = {
        "id": t["id"], "name": t["name"], "category": t["cat"], "layout": t["layout"], "accent": t["acc"],
        "dark_art": not t.get("dark_text", False),
        "qr": lay["qr"], "frame": lay.get("frame"), "texts": lay["texts"],
    }
    (out / (t["id"] + ".json")).write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    out = config.themes_dir()
    out.mkdir(parents=True, exist_ok=True)
    for t in THEMES:
        if args and t["id"] not in args:
            continue
        if not force and (out / (t["id"] + ".json")).exists():
            continue
        print("generating", t["id"], flush=True)
        build(t, out)
    print("done")


if __name__ == "__main__":
    main()
