"""Search engine side of the site: meta tags, canonical links, structured data (JSON-LD), server-rendered landing pages, sitemap."""
import hashlib
import html as _html
import json
import re
import time

from . import config, db
from .render import engine
from .seo_content import GUIDES, TYPES

NAME = "QR Studio"
TYPE_BY_SLUG = {t["slug"]: t for t in TYPES}
GUIDE_BY_SLUG = {g["slug"]: g for g in GUIDES}
_ASSET_REF = re.compile(r'(/assets/[A-Za-z0-9_./-]+\.(?:js|css))(?=["\'])')

# static pages: path -> (title, description, robots, schema)
STATIC = {
    "/": ("QR Studio: Make a UPI, Wi-Fi or Link QR as a Poster | TeamDev",
          "Turn your UPI, WhatsApp, Instagram, Wi-Fi or link QR into a poster people remember. 18 themes, free preview, download from ₹29. Pay by UPI.", "index", "home"),
    "/studio": ("QR Code Poster Studio: Build and Preview Free | QR Studio", "Build your QR poster online. UPI, links, Wi-Fi, WhatsApp, Instagram and more. Live preview with a scan check. Pay only to download.", "index", None),
    "/themes": ("QR Poster Themes: Shop, Cafe, Festive, Retro and More | QR Studio", "Browse QR poster themes for shops, cafes, festivals and creators. Try any theme with your own details for free.", "index", None),
    "/pricing": ("QR Studio Pricing: Posters From ₹29, Pay by UPI", "Simple pricing. A poster download from ₹29, extras for logo, dynamic link and print pack, capped at ₹99. 30 day unlimited pass for ₹99.", "index", "pricing"),
    "/how-it-works": ("How QR Studio Works: Preview, Pay by UPI, Download", "How previews are protected, how UPI payment is matched automatically and how your files unlock.", "index", None),
    "/faq": ("QR Studio FAQ: Payment, UTR, Previews and Downloads", "Answers about paying by UPI, Fam to Fam payments with no UTR, scrambled previews, downloads and accounts.", "index", None),
    "/contact": ("Contact QR Studio Support", "Get help with a payment, a download or your account. Email, Instagram and Telegram.", "index", None),
    "/about": ("About QR Studio by TeamDev", "Who builds QR Studio, how payments stay safe and how to reach us.", "index", "about"),
    "/refund": ("Refund Policy | QR Studio", "When QR Studio refunds or fixes a payment, and how to ask.", "index", None),
    "/terms": ("Terms of Service | QR Studio", "The terms for using QR Studio.", "index", None),
    "/privacy": ("Privacy Policy | QR Studio", "What QR Studio stores, what it never stores, and your choices.", "index", None),
    "/login": ("Log in | QR Studio", "Log in to QR Studio.", "noindex", None),
    "/signup": ("Create your QR Studio account", "Sign up to save QR posters and download them.", "noindex", None),
    "/dashboard": ("Dashboard | QR Studio", "Your QR posters, orders and invites.", "noindex", None),
    "/receipt": ("Receipt | QR Studio", "Payment receipt.", "noindex", None),
    "/admin": ("Admin | QR Studio", "Admin.", "noindex", None),
}


def esc(s) -> str:
    return _html.escape(str(s if s is not None else ""), quote=True)


def base() -> str:
    return config.site_url()


def asset_version() -> str:
    h = hashlib.sha1()
    for f in sorted((config.frontend_dir() / "assets").rglob("*")):
        if f.suffix in (".js", ".css"):
            st = f.stat()
            h.update(("%s%d%d" % (f.name, st.st_size, int(st.st_mtime))).encode())
    return h.hexdigest()[:10]


def finalize(html: str) -> str:
    ver = asset_version()
    return _ASSET_REF.sub(lambda m: m.group(1) + "?v=" + ver, html)


def site_cfg() -> dict:
    try:
        return json.loads((config.frontend_dir() / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _ld(obj) -> str:
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def organization() -> dict:
    c = site_cfg()
    same = []
    if c.get("support_instagram"):
        same.append("https://www.instagram.com/%s" % c["support_instagram"])
    if c.get("support_telegram"):
        same.append("https://t.me/%s" % c["support_telegram"].lstrip("@"))
    o = {"@context": "https://schema.org", "@type": "Organization", "name": "TeamDev", "url": base(), "logo": base() + "/assets/img/icon-512.png"}
    if same:
        o["sameAs"] = same
    if c.get("support_email"):
        o["contactPoint"] = {"@type": "ContactPoint", "contactType": "customer support", "email": c["support_email"], "availableLanguage": ["English", "Hindi"]}
    return o


def rating_block():
    try:
        r = db.one("SELECT COUNT(*) n, AVG(stars) a FROM reviews WHERE status='approved'")
        if r and r["n"] >= 5:                       # only real, approved reviews, and only when there are enough
            return {"@type": "AggregateRating", "ratingValue": round(r["a"], 1), "reviewCount": r["n"], "bestRating": 5}
    except Exception:
        pass
    return None


def webapp_ld() -> dict:
    p = config.get("pricing", {})
    d = {"@context": "https://schema.org", "@type": "WebApplication", "name": NAME, "url": base() + "/", "applicationCategory": "DesignApplication",
         "operatingSystem": "Any", "description": "Make UPI, link, Wi-Fi, WhatsApp and Instagram QR codes as printable posters.",
         "offers": {"@type": "AggregateOffer", "priceCurrency": "INR", "lowPrice": p.get("base", 29), "highPrice": p.get("cap", 99), "offerCount": 3},
         "publisher": {"@type": "Organization", "name": "TeamDev"}}
    r = rating_block()
    if r:
        d["aggregateRating"] = r
    return d


def faq_from_html(html: str):
    out = []
    for q, a in re.findall(r"<details[^>]*>\s*<summary>(.*?)</summary>\s*<p>(.*?)</p>", html, re.S):
        strip = lambda x: _html.unescape(re.sub(r"<[^>]+>", "", x)).strip()  # noqa: E731
        if strip(q) and strip(a):
            out.append((strip(q), strip(a)))
    return out


def faq_ld(pairs):
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in pairs]}


def crumbs(items):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": base() + p} for i, (n, p) in enumerate(items)]}


def head_tags(title, desc, path, image=None, robots="index", jsonld=(), og_type="website") -> str:
    url = base() + path
    img = image or (base() + "/assets/img/og.jpg")
    cv = config.get("seo.google_verification", "")
    bv = config.get("seo.bing_verification", "")
    t = [
        '<link rel="canonical" href="%s">' % esc(url),
        '<meta name="robots" content="%s">' % ("noindex, nofollow" if robots == "noindex" else "index, follow, max-image-preview:large"),
        '<meta property="og:site_name" content="%s">' % NAME, '<meta property="og:type" content="%s">' % og_type, '<meta property="og:locale" content="en_IN">',
        '<meta property="og:title" content="%s">' % esc(title), '<meta property="og:description" content="%s">' % esc(desc),
        '<meta property="og:url" content="%s">' % esc(url), '<meta property="og:image" content="%s">' % esc(img),
        '<meta name="twitter:card" content="summary_large_image">', '<meta name="twitter:title" content="%s">' % esc(title),
        '<meta name="twitter:description" content="%s">' % esc(desc), '<meta name="twitter:image" content="%s">' % esc(img),
        '<link rel="manifest" href="/manifest.webmanifest">', '<link rel="apple-touch-icon" href="/assets/img/icon-192.png">',
    ]
    if cv:
        t.append('<meta name="google-site-verification" content="%s">' % esc(cv))
    if bv:
        t.append('<meta name="msvalidate.01" content="%s">' % esc(bv))
    t += [_ld(j) for j in jsonld]
    return "\n".join(t)


def inject_static(html: str, path: str) -> str:
    """Give an existing static page its own title, description, canonical link, social cards and structured data."""
    meta = STATIC.get(path)
    if not meta:
        return html
    title, desc, robots, schema = meta
    ld = []
    if schema == "home":
        ld = [organization(), {"@context": "https://schema.org", "@type": "WebSite", "name": NAME, "url": base() + "/"}, webapp_ld()]
    elif schema == "about":
        ld = [organization()]
    if path not in ("/",) and robots != "noindex":
        ld.append(crumbs([("Home", "/"), (title.split("|")[0].split(":")[0].strip(), path)]))
    faq = faq_from_html(html)
    if faq and robots != "noindex":
        ld.append(faq_ld(faq))
    html = re.sub(r"<title>.*?</title>", "<title>%s</title>" % esc(title), html, count=1, flags=re.S)
    html = re.sub(r'<meta name="description" content="[^"]*">', '<meta name="description" content="%s">' % esc(desc), html, count=1)
    html = html.replace("<!--SEO:TYPES-->", types_block()).replace("<!--SEO:THEMES-->", themes_block())
    return html.replace("</head>", head_tags(title, desc, path, robots=robots, jsonld=ld) + "\n</head>", 1)


# ---------------------------------------------------------------- shared blocks
def types_block() -> str:
    links = "".join('<a class="card linkcard" href="/qr/%s"><b>%s</b><span class="small muted">%s</span></a>' % (t["slug"], esc(t["h1"]), esc(t["desc"][:92] + "…")) for t in TYPES)
    return '<section class="section"><h2>Make a QR for anything</h2><div class="feat">%s</div></section>' % links


def themes_block() -> str:
    th = engine.builtin_themes()
    links = " · ".join('<a href="/themes/%s">%s</a>' % (esc(k), esc(v["name"])) for k, v in th.items())
    return '<section class="section"><h2>All poster themes</h2><p class="muted">%s</p></section>' % links


def shell(title, desc, path, body, jsonld=(), image=None, robots="index", og_type="website") -> str:
    return finalize("""<!doctype html>
<html lang="en-IN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>%s</title>
<meta name="description" content="%s">
<meta name="theme-color" content="#05060d" media="(prefers-color-scheme: dark)"><meta name="theme-color" content="#e9edf8" media="(prefers-color-scheme: light)">
<link rel="icon" href="/assets/img/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/assets/css/app.css">
<script src="/assets/js/theme.js"></script>
%s
</head>
<body>
<header id="nav"></header>
<main class="wrap">
%s
</main>
<footer id="footer"></footer>
<script src="/assets/js/app.js"></script>
</body>
</html>
""" % (esc(title), esc(desc), head_tags(title, desc, path, image, robots, jsonld, og_type), body))


def _list(items, tag="ul"):
    return "<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % esc(i) for i in items), tag)


def _faq_html(pairs):
    return '<div class="faq">%s</div>' % "".join("<details><summary>%s</summary><p>%s</p></details>" % (esc(q), esc(a)) for q, a in pairs)


def _related(slugs):
    out = []
    for s in slugs:
        if s in TYPE_BY_SLUG:
            out.append('<a href="/qr/%s">%s</a>' % (s, esc(TYPE_BY_SLUG[s]["h1"])))
        elif s in GUIDE_BY_SLUG:
            out.append('<a href="/guides/%s">%s</a>' % (s, esc(GUIDE_BY_SLUG[s]["title"])))
    return '<p class="muted">Related: %s</p>' % " · ".join(out) if out else ""


# ---------------------------------------------------------------- landing pages
def type_html(slug):
    t = TYPE_BY_SLUG.get(slug)
    if not t:
        return None
    path = "/qr/" + slug
    pairs = list(t["faq"])
    body = ('<nav class="small muted" aria-label="Breadcrumb"><a href="/">Home</a> / <a href="/qr">QR codes</a> / %s</nav>' % esc(t["name"]) +
            '<h1 class="h1s">%s</h1>' % esc(t["h1"]) + "".join('<p class="prose muted">%s</p>' % esc(p) for p in t["intro"]) +
            '<p class="pad"><a class="btn lg" href="/studio?type=%s">Make your %s now</a> <span class="small muted">Free preview. Pay only to download.</span></p>' % (t["kind"], esc(t["name"])) +
            '<section class="section"><h2>How to make it</h2>%s</section>' % _list(t["steps"], "ol") +
            '<section class="section"><h2>Where people use it</h2>%s</section>' % _list(t["uses"]) +
            '<section class="section"><h2>Tips for a QR that scans every time</h2>%s</section>' % _list(t["tips"]) +
            '<section class="section"><h2>Questions</h2>%s</section>' % _faq_html(pairs) +
            '<section class="section"><div class="card"><h3>Poster themes for %s</h3><p class="muted">Pick from 18 built-in themes or upload your own artwork. The preview is free, and a scan check tells you the final code will read. <a href="/themes">Browse themes</a> or see <a href="/pricing">pricing</a>.</p></div></section>' % esc(t["name"].lower()) +
            _related(t["related"]))
    ld = [crumbs([("Home", "/"), ("QR codes", "/qr"), (t["name"], path)]), faq_ld(pairs),
          {"@context": "https://schema.org", "@type": "HowTo", "name": t["h1"], "step": [{"@type": "HowToStep", "position": i + 1, "text": s} for i, s in enumerate(t["steps"])]}]
    return shell(t["title"], t["desc"], path, body, ld)


def qr_index_html():
    body = ('<h1 class="h1s">QR code generators</h1><p class="prose muted">Pick what your QR should do. Every type turns into a printable poster in the style you choose, with a free preview and a scan check.</p>' + types_block() + _related(["qr-code-size-and-printing-guide"]))
    return shell("QR Code Generators for UPI, Wi-Fi, WhatsApp and More | QR Studio", "All QR types in one place: UPI payment, Wi-Fi, WhatsApp, Instagram, YouTube, Maps, contact, email, SMS, phone, Telegram and links.", "/qr", body,
                 [crumbs([("Home", "/"), ("QR codes", "/qr")])])


def guide_html(slug):
    g = GUIDE_BY_SLUG.get(slug)
    if not g:
        return None
    path = "/guides/" + slug
    secs = "".join('<section class="section"><h2>%s</h2>%s</section>' % (esc(h), "".join('<p class="prose muted">%s</p>' % esc(p) for p in ps)) for h, ps in g["sections"])
    body = ('<nav class="small muted"><a href="/">Home</a> / <a href="/guides">Guides</a></nav><h1 class="h1s">%s</h1><p class="prose muted">%s</p>' % (esc(g["title"]), esc(g["desc"])) + secs +
            '<p class="pad"><a class="btn lg" href="/studio">Open the Studio</a></p>' + _related(g["related"]))
    ld = [crumbs([("Home", "/"), ("Guides", "/guides"), (g["title"], path)]),
          {"@context": "https://schema.org", "@type": "Article", "headline": g["title"], "description": g["desc"], "author": {"@type": "Organization", "name": "TeamDev"},
           "publisher": {"@type": "Organization", "name": "TeamDev", "logo": {"@type": "ImageObject", "url": base() + "/assets/img/icon-512.png"}}, "mainEntityOfPage": base() + path,
           "dateModified": time.strftime("%Y-%m-%d")}]
    return shell(g["title"] + " | QR Studio", g["desc"], path, body, ld, og_type="article")


def guides_index_html():
    links = "".join('<a class="card linkcard" href="/guides/%s"><b>%s</b><span class="small muted">%s</span></a>' % (g["slug"], esc(g["title"]), esc(g["desc"])) for g in GUIDES)
    body = '<h1 class="h1s">QR code guides</h1><p class="prose muted">Short, practical guides for shops, cafes and creators.</p><section class="section"><div class="feat">%s</div></section>' % links
    return shell("QR Code Guides for Shops, Cafes and Creators | QR Studio", "Practical guides: UPI QR for shops, Wi-Fi QR for cafes, QR size and printing.", "/guides", body, [crumbs([("Home", "/"), ("Guides", "/guides")])])


CAT_TEXT = {"Calm": "soft gradients that feel relaxed, good for cafes, studios and clinics", "Energy": "bold, high contrast colour that grabs attention at a counter",
            "Shop": "friendly shop-counter styling with a clear Scan to Pay feel", "Retro": "neon grids and synth colours with a gaming and music feel",
            "Festive": "warm festive colours for sale season and celebrations", "Soft": "gentle colours for boutiques, home businesses and creators",
            "Minimal": "clean, quiet design that lets the QR and your name stand out", "Cafe & Wi-Fi": "built for Wi-Fi posters and cafe tables"}


def theme_html(tid):
    th = engine.builtin_themes().get(tid)
    if not th:
        return None
    path = "/themes/" + tid
    cat = th.get("category", "")
    blurb = CAT_TEXT.get(cat, "a poster style for your QR")
    title = "%s QR Poster Theme: %s Style | QR Studio" % (th["name"], cat)
    desc = "%s is a %s QR poster theme with %s. Try it with your own UPI, link or Wi-Fi details for free." % (th["name"], cat.lower(), blurb)
    img = "%s/api/themes/%s/thumb" % (base(), tid)
    others = [(k, v) for k, v in engine.builtin_themes().items() if v.get("category") == cat and k != tid][:4]
    more = ('<p class="muted">More %s themes: %s</p>' % (esc(cat.lower()), " · ".join('<a href="/themes/%s">%s</a>' % (esc(k), esc(v["name"])) for k, v in others))) if others else ""
    body = ('<nav class="small muted"><a href="/">Home</a> / <a href="/themes">Themes</a> / %s</nav><div class="grid2"><div><img class="themepic" src="/api/themes/%s/thumb" alt="%s QR poster theme preview" width="369" height="553" loading="eager"></div>'
            '<div><h1 class="h1s">%s</h1><p class="prose muted">%s is a %s theme: %s.</p><p class="prose muted">Use it for UPI payment posters, Wi-Fi posters, link, WhatsApp and Instagram QR codes. The preview is free and shows a scan check, and you pay only to download the clean file.</p>'
            '<p class="pad"><a class="btn lg" href="/studio?theme=%s">Use this theme</a> <a class="btn ghost" href="/themes">All themes</a></p>%s</div></div>' % (esc(th["name"]), esc(tid), esc(th["name"]), esc(th["name"]), esc(th["name"]), esc(cat.lower()), esc(blurb), esc(tid), more) +
            _related(["upi-qr-code-poster", "wifi-qr-code-generator"]))
    return shell(title, desc, path, body, [crumbs([("Home", "/"), ("Themes", "/themes"), (th["name"], path)])], image=img)


def share_html(r, token):
    design = json.loads(r["design"])
    title = "%s | Poster made with QR Studio" % (r["title"] or "QR poster")
    desc = "A QR poster made with QR Studio. Make your own UPI, Wi-Fi, WhatsApp or link QR poster in minutes. Free preview."
    img = "%s/api/p/%s.jpg" % (base(), token)
    body = ('<div class="grid2"><div><img class="themepic" src="/api/p/%s.jpg" alt="QR poster preview" width="640" height="960"></div><div><h1 class="h1s">%s</h1>'
            '<p class="prose muted">This is a shared preview. The QR in a preview is scrambled on purpose, so it does not scan.</p>'
            '<p class="prose muted">Want a poster like this for your own %s?</p><p class="pad"><a class="btn lg" href="/studio?type=%s">Make yours free</a></p></div></div>' %
            (esc(token), esc(r["title"] or "QR poster"), esc(design.get("kind", "QR")), esc(design.get("kind", "upi"))))
    return shell(title, desc, "/p/" + token, body, image=img, robots="noindex")


def not_found_html():
    return shell("Page not found | QR Studio", "This page does not exist.", "/404", '<h1 class="h1s">Page not found</h1><p class="muted">The page may have moved. <a href="/">Go to the home page</a> or <a href="/qr">browse QR types</a>.</p>', robots="noindex")


# ---------------------------------------------------------------- sitemap, robots, manifest
def sitemap_xml() -> str:
    today = time.strftime("%Y-%m-%d")
    fe = config.frontend_dir()
    urls = []
    for path, (t, d, robots, s) in STATIC.items():
        if robots == "noindex":
            continue
        name = "index.html" if path == "/" else path.strip("/") + ".html"
        f = fe / name
        lm = time.strftime("%Y-%m-%d", time.gmtime(f.stat().st_mtime)) if f.exists() else today
        urls.append((path, lm, "1.0" if path == "/" else "0.8" if path in ("/studio", "/themes", "/pricing") else "0.5"))
    urls += [("/qr", today, "0.8"), ("/guides", today, "0.6")]
    urls += [("/qr/" + t["slug"], today, "0.9") for t in TYPES]
    urls += [("/guides/" + g["slug"], today, "0.6") for g in GUIDES]
    urls += [("/themes/" + k, today, "0.5") for k in engine.builtin_themes()]
    b = base()
    return ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
            "".join("<url><loc>%s%s</loc><lastmod>%s</lastmod><priority>%s</priority></url>" % (b, esc(p), lm, pr) for p, lm, pr in urls) + "</urlset>")


def robots_txt() -> str:
    return ("User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /admin\nDisallow: /dashboard\nDisallow: /receipt\nDisallow: /r/\nDisallow: /p/\nDisallow: /login\nDisallow: /signup\n\nSitemap: %s/sitemap.xml\n" % base())


def manifest() -> dict:
    return {"name": "QR Studio by TeamDev", "short_name": "QR Studio", "description": "Make your QR as a poster.", "start_url": "/studio", "scope": "/", "display": "standalone",
            "background_color": "#05060d", "theme_color": "#05060d", "lang": "en-IN",
            "icons": [{"src": "/assets/img/icon-192.png", "sizes": "192x192", "type": "image/png"}, {"src": "/assets/img/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}
