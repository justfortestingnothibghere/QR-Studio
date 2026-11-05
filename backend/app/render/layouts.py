"""Poster layout templates shared by the built-in theme generator and user theme maker."""


def layout(kind, t):
    acc = t["acc"]
    soft = t.get("soft", "#ffffff")
    ink = t.get("ink", "#ffffff")
    if kind == "A":
        return {
            "qr": {"x": 298, "y": 633, "w": 428, "h": 433, "r": 26},
            "frame": {"x": 270, "y": 562, "w": 484, "h": 636, "r": 36},
            "texts": [
                {"key": "title", "x": 512, "y": 598, "size": 34, "font": "script", "color": ink, "maxw": 330, "rules": [292, 732]},
                {"key": "idline", "x": 512, "y": 1100, "size": 25, "font": "mono", "color": soft, "maxw": 420},
                {"key": "tag", "x": 512, "y": 1148, "size": 21, "font": "mono", "color": acc, "maxw": 300, "rules": [300, 724]},
            ]}
    if kind == "B":
        return {
            "qr": {"x": 297, "y": 750, "w": 428, "h": 424, "r": 26},
            "texts": [
                {"key": "name", "x": 512, "y": 620, "size": 150, "font": "script", "color": ink, "maxw": 640, "baseline": "s", "glow": 26, "swoosh": 44, "crown": 88},
                {"key": "idline", "x": 512, "y": 1212, "size": 25, "font": "mono", "color": soft, "maxw": 440},
                {"key": "tag", "x": 512, "y": 1256, "size": 21, "font": "mono", "color": acc, "maxw": 340},
            ]}
    return {
        "qr": {"x": 262, "y": 430, "w": 500, "h": 500, "r": 30},
        "texts": [
            {"key": "title", "x": 512, "y": 372, "size": 40, "font": "script", "color": ink, "maxw": 380, "rules": [262, 762]},
            {"key": "name", "x": 512, "y": 1040, "size": 110, "font": "script", "color": ink, "maxw": 640, "baseline": "s", "glow": 22, "swoosh": 40},
            {"key": "idline", "x": 512, "y": 1128, "size": 26, "font": "mono", "color": soft, "maxw": 460},
            {"key": "tag", "x": 512, "y": 1176, "size": 22, "font": "mono", "color": acc, "maxw": 340, "rules": [262, 762]},
        ]}
