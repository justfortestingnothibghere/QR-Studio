(async function () {
  await QS.ready;
  if (!QS.requireLogin()) return;
  const { $, $$, api } = QS;
  const cv = $("#cv"), cx = cv.getContext("2d");
  const BOX = { A: [298, 633, 428, 433], B: [297, 750, 428, 424], C: [262, 430, 500, 500] };
  const S = { tpl: "A", img: null, file: null };

  const tplBox = $("#tpl");
  function paintTpl() { $$("button", tplBox).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === S.tpl))); $("#place").classList.toggle("hide", S.tpl !== "D"); }
  tplBox.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.tpl = b.dataset.v; paintTpl(); draw(); });
  paintTpl();
  ["qs", "qx", "qy", "accent"].forEach((id) => $("#" + id).addEventListener("input", draw));

  $("#img").addEventListener("change", (e) => {
    const f = e.target.files[0]; if (!f) return;
    S.file = f;
    const im = new Image();
    im.onload = () => { S.img = im; draw(); };
    im.onerror = () => { QS.toast("That file is not a readable image", "bad"); S.img = null; draw(); };
    im.src = URL.createObjectURL(f);
  });

  function rr(x, y, w, h, r) { cx.beginPath(); cx.moveTo(x + r, y); cx.arcTo(x + w, y, x + w, y + h, r); cx.arcTo(x + w, y + h, x, y + h, r); cx.arcTo(x, y + h, x, y, r); cx.arcTo(x, y, x + w, y, r); cx.closePath(); }
  function draw() {
    const W = cv.width, H = cv.height, k = W / 1024;
    cx.clearRect(0, 0, W, H);
    if (S.img) {
      const s = Math.max(W / S.img.width, H / S.img.height), w = S.img.width * s, h = S.img.height * s;
      cx.drawImage(S.img, (W - w) / 2, (H - h) / 2, w, h);
    } else { const g = cx.createLinearGradient(0, 0, 0, H); g.addColorStop(0, "#0d0f1e"); g.addColorStop(1, "#1b1f3a"); cx.fillStyle = g; cx.fillRect(0, 0, W, H); cx.fillStyle = "#8f98c8"; cx.font = "600 16px Inter,sans-serif"; cx.textAlign = "center"; cx.fillText("Choose an image to start", W / 2, H / 2 - 160); }
    let b;
    if (S.tpl === "D") { const s = +$("#qs").value, x = Math.min(+$("#qx").value, 1024 - s), y = Math.min(+$("#qy").value, 1536 - s); b = [x, y, s, s]; } else b = BOX[S.tpl];
    const acc = $("#accent").value;
    if (S.tpl === "A" || S.tpl === "C") { const pad = S.tpl === "A" ? 28 : 28; cx.fillStyle = "rgba(4,2,8,.9)"; cx.strokeStyle = acc; cx.lineWidth = 2; rr((b[0] - pad) * k, (b[1] - pad - (S.tpl === "A" ? 42 : 0)) * k, (b[2] + pad * 2) * k, (b[3] + pad * 2 + (S.tpl === "A" ? 134 : 0)) * k, 18 * k); cx.fill(); cx.stroke(); }
    cx.fillStyle = "#fff"; rr(b[0] * k, b[1] * k, b[2] * k, b[3] * k, 14 * k); cx.fill();
    cx.fillStyle = "#111"; const m = 10 * k, n = 9, cs = (b[2] * k - m * 2) / n;
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) if ((i * 7 + j * 3 + i * j) % 3 === 0 || (i < 3 && j < 3) || (i > 5 && j < 3) || (i < 3 && j > 5)) { cx.fillRect(b[0] * k + m + i * cs, b[1] * k + m + j * cs, cs - 1, cs - 1); }
    cx.fillStyle = "#fff"; cx.font = "700 " + (S.tpl === "B" ? 34 : 22) + "px Poppins,sans-serif"; cx.textAlign = "center";
    if (S.tpl === "B") { cx.fillStyle = $("#ink").value; cx.fillText("Your Name", W / 2, 620 * k); }
    if (S.tpl === "C") { cx.fillStyle = $("#ink").value; cx.fillText("Your Name", W / 2, 1040 * k); }
  }
  ["ink", "soft"].forEach((id) => $("#" + id).addEventListener("input", draw));
  draw();

  $("#f").addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("#msg"), btn = $("#go");
    msg.className = "msg"; msg.textContent = "";
    if (!S.file) { msg.className = "msg bad"; msg.textContent = "Choose an image first."; return; }
    if (!$("#own").checked) { msg.className = "msg bad"; msg.textContent = "Please confirm you have the right to use this artwork."; return; }
    const fd = new FormData();
    fd.append("image", S.file); fd.append("name", $("#name").value); fd.append("tpl", S.tpl);
    ["accent", "ink", "soft"].forEach((k) => fd.append(k, $("#" + k).value));
    if (S.tpl === "D") { fd.append("qx", $("#qx").value); fd.append("qy", $("#qy").value); fd.append("qs", $("#qs").value); }
    btn.disabled = true; msg.textContent = "Uploading…";
    try { const d = await api("/api/themes/upload", { form: fd }); location.href = "/studio?theme=" + encodeURIComponent(d.theme.id); }
    catch (err) { msg.className = "msg bad"; msg.textContent = err.message; btn.disabled = false; }
  });
})();
