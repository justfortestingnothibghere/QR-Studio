(async function () {
  await QS.ready;
  if (!QS.requireLogin()) return;
  if (!QS.user.admin) { location.replace("/"); return; }
  const { $, $$, api, esc, rs, date, toast } = QS;
  const panel = $("#panel"), dlg = $("#dlg"), dlgBody = $("#dlgBody");
  const inr = (r) => "₹" + Number(r).toLocaleString("en-IN");
  const chip = (s) => '<span class="chip ' + ({ paid: "ok", pending: "warn", expired: "bad", unpaid: "bad" }[s] || "") + '">' + esc(s) + "</span>";
  const ago = (t) => { if (!t) return "never"; const s = Math.max(0, Date.now() / 1000 - t); return s < 90 ? Math.round(s) + "s ago" : s < 5400 ? Math.round(s / 60) + " min ago" : s < 129600 ? Math.round(s / 3600) + " h ago" : date(t); };
  const table = (heads, rows, empty) => '<div class="card tablewrap"><table><thead><tr>' + heads.map((h) => "<th>" + h + "</th>").join("") + "</tr></thead><tbody>" +
    (rows.length ? rows.join("") : '<tr><td colspan="' + heads.length + '" class="muted">' + (empty || "Nothing here yet.") + "</td></tr>") + "</tbody></table></div>";
  const modal = (html) => { dlgBody.innerHTML = html; if (!dlg.open) dlg.showModal(); const c = dlgBody.querySelector("[data-close]"); if (c) c.onclick = () => dlg.close(); return dlgBody; };
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
  const guard = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message, "bad"); } };

  function pager(host, d, go) {
    const pages = Math.max(1, Math.ceil(d.total / d.per));
    host.innerHTML = '<span>' + d.total + ' total · page ' + d.page + " of " + pages + '</span><button class="btn ghost sm" data-p="-1"' + (d.page <= 1 ? " disabled" : "") + '>Prev</button><button class="btn ghost sm" data-p="1"' + (d.page >= pages ? " disabled" : "") + ">Next</button>";
    $$("button", host).forEach((b) => (b.onclick = () => go(d.page + Number(b.dataset.p))));
  }
  function bars(host, series, cls, fmt) {
    const max = Math.max(1, ...series.map((s) => s.v));
    host.innerHTML = series.map((s) => '<i class="' + cls + '" data-t="' + esc(s.day + ": " + fmt(s.v)) + '"></i>').join("");
    $$("i", host).forEach((el, i) => { el.style.height = "2%"; requestAnimationFrame(() => requestAnimationFrame(() => { el.style.height = Math.max(2, Math.round((series[i].v / max) * 100)) + "%"; })); });
  }

  // ------------------------------------------------------------------ overview
  async function overview() {
    panel.innerHTML = '<p class="muted">Loading…</p>';
    const [d, sy] = await Promise.all([api("/api/admin/stats"), api("/api/admin/system")]);
    const s = d.stats, sys = sy.system, im = s.imap;
    const imapAge = im.last_ok ? Date.now() / 1000 - im.last_ok : 1e9;
    const mailOk = im.enabled && imapAge < 180 && !im.last_error;
    const checks = [
      [sys.mode === "live", "Payments are in live mode"],
      [sys.upi_ready, "UPI ID is set (" + esc(sys.upi_ready ? sys.upi_id : "not set") + ")"],
      [mailOk, "Mailbox reader is running (" + (im.enabled ? "last check " + ago(im.last_ok) : "off") + ")"],
      [sys.volume, "A Volume is attached (data survives redeploys)"],
      [(sys.admin_emails || []).length > 0, "Admin email is set"],
      [/^https:/.test(sys.public_url || ""), "Site address uses https"]
    ];
    const cards = [["Today", inr(s.revenue_today)], ["Last 7 days", inr(s.revenue_7d)], ["Last 30 days", inr(s.revenue_30d)], ["All time", inr(s.revenue)],
      ["Users", s.users + (s.new_today ? " (+" + s.new_today + ")" : "")], ["Paid orders", s.paid_orders], ["Open orders", s.pending], ["Active passes", s.active_pass],
      ["Saved QRs", s.qrs], ["QR scans", s.scans], ["Downloads", s.downloads], ["Unmatched payments", s.unclaimed_payments], ["Failed checks 24h", s.failed_verifies_24h]];
    panel.innerHTML =
      (s.warnings.length ? '<div class="alert pad">' + s.warnings.map((w) => "<div>• " + esc(w) + "</div>").join("") + "</div><br>" : "") +
      '<div class="stat" id="cards"></div>' +
      '<div class="grid2"><div class="card"><h3>Revenue, last 14 days</h3><div class="bars" id="bRev"></div><div class="barlab"><span>' + esc(d.revenue_series[0].day) + "</span><span>today</span></div></div>" +
      '<div class="card"><h3>New users, last 14 days</h3><div class="bars" id="bSign"></div><div class="barlab"><span>' + esc(d.signup_series[0].day) + "</span><span>today</span></div></div></div><br>" +
      '<div class="grid2"><div class="card"><h3>Go-live checklist</h3><ul class="checklist" id="chk"></ul></div>' +
      '<div class="card"><h3>Payment mailbox</h3><p class="small muted">' + (im.enabled ? (mailOk ? '<span class="chip ok">connected</span> ' : '<span class="chip bad">problem</span> ') : '<span class="chip bad">off</span> ') +
      "Last OK " + esc(ago(im.last_ok)) + ". Emails seen " + im.seen + ", payments stored " + im.stored + ", rejected " + im.rejected + (im.last_error ? ". Error: " + esc(im.last_error) : "") + '.</p><p class="pad"><button class="btn ghost sm" id="pollNow" type="button">Check mailbox now</button></p></div></div><br>' +
      '<div class="grid2"><div class="card"><h3>Popular themes</h3><ul class="price pad">' + (d.top_themes.map((t) => "<li><span>" + esc(t.theme_id) + "</span><b>" + t.n + "</b></li>").join("") || '<li class="muted">No saved QRs yet.</li>') + "</ul></div>" +
      '<div class="card"><h3>Orders by status</h3><ul class="price pad">' + (d.order_status.map((t) => "<li><span>" + chip(t.status) + "</span><b>" + t.n + "</b></li>").join("") || '<li class="muted">No orders yet.</li>') + "</ul></div></div>";
    const host = $("#cards");
    cards.forEach(([a, b]) => { const c = document.createElement("div"); c.className = "card"; c.innerHTML = "<b></b><span>" + esc(a) + "</span>"; const bEl = c.firstChild; host.appendChild(c); const m = /^₹?([\d,]+)/.exec(String(b)); if (m && /^₹?[\d,]+$/.test(String(b))) QS.countUp(bEl, Number(m[1].replace(/,/g, "")), (v) => (String(b)[0] === "₹" ? "₹" : "") + v.toLocaleString("en-IN")); else bEl.textContent = b; });
    $("#chk").innerHTML = checks.map(([ok, t]) => '<li class="' + (ok ? "" : "bad-item") + '">' + (ok ? "" : "✗ ") + t + "</li>").join("");
    bars($("#bRev"), d.revenue_series, "r", inr); bars($("#bSign"), d.signup_series, "", (v) => v + " users");
    $("#pollNow").onclick = guard(async (e) => { e.currentTarget.disabled = true; const r = await api("/api/admin/mailbox/poll", { json: {} }); toast("Mailbox checked. " + r.new + " new payment(s).", "ok"); overview(); });
  }

  // ------------------------------------------------------------------ orders
  const ordersState = { q: "", status: "", kind: "", page: 1 };
  async function orders() {
    panel.innerHTML = '<div class="toolbar"><input id="oq" type="text" placeholder="Search order, email, UTR, amount" aria-label="Search orders"><select id="os" aria-label="Status"><option value="">All statuses</option><option>pending</option><option>paid</option><option>unpaid</option><option>expired</option></select><select id="ok" aria-label="Kind"><option value="">All kinds</option><option value="export">Poster</option><option value="pass">Pass</option><option value="test">Payment test</option></select></div><div id="ol"></div><div class="pager" id="op"></div>';
    $("#oq").value = ordersState.q; $("#os").value = ordersState.status; $("#ok").value = ordersState.kind;
    let tm; $("#oq").oninput = () => { clearTimeout(tm); tm = setTimeout(() => { ordersState.q = $("#oq").value; ordersState.page = 1; loadOrders(); }, 300); };
    $("#os").onchange = () => { ordersState.status = $("#os").value; ordersState.page = 1; loadOrders(); };
    $("#ok").onchange = () => { ordersState.kind = $("#ok").value; ordersState.page = 1; loadOrders(); };
    await loadOrders();
  }
  const loadOrders = guard(async function () {
    const p = new URLSearchParams({ q: ordersState.q, status: ordersState.status, kind: ordersState.kind, page: ordersState.page });
    const d = await api("/api/admin/orders?" + p);
    $("#ol").innerHTML = table(["Order", "User", "What", "Amount", "Status", "Reference", "Created", ""],
      d.orders.map((o) => '<tr><td class="mono">' + esc(o.id) + "</td><td>" + esc(o.email) + "</td><td>" + esc(o.kind === "pass" ? "Pass" : o.kind === "test" ? "Test" : o.label || "Poster") + "</td><td>" + (o.amount_paise ? esc(rs(o.amount_paise)) : "Free") + "</td><td>" + chip(o.status) + '</td><td class="mono">' + esc(o.utr || "") + "</td><td>" + esc(date(o.created)) +
        '</td><td><div class="row-actions"><button class="btn ghost sm" data-v="' + esc(o.id) + '" type="button">View</button>' +
        (o.status === "paid" ? '<button class="btn danger sm" data-u="' + esc(o.id) + '" type="button">Mark unpaid</button>' : '<button class="btn sm" data-p="' + esc(o.id) + '" type="button">Mark paid</button>') + "</div></td></tr>"), "No orders match.");
    $$("[data-v]", $("#ol")).forEach((b) => (b.onclick = () => orderView(b.dataset.v)));
    $$("[data-p]", $("#ol")).forEach((b) => (b.onclick = () => orderSet(b.dataset.p, "paid")));
    $$("[data-u]", $("#ol")).forEach((b) => (b.onclick = () => orderSet(b.dataset.u, "unpaid")));
    pager($("#op"), d, (pg) => { ordersState.page = pg; loadOrders(); });
  });
  function orderSet(id, want) {
    const m = modal("<h3>Mark " + esc(id) + " as " + want + "?</h3><p class=\"muted\">" + (want === "paid" ? "This unlocks what the customer bought (downloads, pass days, dynamic link) as if the payment matched." : "This takes the purchase back: downloads stop, pass days are removed, and the payment can be matched again.") + "</p>" +
      (want === "paid" ? '<label for="mRef">UTR or Transaction ID (optional, links the payment so it cannot be reused)</label><input id="mRef" type="text" maxlength="40" autocomplete="off">' : "") +
      '<label for="mNote">Note for the activity log</label><input id="mNote" type="text" maxlength="200" placeholder="Why?"><div class="actions pad"><button class="btn ' + (want === "paid" ? "" : "danger") + '" id="mGo" type="button">Confirm</button><button class="btn ghost" data-close type="button">Cancel</button></div><p class="msg" id="mMsg"></p>');
    $("#mGo", m).onclick = async () => {
      try { await api("/api/admin/orders/" + id + "/status", { json: { status: want, note: $("#mNote", m).value, utr: want === "paid" ? $("#mRef", m).value : "" } }); dlg.close(); toast("Order marked " + want, "ok"); loadOrders(); }
      catch (e) { const x = $("#mMsg", m); x.className = "msg bad"; x.textContent = e.message; }
    };
  }
  const orderView = guard(async function (id) {
    const d = await api("/api/admin/orders/" + id), o = d.order, p = d.payment;
    modal('<h3>Order ' + esc(o.id) + "</h3><dl class=\"kv\"><dt>User</dt><dd>" + esc(o.email) + "</dd><dt>Status</dt><dd>" + chip(o.status) + "</dd><dt>Amount</dt><dd>" + esc(rs(o.amount_paise)) + "</dd><dt>What</dt><dd>" + esc(o.label || o.kind) + "</dd><dt>Created</dt><dd>" + esc(date(o.created)) + "</dd><dt>Expires</dt><dd>" + esc(date(o.expires)) + "</dd><dt>Paid</dt><dd>" + (o.paid_at ? esc(date(o.paid_at)) : "-") + "</dd><dt>Reference</dt><dd class=\"mono\">" + esc(o.utr || "-") + "</dd>" +
      (p ? "<dt>Payment</dt><dd>" + esc(rs(p.amount_paise)) + " from " + esc(p.payer || "?") + " via " + esc(p.source) + ", received " + esc(date(p.received_at)) + (p.txn_id ? ", Txn " + esc(p.txn_id) : "") + "</dd>" : "") + "</dl>" +
      "<h3>Trail</h3><ul class=\"timeline\">" + (d.events.map((e) => "<li><b>" + esc(date(e.ts)) + "</b> " + esc(e.kind) + " · " + esc(e.actor) + (e.ip ? " · " + esc(e.ip) : "") + "<br><span class=\"muted\">" + esc(e.detail || "") + "</span></li>").join("") || '<li class="muted">No events.</li>') + "</ul>" +
      (d.downloads.length ? "<h3>Downloads</h3><p class=\"small muted\">" + d.downloads.map((x) => esc(x.fmt + " " + date(x.ts))).join(" · ") + "</p>" : "") + '<div class="actions"><button class="btn ghost" data-close type="button">Close</button></div>');
  });

  // ------------------------------------------------------------------ payments
  const payState = { q: "", only: "", page: 1 };
  async function payments() {
    panel.innerHTML = '<div class="toolbar"><input id="pq2" type="text" placeholder="Search UTR, Transaction ID, payer, amount" aria-label="Search payments"><select id="po" aria-label="Filter"><option value="">All payments</option><option value="unclaimed">Not matched to an order</option></select></div><div id="pl"></div><div class="pager" id="pp"></div>' +
      '<section class="section"><h2>Add a payment by hand</h2><p class="muted">Use this if a payment email never arrived. If exactly one open order has that amount it unlocks at once, otherwise the customer claims it with the reference.</p>' +
      '<form id="payForm" class="verify pad" novalidate><input id="aUtr" type="text" maxlength="40" placeholder="UTR or Transaction ID" aria-label="Reference"><input id="aAmt" type="number" step="0.01" min="0" placeholder="Amount ₹" aria-label="Amount"><button class="btn" type="submit">Add payment</button></form><p class="msg" id="aMsg" role="status"></p></section>';
    $("#pq2").value = payState.q; $("#po").value = payState.only;
    let tm; $("#pq2").oninput = () => { clearTimeout(tm); tm = setTimeout(() => { payState.q = $("#pq2").value; payState.page = 1; loadPay(); }, 300); };
    $("#po").onchange = () => { payState.only = $("#po").value; payState.page = 1; loadPay(); };
    $("#payForm").addEventListener("submit", async (e) => {
      e.preventDefault(); const m = $("#aMsg");
      try { await api("/api/admin/payments", { json: { utr: $("#aUtr").value, amount: $("#aAmt").value } }); m.className = "msg ok"; m.textContent = "Payment added."; $("#aUtr").value = $("#aAmt").value = ""; loadPay(); }
      catch (err) { m.className = "msg bad"; m.textContent = err.message; }
    });
    await loadPay();
  }
  const loadPay = guard(async function () {
    const d = await api("/api/admin/payments?" + new URLSearchParams({ q: payState.q, only: payState.only, page: payState.page }));
    $("#pl").innerHTML = table(["Reference", "Txn ID", "Amount", "Payer", "Source", "Used by", "Received", ""],
      d.payments.map((p) => '<tr><td class="mono">' + esc(p.utr) + '</td><td class="mono">' + esc(p.txn_id || "") + "</td><td>" + esc(rs(p.amount_paise)) + "</td><td>" + esc(p.payer || "") + "</td><td>" + esc(p.source) + '</td><td class="mono">' + (p.claimed_by ? esc(p.claimed_by) : '<span class="chip warn">unmatched</span>') + "</td><td>" + esc(date(p.received_at)) + "</td><td>" + (p.claimed_by ? "" : '<button class="btn danger sm" data-d="' + esc(p.utr) + '" type="button">Delete</button>') + "</td></tr>"), "No payments yet.");
    $$("[data-d]", $("#pl")).forEach((b) => (b.onclick = guard(async () => { if (!confirm("Delete this unmatched payment?")) return; await api("/api/admin/payments/" + encodeURIComponent(b.dataset.d), { method: "DELETE" }); loadPay(); })));
    pager($("#pp"), d, (pg) => { payState.page = pg; loadPay(); });
  });

  // ------------------------------------------------------------------ users
  const userState = { q: "", page: 1 };
  async function users() {
    panel.innerHTML = '<div class="toolbar"><input id="uq" type="text" placeholder="Search email or name" aria-label="Search users"></div><div id="ul"></div><div class="pager" id="up"></div>';
    $("#uq").value = userState.q; let tm;
    $("#uq").oninput = () => { clearTimeout(tm); tm = setTimeout(() => { userState.q = $("#uq").value; userState.page = 1; loadUsers(); }, 300); };
    await loadUsers();
  }
  const loadUsers = guard(async function () {
    const d = await api("/api/admin/users?" + new URLSearchParams({ q: userState.q, page: userState.page }));
    const now = Date.now() / 1000;
    $("#ul").innerHTML = table(["User", "Joined", "QRs", "Paid", "Spent", "Pass", ""],
      d.users.map((u) => "<tr><td>" + esc(u.email) + '<br><span class="small muted">' + esc(u.name) + (u.is_admin ? " · admin" : "") + (u.banned ? ' · <span class="chip bad">banned</span>' : "") + "</span></td><td>" + esc(date(u.created)) + "</td><td>" + u.qrs + "</td><td>" + u.paid_orders + "</td><td>" + inr(u.spent) + "</td><td>" + (u.pass_until > now ? "until " + esc(date(u.pass_until)) : "") +
        '</td><td><div class="row-actions"><button class="btn ' + (u.banned ? "ghost" : "danger") + ' sm" data-b="' + u.id + '" data-s="' + (u.banned ? 0 : 1) + '" type="button">' + (u.banned ? "Unban" : "Ban") + '</button><button class="btn ghost sm" data-g="' + u.id + '" type="button">+30d pass</button>' + (u.pass_until > now ? '<button class="btn ghost sm" data-r="' + u.id + '" type="button">Revoke</button>' : "") + '<button class="btn ghost sm" data-w="' + u.id + '" data-e="' + esc(u.email) + '" type="button">Password</button></div></td></tr>'), "No users match.");
    const h = $("#ul");
    $$("[data-b]", h).forEach((b) => (b.onclick = guard(async () => { await api("/api/admin/users/" + b.dataset.b + "/ban", { json: { banned: b.dataset.s === "1" } }); loadUsers(); })));
    $$("[data-g]", h).forEach((b) => (b.onclick = guard(async () => { await api("/api/admin/users/" + b.dataset.g + "/pass", { json: { days: 30 } }); toast("30 days added", "ok"); loadUsers(); })));
    $$("[data-r]", h).forEach((b) => (b.onclick = guard(async () => { if (!confirm("Remove this user's pass?")) return; await api("/api/admin/users/" + b.dataset.r + "/pass", { json: { revoke: true } }); loadUsers(); })));
    $$("[data-w]", h).forEach((b) => (b.onclick = () => {
      const m = modal("<h3>Set a new password</h3><p class=\"muted\">For " + esc(b.dataset.e) + ". They are logged out everywhere. Tell them the password privately and ask them to change it.</p><label for=\"npw\">New password</label><input id=\"npw\" type=\"text\" autocomplete=\"off\" minlength=\"8\"><div class=\"actions pad\"><button class=\"btn\" id=\"npGo\" type=\"button\">Set password</button><button class=\"btn ghost\" data-close type=\"button\">Cancel</button></div><p class=\"msg\" id=\"npMsg\"></p>");
      $("#npGo", m).onclick = async () => { try { await api("/api/admin/users/" + b.dataset.w + "/password", { json: { password: $("#npw", m).value } }); dlg.close(); toast("Password changed", "ok"); } catch (e) { const x = $("#npMsg", m); x.className = "msg bad"; x.textContent = e.message; } };
    }));
    pager($("#up"), d, (pg) => { userState.page = pg; loadUsers(); });
  });

  // ------------------------------------------------------------------ QRs
  const qrState = { q: "", page: 1 };
  async function qrs() {
    panel.innerHTML = '<div class="toolbar"><input id="qq" type="text" placeholder="Search title, owner or short code" aria-label="Search QRs"></div><div id="ql"></div><div class="pager" id="qp"></div>';
    $("#qq").value = qrState.q; let tm;
    $("#qq").oninput = () => { clearTimeout(tm); tm = setTimeout(() => { qrState.q = $("#qq").value; qrState.page = 1; loadQrs(); }, 300); };
    await loadQrs();
  }
  const loadQrs = guard(async function () {
    const d = await api("/api/admin/qrs?" + new URLSearchParams({ q: qrState.q, page: qrState.page }));
    $("#ql").innerHTML = table(["Title", "Owner", "Type", "Theme", "Dynamic", "Scans", "Updated", ""],
      d.qrs.map((r) => "<tr><td>" + esc(r.title) + "</td><td>" + esc(r.email) + "</td><td>" + esc(r.kind || "") + '</td><td class="mono">' + esc(r.theme_id) + "</td><td>" + (r.slug ? (r.dyn_active ? '<a href="/r/' + esc(r.slug) + '" target="_blank" rel="noopener">/r/' + esc(r.slug) + "</a>" : '<span class="muted">inactive</span>') : "") + "</td><td>" + r.scans + "</td><td>" + esc(date(r.updated)) + '</td><td><button class="btn danger sm" data-d="' + r.id + '" type="button">Delete</button></td></tr>'), "No QRs yet.");
    $$("[data-d]", $("#ql")).forEach((b) => (b.onclick = guard(async () => { if (!confirm("Delete this QR for the user? Dynamic links stop working.")) return; await api("/api/admin/qrs/" + b.dataset.d, { method: "DELETE" }); loadQrs(); })));
    pager($("#qp"), d, (pg) => { qrState.page = pg; loadQrs(); });
  });

  // ------------------------------------------------------------------ payment test
  async function test() {
    const [sy, st] = await Promise.all([api("/api/admin/system"), api("/api/admin/stats")]);
    const sys = sy.system, im = st.stats.imap;
    const pre = [
      [sys.mode === "live", "Live mode is on" + (sys.mode === "live" ? "" : " (mock mode: use the Simulate button inside the test)")],
      [sys.upi_ready, "Receiving UPI ID: " + (sys.upi_ready ? sys.upi_id : "not set")],
      [im.enabled, "Mailbox reader: " + (im.enabled ? "on, last check " + ago(im.last_ok) : "off. Set GMAIL_USER and GMAIL_APP_PASSWORD")],
      [(sys.sender_domains || []).length > 0, "Trusted sender domain: " + esc((sys.sender_domains || []).join(", ")) + (sys.require_dkim ? " (DKIM must pass)" : " (DKIM check off)")]
    ];
    panel.innerHTML = '<div class="grid2"><div class="card"><h3>Test the whole payment flow</h3><p class="muted">Creates a test order for any amount, with no minimum and no maximum. You pay it from your own Fam, the Fam email is read from Gmail and matched exactly like a customer payment. Test orders never count as revenue.</p>' +
      '<ul class="checklist pad">' + pre.map(([ok, t]) => "<li class=\"" + (ok ? "" : "bad-item") + "\">" + (ok ? "" : "✗ ") + t + "</li>").join("") + "</ul>" +
      '<form id="tForm" class="verify pad" novalidate><input id="tAmt" type="number" step="0.01" min="0.01" placeholder="Amount ₹ (any)" aria-label="Test amount" value="1.00"><button class="btn" type="submit">Start test</button></form><p class="small muted pad">Fam to Fam transfers with no UTR work too: the amount matches by itself.</p><p class="msg" id="tMsg"></p></div>' +
      '<div class="card"><h3>What the mailbox read last</h3><div id="lastPay" class="small"></div><p class="pad"><button class="btn ghost sm" id="pollNow" type="button">Check mailbox now</button></p></div></div><div class="card hide" id="tPay"></div><section class="section"><h2>Earlier tests</h2><div id="tList"></div></section>';
    $("#tForm").addEventListener("submit", async (e) => {
      e.preventDefault(); const m = $("#tMsg"); m.className = "msg"; m.textContent = "";
      try { const d = await api("/api/admin/test-order", { json: { amount: $("#tAmt").value } }); QSPay.mount($("#tPay"), d.order, { onPaid: () => { toast("Payment flow works", "ok"); loadTests(); lastPay(); } }); $("#tPay").scrollIntoView({ behavior: "smooth", block: "nearest" }); }
      catch (err) { m.className = "msg bad"; m.textContent = err.message; }
    });
    $("#pollNow").onclick = guard(async (e) => { e.currentTarget.disabled = true; const r = await api("/api/admin/mailbox/poll", { json: {} }); toast("Checked. " + r.new + " new payment(s).", "ok"); e.currentTarget.disabled = false; lastPay(); });
    async function lastPay() {
      const d = await api("/api/admin/payments?page=1");
      $("#lastPay").innerHTML = d.payments.slice(0, 5).map((p) => "<div><b>" + esc(rs(p.amount_paise)) + "</b> from " + esc(p.payer || "?") + ' · <span class="mono">' + esc(p.utr) + "</span> · " + esc(ago(p.received_at)) + (p.claimed_by ? " · " + esc(p.claimed_by) : ' · <span class="chip warn">unmatched</span>') + "</div>").join("") || '<span class="muted">No payment email has been read yet. Pay a test order, then press Check mailbox now.</span>';
    }
    async function loadTests() {
      const d = await api("/api/admin/orders?kind=test");
      $("#tList").innerHTML = table(["Order", "Amount", "Status", "Reference", "Created"], d.orders.slice(0, 10).map((o) => '<tr><td class="mono">' + esc(o.id) + "</td><td>" + esc(rs(o.amount_paise)) + "</td><td>" + chip(o.status) + '</td><td class="mono">' + esc(o.utr || "") + "</td><td>" + esc(date(o.created)) + "</td></tr>"), "No tests yet.");
    }
    lastPay(); loadTests();
  }

  // ------------------------------------------------------------------ backup
  async function backup() {
    const sy = (await api("/api/admin/system")).system;
    const mb = (b) => (b / 1048576).toFixed(b > 1048576 * 10 ? 0 : 1) + " MB";
    panel.innerHTML = '<div class="grid2"><div class="card"><h3>Download a full backup</h3><p class="muted">One zip with the whole database (users, QRs, orders, payments, settings) plus uploaded logos and custom themes. Posters are rebuilt on demand, so they are not included. The zip holds password hashes: keep it private.</p>' +
      '<p class="pad"><a class="btn" href="/api/admin/backup" download>Download backup</a></p><p class="small muted pad">Now: database ' + mb(sy.db_bytes) + ", logos " + mb(sy.logos_bytes) + ", custom themes " + mb(sy.themes_bytes) + ".</p></div>" +
      '<div class="card"><h3>Restore from a backup</h3><p class="muted">Replaces the live data with the backup. A safety copy of what is live now is kept first. Everyone, including you, is logged out afterwards: log in again with your old account.</p>' +
      '<form id="rForm" class="stack pad" novalidate><div><label for="rFile">Backup file (.zip, or a .db file)</label><input id="rFile" type="file" accept=".zip,.db,application/zip"></div><div><label for="rConf">Type RESTORE to confirm</label><input id="rConf" type="text" autocomplete="off"></div><div><label for="rPw">Your admin password</label><input id="rPw" type="password" autocomplete="current-password"></div><div><button class="btn danger" type="submit">Restore now</button></div></form><p class="msg" id="rMsg" role="status"></p></div></div>' +
      '<section class="section"><h2>Moving to a new Railway account</h2><ol class="muted"><li>Download a backup here.</li><li>Deploy the same GitHub repo on the new account, add a Volume at /data and the same Variables.</li><li>Sign up on the new site with your admin email, open Admin, Backup, and restore the zip.</li><li>Log in with your old password. Everything is back.</li></ol></section>' +
      '<section class="section"><h2>Automatic copies on the server</h2><p class="muted">A daily database copy is kept in the data folder (last 7). It protects against mistakes, not against losing the Volume, so still download a backup now and then.</p><div class="card"><ul class="price pad">' +
      (sy.snapshots.map((s) => "<li><span class=\"mono\">" + esc(s.name) + "</span><b>" + mb(s.bytes) + "</b></li>").join("") || '<li class="muted">The first copy appears within an hour.</li>') + "</ul></div></section>";
    $("#rForm").addEventListener("submit", async (e) => {
      e.preventDefault(); const m = $("#rMsg"), f = $("#rFile").files[0];
      if (!f) { m.className = "msg bad"; m.textContent = "Choose a backup file first."; return; }
      const fd = new FormData(); fd.append("file", f); fd.append("confirm", $("#rConf").value); fd.append("password", $("#rPw").value);
      m.className = "msg"; m.textContent = "Restoring… this can take a minute.";
      try { const r = await api("/api/admin/restore", { form: fd }); m.className = "msg ok"; m.textContent = "Restored: " + r.counts.users + " users, " + r.counts.qrs + " QRs, " + r.counts.orders + " orders. Taking you to the login page…"; setTimeout(() => (location.href = "/login"), 2500); }
      catch (err) { m.className = "msg bad"; m.textContent = err.message; }
    });
  }

  // ------------------------------------------------------------------ activity
  const actState = { kind: "", q: "", page: 1 };
  async function activity() {
    panel.innerHTML = '<div class="toolbar"><select id="ak" aria-label="Filter"><option value="">Everything</option><option value="payment">Payments</option><option value="security">Security (failed attempts)</option><option value="admin">Admin actions</option></select><input id="aq" type="text" placeholder="Search order, email, IP, detail" aria-label="Search activity"></div><div id="al"></div><div class="pager" id="ap"></div>';
    $("#ak").value = actState.kind; $("#aq").value = actState.q; let tm;
    $("#ak").onchange = () => { actState.kind = $("#ak").value; actState.page = 1; loadAct(); };
    $("#aq").oninput = () => { clearTimeout(tm); tm = setTimeout(() => { actState.q = $("#aq").value; actState.page = 1; loadAct(); }, 300); };
    await loadAct();
  }
  const loadAct = guard(async function () {
    const d = await api("/api/admin/events?" + new URLSearchParams({ kind: actState.kind, q: actState.q, page: actState.page }));
    $("#al").innerHTML = table(["When", "Who", "What", "Ref", "IP", "Detail"], d.events.map((e) => "<tr><td>" + esc(date(e.ts)) + "</td><td>" + esc(e.actor) + '</td><td><span class="chip ' + (/fail|locked|denied|ambiguous/.test(e.kind) ? "bad" : /paid|payment_in/.test(e.kind) ? "ok" : "") + '">' + esc(e.kind) + '</span></td><td class="mono">' + esc(e.ref || "") + '</td><td class="mono">' + esc(e.ip || "") + "</td><td>" + esc(e.detail || "") + "</td></tr>"), "No activity yet.");
    pager($("#ap"), d, (pg) => { actState.page = pg; loadAct(); });
  });

  // ------------------------------------------------------------------ growth + reviews
  async function growth() {
    const d = await api("/api/admin/growth");
    panel.innerHTML = '<div class="card"><h3>Page views, last 14 days (' + d.views + ' total)</h3><div id="gv" class="pad"></div></div><div class="grid2 pad">' +
      '<div><h3>Top pages</h3>' + table(["Page", "Views"], d.pages.map((p) => '<tr><td class="mono">' + esc(p.path) + "</td><td>" + p.n + "</td></tr>")) + "</div>" +
      '<div><h3>Where visitors come from</h3>' + table(["Source", "Views"], d.sources.map((p) => "<tr><td>" + esc(p.src) + "</td><td>" + p.n + "</td></tr>")) + "</div></div>" +
      '<div class="grid2 pad"><div><h3>Signups by source</h3>' + table(["Source", "Users"], d.signups.map((p) => "<tr><td>" + esc(p.src) + "</td><td>" + p.n + "</td></tr>")) + "</div>" +
      '<div><h3>Top inviters</h3>' + table(["Inviter", "Joined", "Paid", "Credits used"], d.referrers.map((r) => "<tr><td>" + esc(r.name) + '<div class="small muted">' + esc(r.email) + "</div></td><td>" + r.joined + "</td><td>" + (r.paid || 0) + "</td><td>" + r.used + "</td></tr>"), "No invites yet.") + "</div></div>";
    bars($("#gv"), d.series.map((s) => ({ day: s.label, v: s.v })), "", (v) => v);
  }
  async function reviews() {
    const d = await api("/api/admin/reviews");
    panel.innerHTML = table(["Customer", "Stars", "Review", "Status", ""], d.reviews.map((r) => "<tr><td>" + esc(r.name) + "</td><td>" + "★".repeat(r.stars) + "</td><td>" + esc(r.text) + '</td><td><span class="chip ' + (r.status === "approved" ? "ok" : r.status === "pending" ? "warn" : "bad") + '">' + esc(r.status) + '</span></td><td><button class="btn sm" data-r="' + r.id + '" data-s="approved">Approve</button> <button class="btn ghost sm" data-r="' + r.id + '" data-s="rejected">Reject</button></td></tr>'), "No reviews yet. Customers can review from their dashboard after a paid download.");
    $$("[data-r]", panel).forEach((b) => (b.onclick = guard(async () => { await api("/api/admin/reviews/" + b.dataset.r, { json: { status: b.dataset.s } }); reviews(); })));
  }

  // ------------------------------------------------------------------ settings
  async function settings() {
    const [s, sy] = await Promise.all([api("/api/admin/settings"), api("/api/admin/system")]);
    const x = sy.system, mb = (b) => (b / 1048576).toFixed(1) + " MB";
    panel.innerHTML = '<div class="grid2"><div class="card"><h3>Site announcement</h3><p class="muted">Shows as a banner on every page. Leave empty to hide it.</p><form id="sForm" class="stack pad" novalidate>' +
      '<div><label for="sAnn">Message (max 200 characters)</label><input id="sAnn" type="text" maxlength="200"></div><div><label for="sKind">Style</label><select id="sKind"><option value="info">Info</option><option value="warn">Warning</option></select></div>' +
      '<label class="check"><input id="sSign" type="checkbox"><span>Allow new sign ups<small>Turn off to pause registrations.</small></span></label><div><button class="btn" type="submit">Save</button></div></form><p class="msg" id="sMsg"></p></div>' +
      '<div class="card"><h3>System</h3><dl class="kv"><dt>Site</dt><dd>' + esc(x.public_url) + "</dd><dt>Payments</dt><dd>" + esc(x.mode) + "</dd><dt>UPI ID</dt><dd>" + esc(x.upi_id || "-") + " (" + esc(x.payee || "") + ")</dd><dt>Gmail</dt><dd>" + esc(x.gmail_user || "-") + (x.gmail_enabled ? " (reading)" : " (off)") + "</dd><dt>Order timeout</dt><dd>" + esc(x.order_expiry_minutes) + " min</dd><dt>Admins</dt><dd>" + esc((x.admin_emails || []).join(", ") || "-") + "</dd><dt>Workers</dt><dd>" + esc(x.workers) + "</dd><dt>Uptime</dt><dd>" + Math.round(x.uptime / 3600 * 10) / 10 + " h</dd><dt>Telegram alerts</dt><dd>" + (s.telegram ? 'on <button class="btn ghost sm" id="tgTest" type="button">Send test</button>' : "off (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)") + "</dd><dt>Python</dt><dd>" + esc(x.python) + "</dd><dt>Data folder</dt><dd class=\"mono\">" + esc(x.data_dir) + (x.volume ? "" : " (no Volume)") + "</dd><dt>Disk use</dt><dd>db " + mb(x.db_bytes) + ", logos " + mb(x.logos_bytes) + ", themes " + mb(x.themes_bytes) + ", exports " + mb(x.exports_bytes) + ", cache " + mb(x.cache_bytes) + "</dd></dl>" +
      '<p class="pad"><button class="btn ghost sm" id="clr" type="button">Clear export + thumbnail cache</button></p><p class="small muted">Prices and the UPI ID are changed in Railway Variables (for example QS__pricing__base=39). That keeps secrets and money settings out of the website.</p></div></div>';
    $("#sAnn").value = s.announcement; $("#sKind").value = s.announcement_kind; $("#sSign").checked = s.signups_open;
    $("#sForm").addEventListener("submit", async (e) => { e.preventDefault(); const m = $("#sMsg"); try { await api("/api/admin/settings", { json: { announcement: $("#sAnn").value, announcement_kind: $("#sKind").value, signups_open: $("#sSign").checked } }); m.className = "msg ok"; m.textContent = "Saved."; } catch (err) { m.className = "msg bad"; m.textContent = err.message; } });
    if ($("#tgTest")) $("#tgTest").onclick = guard(async () => { await api("/api/admin/notify-test", { json: {} }); toast("Test alert sent to Telegram", "ok"); });
    $("#clr").onclick = guard(async () => { await api("/api/admin/system/clear-cache", { json: {} }); toast("Cache cleared. Files rebuild when needed.", "ok"); settings(); });
  }

  // ------------------------------------------------------------------ tabs
  const views = { overview, orders, payments, users, qrs, growth, reviews, test, backup, activity, settings };
  function show(name) {
    if (!views[name]) name = "overview";
    $$("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.t === name)));
    panel.classList.remove("panel-in"); void panel.offsetWidth; panel.classList.add("panel-in");
    history.replaceState(null, "", "#" + name);
    guard(views[name])();
  }
  $$("#tabs button").forEach((b) => (b.onclick = () => show(b.dataset.t)));
  const sys0 = await api("/api/admin/stats").catch(() => null);
  if (sys0) { const m = sys0.stats.mode; $("#modeChip").textContent = m === "live" ? "LIVE payments" : "MOCK payments (testing)"; $("#modeChip").className = "chip " + (m === "live" ? "ok" : "warn"); }
  window.addEventListener("hashchange", () => { const n = location.hash.replace("#", ""); if (views[n]) show(n); });
  show(location.hash.replace("#", "") || "overview");
})();
