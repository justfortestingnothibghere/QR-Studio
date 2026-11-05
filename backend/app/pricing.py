from . import config


def breakdown(design: dict, theme: dict, print_pack: bool = False):
    """Returns (items, rupees). Price follows what the poster uses, capped."""
    p = config.get("pricing", {})
    items = [("HD export (PNG, JPG, PDF)", p.get("base", 29))]
    if design["style"]["logo"] != "none":
        items.append(("Centre logo", p.get("logo", 10)))
    if not theme.get("builtin"):
        items.append(("Your own theme", p.get("custom_theme", 20)))
    if design.get("dynamic"):
        items.append(("Scan counter and editable link", p.get("dynamic", 30)))
    if print_pack:
        items.append(("Print pack (SVG and transparent PNG of the QR)", p.get("print", 10)))
    raw = sum(i[1] for i in items)
    cap = p.get("cap", 99)
    return items, min(raw, cap), raw
