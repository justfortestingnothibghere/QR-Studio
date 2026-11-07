(async function () {
  await QS.ready;
  if (!QS.requireLogin()) return;
  const { $, $$, api, esc, rs, date, toast } = QS;

  const KIND = { upi: "UPI", url: "Link", text: "Text", wifi: "Wi-Fi", contact: "Contact", whatsapp: "WhatsApp", instagram: "Instagram", youtube: "YouTube", maps: "Maps", email: "Email", sms: "SMS", phone: "Call", telegram: "Telegram" };
  let qrs = [], orders = [], themes = [];

  function tab(name) {
    $$("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
    $$("[data-pane]").forEach((p) => p.classList.toggle("hide", p.dataset.pane !== name));
    if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  }
  $("#tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) tab(b.dataset.tab); });

  async function load() {
    const [a, b, c] = await Promise.all([api("/api/qrs"), api("/api/orders"), api("/api/themes")]);
    qrs = a.qrs; orders = b.orders; themes = c.themes;
    stats(); drawQrs(); drawOrders(); drawThemes(); drawPass();
  }

  function stats() {
    const paid = orders.filter((o) => o.status === "paid" && o.kind === "export").length;
    const scans = qrs.reduce((n, q) => n + (q.scans || 0), 0);
    const u = QS.user;
    $("#stats").innerHTML =
      '<div class="card"><b>' + qrs.length + "</b><span>Saved QRs</span></div>" +
      '<div class="card"><b>' + paid + "</b><span>Paid downloads</span></div>" +
      '<div class="card"><b>' + scans + "</b><span>Dynamic scans</span></div>" +
      '<div class="card"><b>' + (u.pass_active ? "Active" : "None") + "</b><span>Unlimited pass</span></div>";
  }

  const themeName = (id) => (themes.find((t) => t.id === id) || { name: "Removed theme" }).name;
  const latestPaid = (qid) => orders.find((o) => o.qr_id === qid && o.status === "paid" && o.kind === "export");

  function drawQrs() {
    const g = $("#qgrid"); g.innerHTML = "";
    $("#qempty").classList.toggle("hide", qrs.length > 0);
    qrs.forEach((q) => {
      const paid = latestPaid(q.id);
      const el = document.createElement("div"); el.className = "card qcard";
      el.innerHTML =
        "<h3>" + esc(q.title) + '</h3><div class="row"><span class="chip">' + esc(KIND[q.design.kind] || q.design.kind) + '</span><span class="chip">' + esc(themeName(q.theme_id)) + "</span>" +
        (paid ? '<span class="chip ok">Paid</span>' : '<span class="chip warn">Draft</span>') +
        (q.slug ? '<span class="chip ' + (q.dyn_active ? "ok" : "") + '">' + (q.dyn_active ? q.scans + " scans" : "Dynamic · inactive") + "</span>" : "") +
        '</div><p class="small muted">Updated ' + esc(date(q.updated)) + "</p>" +
        '<div class="row"><a class="btn sm" href="/studio?qr=' + q.id + '">Edit</a>' +
        (paid ? '<a class="btn ghost sm" href="/api/orders/' + paid.id + '/download/png">PNG</a><a class="btn ghost sm" href="/api/orders/' + paid.id + '/download/pdf">PDF</a>' : "") +
        '<button class="btn ghost sm" type="button" data-share>Share preview</button><button class="btn danger sm" type="button" data-del>Delete</button></div>' +
        (q.slug && q.dyn_active ? '<div class="verify"><input type="url" value="' + esc(q.design.fields.url || "") + '" aria-label="Destination link"><button class="btn ghost sm" type="button" data-target>Update link</button></div>' : "");
      const del = el.querySelector("[data-del]");
      let armed = false;
      del.onclick = async () => {
        if (!armed) { armed = true; del.textContent = "Tap again to delete"; setTimeout(() => { armed = false; del.textContent = "Delete"; }, 3000); return; }
        try { await api("/api/qrs/" + q.id, { method: "DELETE" }); toast("Deleted", "ok"); load(); } catch (e) { toast(e.message, "bad"); }
      };
      el.querySelector("[data-share]").onclick = async () => {
        if (!confirm("Anyone with the link can see this poster preview, including the name and details printed on it (the QR itself is scrambled). Create the link?")) return;
        try {
          const r = await api("/api/qrs/" + q.id + "/share", { json: {} });
          if (navigator.share) { try { await navigator.share({ title: q.title, url: r.url }); return; } catch (e) { /* fall back to copy */ } }
          try { await navigator.clipboard.writeText(r.url); toast("Link copied", "ok"); } catch (e) { prompt("Copy this link", r.url); }
        } catch (e) { toast(e.message, "bad"); }
      };
      const tb = el.querySelector("[data-target]");
      if (tb) tb.onclick = async () => { try { await api("/api/qrs/" + q.id + "/target", { json: { url: el.querySelector("input").value } }); toast("Link updated. Your printed QR now opens it.", "ok"); } catch (e) { toast(e.message, "bad"); } };
      g.appendChild(el);
    });
  }

  function drawOrders() {
    const body = $("#obody"); body.innerHTML = "";
    if (!orders.length) { body.innerHTML = '<tr><td colspan="6" class="muted">No orders yet.</td></tr>'; return; }
    orders.forEach((o) => {
      const tr = document.createElement("tr");
      const chip = { paid: "ok", pending: "warn", expired: "bad", unpaid: "bad" }[o.status] || "";
      let act = "";
      if (o.status === "paid" && o.kind === "export") act = '<a class="btn ghost sm" href="/api/orders/' + o.id + '/download/png">PNG</a> <a class="btn ghost sm" href="/api/orders/' + o.id + '/download/pdf">PDF</a>';
      if (o.status === "paid" && o.amount_paise) act += ' <a class="btn ghost sm" href="/receipt?id=' + o.id + '">Receipt</a>';
      if (o.status === "pending" && o.kind === "export") act = '<a class="btn sm" href="/studio?qr=' + o.qr_id + "&order=" + o.id + '">Continue</a>';
      tr.innerHTML = '<td class="mono">' + esc(o.id) + "</td><td>" + esc(o.label || (o.kind === "pass" ? "Pass" : "")) + "</td><td>" + (o.amount_paise ? esc(rs(o.amount_paise)) : "Pass") + '</td><td><span class="chip ' + chip + '">' + esc(o.status) + "</span></td><td>" + esc(date(o.created)) + "</td><td>" + act + "</td>";
      body.appendChild(tr);
    });
  }

  function drawThemes() {
    const mine = themes.filter((t) => t.mine);
    const g = $("#mythemes"); g.innerHTML = "";
    $("#tempty").classList.toggle("hide", mine.length > 0);
    mine.forEach((t) => {
      const d = document.createElement("div");
      d.innerHTML = '<img loading="lazy" alt="' + esc(t.name) + '" src="/api/themes/' + encodeURIComponent(t.id) + '/thumb"><span class="tcard"><span>' + esc(t.name) + '</span></span><div class="row"><a class="btn sm" href="/studio?theme=' + encodeURIComponent(t.id) + '">Use</a><button class="btn danger sm" type="button">Delete</button></div>';
      let armed = false; const b = d.querySelector("button");
      b.onclick = async () => {
        if (!armed) { armed = true; b.textContent = "Tap again"; setTimeout(() => { armed = false; b.textContent = "Delete"; }, 3000); return; }
        try { await api("/api/themes/" + t.id, { method: "DELETE" }); toast("Theme deleted", "ok"); load(); } catch (e) { toast(e.message, "bad"); }
      };
      g.appendChild(d);
    });
    const add = document.createElement("a"); add.className = "card"; add.href = "/theme-maker"; add.innerHTML = "<h3>+ New theme</h3><p class='muted small'>Upload your own artwork.</p>"; g.appendChild(add);
  }

  function drawPass() {
    const u = QS.user, p = QS.cfg.pricing || {};
    $("#passText").textContent = u.pass_active
      ? "Your pass is active until " + new Date(u.pass_until * 1000).toLocaleDateString([], { day: "2-digit", month: "long", year: "numeric" }) + ". Every download is free until then."
      : "₹" + p.pass_price + " for " + p.pass_days + " days of unlimited HD downloads, dynamic links and print packs.";
    const box = $("#passPay"); box.innerHTML = "";
    const b = document.createElement("button"); b.className = "btn blue"; b.type = "button"; b.textContent = u.pass_active ? "Extend the pass" : "Get the pass · ₹" + p.pass_price;
    b.onclick = async () => {
      b.disabled = true;
      try { const d = await api("/api/orders", { json: { kind: "pass" } }); const holder = document.createElement("div"); box.innerHTML = ""; box.appendChild(holder); QSPay.mount(holder, d.order, { onPaid: () => { load(); } }); } catch (e) { toast(e.message, "bad"); b.disabled = false; }
    };
    box.appendChild(b);
  }

  // invite and review
  let stars = 0;
  async function drawInvite() {
    try {
      const r = await api("/api/referral"), s = r.stats;
      $("#invRule").textContent = r.rule;
      $("#invLink").value = r.link;
      const msg = "Make a UPI / Wi-Fi / WhatsApp QR poster in minutes with QR Studio: " + r.link;
      $("#invWa").href = "https://wa.me/?text=" + encodeURIComponent(msg);
      $("#invTg").href = "https://t.me/share/url?url=" + encodeURIComponent(r.link) + "&text=" + encodeURIComponent("Make a QR poster with QR Studio");
      if (navigator.share) { const n = $("#invNative"); n.classList.remove("hide"); n.onclick = () => navigator.share({ title: "QR Studio", text: msg, url: r.link }).catch(() => {}); }
      $("#invCopy").onclick = async () => { try { await navigator.clipboard.writeText(r.link); toast("Invite link copied", "ok"); } catch (e) { $("#invLink").select(); } };
      const c = s.current;
      $("#invText").textContent = s.available > 0 ? "You have " + s.available + " free download" + (s.available > 1 ? "s" : "") + " ready. Use it in the Studio." : "Friends joined: " + c.joined + " of " + s.per_group + ". Friends who paid: " + c.paid + ".";
      $("#invBar").style.width = Math.min(100, Math.round((c.complete ? 100 : (c.joined / s.per_group) * 60 + (c.paid ? 40 : 0)))) + "%";
      $("#invSub").textContent = "Total earned: " + s.earned + " · used: " + s.used + ". A friend counts when they pay for a download.";
      $("#invFriends").innerHTML = s.friends.map((f) => "<div>" + esc(f.name) + ' — <span class="chip ' + (f.paid ? "ok" : "warn") + '">' + (f.paid ? "paid" : "joined") + "</span></div>").join("");
    } catch (e) { /* ignore */ }
    try {
      const m = await api("/api/reviews/mine");
      if (m.can_review) {
        $("#revCard").classList.remove("hide");
        if (m.review) { stars = m.review.stars; $("#revText").value = m.review.text; $("#revMsg").textContent = m.review.status === "approved" ? "Published, thank you!" : "Received. It will show after a quick check."; }
        paintStars();
      }
    } catch (e) { /* ignore */ }
  }
  function paintStars() {
    const box = $("#stars"); box.innerHTML = "";
    for (let i = 1; i <= 5; i++) { const b = document.createElement("button"); b.type = "button"; b.textContent = "★"; b.setAttribute("aria-label", i + " stars"); if (i <= stars) b.className = "on"; b.onclick = () => { stars = i; paintStars(); }; box.appendChild(b); }
  }
  $("#revGo").onclick = async () => {
    const m = $("#revMsg");
    try { await api("/api/reviews", { json: { stars, text: $("#revText").value } }); m.className = "msg ok"; m.textContent = "Thank you! It will show after a quick check."; }
    catch (e) { m.className = "msg bad"; m.textContent = e.message; }
  };

  // account
  $("#pwForm").addEventListener("submit", async (e) => {
    e.preventDefault(); const m = $("#pwMsg");
    try { await api("/api/password", { json: { old: $("#oldpw").value, new: $("#newpw").value } }); m.className = "msg ok"; m.textContent = "Password updated. Other devices were logged out."; $("#oldpw").value = $("#newpw").value = ""; }
    catch (err) { m.className = "msg bad"; m.textContent = err.message; }
  });
  $("#delForm").addEventListener("submit", async (e) => {
    e.preventDefault(); const m = $("#delMsg");
    try { await api("/api/account/delete", { json: { password: $("#delpw").value } }); location.href = "/"; }
    catch (err) { m.className = "msg bad"; m.textContent = err.message; }
  });

  await load(); drawInvite();
  const h = location.hash.slice(1);
  if (["qrs", "orders", "themes", "invite", "pass", "account"].includes(h)) tab(h);
})();
