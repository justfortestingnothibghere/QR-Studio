/* Studio: live server-rendered preview (always watermarked), save, price, unlock. */
(async function () {
  await QS.ready;
  const { $, $$, api, esc, toast } = QS;
  const qs = new URLSearchParams(location.search);

  const INKS = ["#0b0b10", "#10206b", "#7c0d1f", "#0b4d2e", "#4a1d96"];
  const S = {
    kind: "upi", f: { upi_id: "yourname@upi", amount: "", note: "", url: "https://teamdev.sbs", text: "Hello from QR Studio", ssid: "HomeNet", wpass: "", wenc: "WPA", phone: "", email: "", wa_phone: "919876543210", wa_msg: "", ig: "yourname", yt: "@yourchannel", mq: "Your shop, your city", em_to: "you@example.com", em_sub: "", em_msg: "", sms_phone: "919876543210", sms_msg: "", ph_phone: "919876543210", tg: "yourname" },
    name: QS.user ? QS.user.name : "Your Name", title: "Your Pocket UPI QR", tag: "SCAN · PAY · DONE",
    dot: "dot", ink: INKS[0], logo: "letter", logo_id: "", dynamic: false, theme_id: qs.get("theme") || "crimson-surge", print: false, qr_id: null, order: null, themes: [], logos: [],
  };

  const FIELD_MAP = { upi_id: "upi_id", amount: "amount", note: "note", url: "url", text: "text", ssid: "ssid", password: "wpass", enc: "wenc", phone: "phone", email: "email" };
  function fieldsFor(k) {
    const f = S.f;
    if (k === "upi") return { upi_id: f.upi_id, amount: f.amount, note: f.note };
    if (k === "url") return { url: f.url };
    if (k === "text") return { text: f.text };
    if (k === "wifi") return { ssid: f.ssid, password: f.wpass, enc: f.wenc };
    if (k === "whatsapp") return { phone: f.wa_phone, message: f.wa_msg };
    if (k === "instagram") return { handle: f.ig };
    if (k === "youtube") return { url: f.yt };
    if (k === "maps") return { query: f.mq };
    if (k === "email") return { to: f.em_to, subject: f.em_sub, message: f.em_msg };
    if (k === "sms") return { phone: f.sms_phone, message: f.sms_msg };
    if (k === "phone") return { phone: f.ph_phone };
    if (k === "telegram") return { handle: f.tg };
    return { phone: f.phone, email: f.email };
  }
  const design = () => ({ kind: S.kind, fields: fieldsFor(S.kind), name: S.name, title: S.title, tag: S.tag, dynamic: S.kind === "url" && S.dynamic, style: { dot: S.dot, ink: S.ink, logo: S.logo, logo_id: S.logo_id } });

  // ---------- bind inputs ----------
  const bindIds = { upi_id: "upi_id", amount: "amount", note: "note", url: "url", text: "text", ssid: "ssid", wpass: "wpass", wenc: "wenc", phone: "phone", email: "email" };
  Object.entries(bindIds).forEach(([k, id]) => { const el = $("#" + id); el.value = S.f[k]; el.addEventListener("input", () => { S.f[k] = el.value; changed(); }); });
  [["name", "name"], ["title", "title"], ["tag", "tag"]].forEach(([k, id]) => { const el = $("#" + id); el.value = S[k]; el.addEventListener("input", () => { S[k] = el.value; changed(); }); });
  $("#dynamic").addEventListener("change", (e) => { S.dynamic = e.target.checked; changed(); });
  $("#printPack").addEventListener("change", (e) => { S.print = e.target.checked; quote(); });

  function seg(id, key, after) {
    const g = $("#" + id);
    const paint = () => $$("button", g).forEach((b) => b.setAttribute("aria-pressed", String(S[key] === b.dataset.v)));
    g.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S[key] = b.dataset.v; paint(); if (after) after(); changed(); });
    paint();
    return paint;
  }
  const TITLES = { upi: "Your Pocket UPI QR", url: "Scan to open", text: "Scan to read", wifi: "Scan to join Wi-Fi", contact: "Scan to save contact", whatsapp: "Chat on WhatsApp", instagram: "Follow on Instagram", youtube: "Watch on YouTube", maps: "Find us on Maps", email: "Scan to email us", sms: "Scan to text us", phone: "Scan to call", telegram: "Chat on Telegram" };
  S.autoTitle = S.title;
  if (KIND_PRESET()) S.kind = KIND_PRESET();
  function KIND_PRESET() { const t = qs.get("type"); return t && TITLES[t] ? t : ""; }
  const paintKind = seg("kind", "kind", syncKind);
  seg("dot", "dot");
  const paintLogo = seg("logo", "logo", syncLogo);

  function syncKind() {
    $$("[data-k]").forEach((el) => el.classList.toggle("hide", el.dataset.k !== S.kind));
    if (S.title === S.autoTitle) { S.title = TITLES[S.kind] || S.title; S.autoTitle = S.title; const t = $("#title"); if (t) t.value = S.title; }
    $("#dynRow").classList.toggle("hide", S.kind !== "url");
    $("#title").parentElement.classList.toggle("hide", false);
    if (S.kind !== "url") S.dynamic = false;
  }
  function syncLogo() {
    $("#logoBox").classList.toggle("hide", S.logo !== "image");
    if (S.logo === "image") loadLogos();
  }
  syncKind(); syncLogo();

  // ink swatches
  const inkBox = $("#ink");
  INKS.forEach((c) => { const b = document.createElement("button"); b.type = "button"; b.style.background = c; b.setAttribute("aria-label", "Ink " + c); b.dataset.v = c; b.setAttribute("aria-pressed", String(c === S.ink)); inkBox.appendChild(b); });
  inkBox.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.ink = b.dataset.v; $$("button", inkBox).forEach((x) => x.setAttribute("aria-pressed", String(x === b))); changed(); });

  // tabs
  $("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $$("#tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    $$("[data-pane]").forEach((p) => p.classList.toggle("hide", p.dataset.pane !== b.dataset.tab));
    if (b.dataset.tab === "export") quote();
  });

  // ---------- themes ----------
  async function loadThemes() {
    const d = await api("/api/themes");
    S.themes = d.themes;
    if (!S.themes.find((t) => t.id === S.theme_id)) S.theme_id = S.themes[0].id;
    const box = $("#themes"); box.innerHTML = "";
    S.themes.forEach((t) => {
      const b = document.createElement("button"); b.type = "button"; b.dataset.id = t.id; b.setAttribute("aria-pressed", String(t.id === S.theme_id));
      b.innerHTML = '<img loading="lazy" alt="" src="/api/themes/' + encodeURIComponent(t.id) + '/thumb">' + esc(t.name);
      b.onclick = () => { S.theme_id = t.id; $$("#themes button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); changed(); };
      box.appendChild(b);
    });
  }

  // ---------- logos ----------
  async function loadLogos() {
    const list = $("#logoList"); list.innerHTML = "";
    if (!QS.user) { list.innerHTML = '<span class="small muted"><a href="/login?next=/studio">Log in</a> to upload a logo.</span>'; return; }
    try {
      const d = await api("/api/logos"); S.logos = d.logos;
      d.logos.forEach((id) => {
        const b = document.createElement("button"); b.type = "button"; b.setAttribute("aria-pressed", String(id === S.logo_id));
        b.innerHTML = '<img alt="logo" width="34" height="34" src="/api/logos/' + id + '">';
        b.onclick = () => { S.logo_id = id; $$("#logoList button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); changed(); };
        list.appendChild(b);
      });
      if (!S.logo_id && d.logos[0]) { S.logo_id = d.logos[0]; list.firstChild && list.firstChild.setAttribute("aria-pressed", "true"); changed(); }
    } catch (e) { /* ignore */ }
  }
  $("#logoFile").addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f) return;
    if (!QS.requireLogin()) return;
    const fd = new FormData(); fd.append("image", f);
    try { const d = await api("/api/logos/upload", { form: fd }); S.logo_id = d.logo_id; toast("Logo added", "ok"); await loadLogos(); changed(); } catch (err) { toast(err.message, "bad"); }
    e.target.value = "";
  });

  // ---------- preview ----------
  const pv = $("#pv"), busy = $("#busy"), err = $("#err");
  QS.shield($("#shield")); QS.shield(pv);
  let timer = null, ctl = null, lastUrl = null, seq = 0;
  function changed() { clearTimeout(timer); timer = setTimeout(render, 320); S.qr_dirty = true; }
  async function render() {
    const my = ++seq;
    if (ctl) ctl.abort(); ctl = new AbortController();
    busy.classList.remove("hide");
    try {
      const res = await fetch("/api/preview", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ theme_id: S.theme_id, design: design() }), signal: ctl.signal });
      if (my !== seq) return;
      if (!res.ok) { let m = "Could not render"; try { m = (await res.json()).error || m; } catch (e) { /* ignore */ } err.textContent = m; setChip($("#chipScan"), "bad", "Fix the details to preview"); return; }
      err.textContent = "";
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      pv.src = url; if (lastUrl) URL.revokeObjectURL(lastUrl); lastUrl = url;
      const ok = res.headers.get("X-Scan-OK") === "1";
      setChip($("#chipScan"), ok ? "ok" : "bad", ok ? "Scan check passed" : "May not scan. Try black ink or no logo");
    } catch (e) { if (e.name !== "AbortError") err.textContent = "Network problem while rendering."; }
    finally { if (my === seq) busy.classList.add("hide"); }
    quote();
  }
  function setChip(el, kind, text) { el.className = "chip " + kind; el.textContent = text; }

  // ---------- price ----------
  let qTimer = null;
  function quote() {
    clearTimeout(qTimer);
    qTimer = setTimeout(async () => {
      try {
        const d = await api("/api/quote", { json: { theme_id: S.theme_id, design: design(), print: S.print } });
        $("#priceList").innerHTML = d.items.map((i) => "<li><span>" + esc(i.label) + "</span><b>₹" + i.rupees + "</b></li>").join("");
        $("#priceTotal").textContent = d.pass_active ? "₹0 (your pass)" : "₹" + d.rupees + (d.raw > d.rupees ? " (capped)" : "");
        $("#printPrice").textContent = (QS.cfg.pricing || {}).print || 10;
      } catch (e) { /* design invalid: leave as is */ }
    }, 150);
  }

  // ---------- save + unlock ----------
  const smsg = $("#saveMsg");
  const say = (k, t) => { smsg.className = "msg " + k; smsg.textContent = t; };
  async function save() {
    if (!QS.requireLogin()) return null;
    const d = await api("/api/qrs", { json: { id: S.qr_id, theme_id: S.theme_id, design: design(), title: S.name || "Untitled QR" } });
    S.qr_id = d.id; S.qr_dirty = false; history.replaceState(null, "", "/studio?qr=" + d.id);
    return d.id;
  }
  $("#saveBtn").onclick = async () => { try { if (await save()) say("ok", "Saved. Find it in My QRs."); } catch (e) { say("bad", e.message); } };
  $("#unlockBtn").onclick = async () => {
    try {
      const id = await save(); if (!id) return;
      say("", "Creating your order…");
      const d = await api("/api/orders", { json: { kind: "export", qr_id: id, print: S.print } });
      S.order = d.order; say("", "");
      QSPay.mount($("#payArea"), d.order, {});
      $("#payArea").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) { say("bad", e.message); }
  };

  if (QS.user && QS.user.credits > 0) { $("#creditRow").classList.remove("hide"); $("#creditN").textContent = QS.user.credits; }
  $("#creditBtn").onclick = async () => {
    try {
      const id = await save(); if (!id) return;
      const d = await api("/api/orders", { json: { kind: "export", qr_id: id, print: S.print, use_credit: true } });
      S.order = d.order; await QS.load();
      QSPay.mount($("#payArea"), d.order, {});
      $("#creditRow").classList.add("hide");
    } catch (e) { say("bad", e.message); }
  };

  // ---------- load existing ----------
  async function openSaved(id) {
    const d = await api("/api/qrs");
    const q = d.qrs.find((x) => String(x.id) === String(id));
    if (!q) return;
    const de = q.design;
    S.qr_id = q.id; S.kind = de.kind; S.name = de.name; S.title = de.title; S.tag = de.tag; S.dot = de.style.dot; S.ink = de.style.ink; S.logo = de.style.logo; S.logo_id = de.style.logo_id || "";
    S.dynamic = de.dynamic; S.theme_id = q.theme_id;
    const f = de.fields;
    Object.assign(S.f, { upi_id: f.upi_id || S.f.upi_id, amount: f.amount || "", note: f.note || "", url: f.url || S.f.url, text: f.text || S.f.text, ssid: f.ssid || S.f.ssid, wpass: f.password || "", wenc: f.enc || "WPA", phone: f.phone || "", email: f.email || "" });
    if (de.kind === "whatsapp") Object.assign(S.f, { wa_phone: f.phone || "", wa_msg: f.message || "" });
    if (de.kind === "instagram") S.f.ig = f.handle || "";
    if (de.kind === "youtube") S.f.yt = f.url || "";
    if (de.kind === "maps") S.f.mq = f.query || "";
    if (de.kind === "email") Object.assign(S.f, { em_to: f.to || "", em_sub: f.subject || "", em_msg: f.message || "" });
    if (de.kind === "sms") Object.assign(S.f, { sms_phone: f.phone || "", sms_msg: f.message || "" });
    if (de.kind === "phone") S.f.ph_phone = f.phone || "";
    if (de.kind === "telegram") S.f.tg = f.handle || "";
    S.autoTitle = null;
    Object.entries(bindIds).forEach(([k, i]) => { $("#" + i).value = S.f[k]; });
    ["name", "title", "tag"].forEach((k) => { $("#" + k).value = S[k]; });
    $("#dynamic").checked = S.dynamic;
    if (!INKS.includes(S.ink)) { const b = document.createElement("button"); b.type = "button"; b.style.background = S.ink; b.dataset.v = S.ink; inkBox.appendChild(b); }
    $$("button", inkBox).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === S.ink)));
    paintKind(); paintLogo(); syncKind(); syncLogo();
    $$("#dot button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === S.dot)));
  }

  await loadThemes();
  if (qs.get("qr") && QS.user) await openSaved(qs.get("qr"));
  $$("#themes button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.id === S.theme_id)));
  render();
  if (qs.get("order") && QS.user) {
    try { const d = await api("/api/orders/" + qs.get("order")); $$("#tabs button")[2].click(); QSPay.mount($("#payArea"), d.order, {}); } catch (e) { /* ignore */ }
  }
})();
