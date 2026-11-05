(async function () {
  await QS.ready;
  if (!QS.requireLogin()) return;
  if (!QS.user.admin) { location.replace("/"); return; }
  const { $, api, esc, rs, date, toast } = QS;

  async function load() {
    const d = await api("/api/admin/stats"), s = d.stats;
    $("#stats").innerHTML = [["Users", s.users], ["Saved QRs", s.qrs], ["Paid orders", s.paid_orders], ["Revenue", "₹" + s.revenue], ["Last 7 days", "₹" + s.revenue_7d], ["Pending", s.pending], ["Unclaimed payments", s.unclaimed_payments]]
      .map(([a, b]) => '<div class="card"><b>' + b + "</b><span>" + a + "</span></div>").join("");
    const im = s.imap;
    $("#mbox").textContent = "Mode: " + s.mode + ". Mailbox reader: " + (im.enabled ? "on" : "off") + (im.last_ok ? ", last OK " + date(im.last_ok) : "") + ". Emails seen " + im.seen + ", stored " + im.stored + ", rejected " + im.rejected + (im.last_error ? ". Last error: " + im.last_error : "") + ".";
    $("#oBody").innerHTML = d.orders.map((o) => '<tr><td class="mono">' + esc(o.id) + "</td><td>" + esc(o.email) + "</td><td>" + (o.amount_paise ? esc(rs(o.amount_paise)) : "Pass") + '</td><td><span class="chip ' + ({ paid: "ok", pending: "warn", expired: "bad" }[o.status] || "") + '">' + esc(o.status) + '</span></td><td class="mono">' + esc(o.utr || "") + "</td><td>" + esc(date(o.created)) + "</td></tr>").join("") || '<tr><td colspan="6" class="muted">No orders yet.</td></tr>';
    $("#pBody").innerHTML = d.payments.map((p) => '<tr><td class="mono">' + esc(p.utr) + "</td><td>" + esc(rs(p.amount_paise)) + "</td><td>" + esc(p.payer || "") + "</td><td>" + esc(p.source) + '</td><td class="mono">' + esc(p.claimed_by || "unclaimed") + "</td><td>" + esc(date(p.received_at)) + "</td></tr>").join("") || '<tr><td colspan="6" class="muted">No payments yet.</td></tr>';
    const ub = $("#uBody"); ub.innerHTML = "";
    d.users.forEach((u) => {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + esc(u.email) + "</td><td>" + esc(u.name) + "</td><td>" + esc(date(u.created)) + "</td><td>" + (u.pass_until > Date.now() / 1000 ? "Active" : "") + '</td><td><button class="btn ' + (u.banned ? "ghost" : "danger") + ' sm" type="button">' + (u.banned ? "Unban" : "Ban") + "</button></td>";
      tr.querySelector("button").onclick = async () => { try { await api("/api/admin/users/" + u.id + "/ban", { json: { banned: !u.banned } }); load(); } catch (e) { toast(e.message, "bad"); } };
      ub.appendChild(tr);
    });
  }
  $("#payForm").addEventListener("submit", async (e) => {
    e.preventDefault(); const m = $("#aMsg");
    try { await api("/api/admin/payments", { json: { utr: $("#aUtr").value, amount: $("#aAmt").value } }); m.className = "msg ok"; m.textContent = "Payment added."; $("#aUtr").value = $("#aAmt").value = ""; load(); }
    catch (err) { m.className = "msg bad"; m.textContent = err.message; }
  });
  load().catch((e) => toast(e.message, "bad"));
})();
