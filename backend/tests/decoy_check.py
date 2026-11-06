"""Proves unpaid previews cannot be scanned (screenshots are useless) while the paid export can. Run: python3 tests/decoy_check.py"""
import glob, os, sys
from io import BytesIO
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cv2, numpy as np
from PIL import Image
from app import uploads
from app.render import engine

ids = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(os.path.dirname(__file__), "../assets/themes/*.json")))
design = {"kind": "upi", "fields": {"upi_id": "yourname@upi"}, "name": "Arman Khan", "title": "T", "tag": "x", "dynamic": False,
          "style": {"dot": "dot", "ink": "#0b0b10", "logo": "letter", "logo_id": ""}}
payload = "upi://pay?pa=yourname@upi&pn=Arman%20Khan&cu=INR"
w = cv2.wechat_qrcode_WeChatQRCode()
bad = n = 0
for i in ids:
    th = uploads.get_theme(i, None)
    for dot in ("dot", "square", "round"):
        design["style"]["dot"] = dot
        n += 1
        b = BytesIO(); engine.render_poster(th, design, payload, 0.625, True, None, "user 1").save(b, "JPEG", quality=70)
        arr = cv2.cvtColor(np.array(Image.open(BytesIO(b.getvalue()))), cv2.COLOR_RGB2BGR)
        r, _ = w.detectAndDecode(arr); r2, _, _ = cv2.QRCodeDetector().detectAndDecode(arr)
        if (r and any(r)) or r2:
            bad += 1; print("READABLE:", i, dot)
real = engine.render_poster(uploads.get_theme(ids[0], None), design, payload, 2.0, False, None)
ok = w.detectAndDecode(cv2.cvtColor(np.array(real), cv2.COLOR_RGB2BGR))[0] == (payload,)
print("decoys readable: %d of %d | paid export readable: %s" % (bad, n, ok))
sys.exit(1 if bad or not ok else 0)
