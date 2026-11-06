(async function () {
  await QS.ready;
  if (!QS.requireLogin()) return;
  const { $, api, esc, rs, date } = QS;
  const id = new URLSearchParams(location.search).get("id") || "";
  const box = $("#rc");
  try {
    const o = (await api("/api/orders/" + encodeURIComponent(id))).order;
    if (o.status !== "paid") { box.innerHTML = "<h1>No receipt yet</h1><p class=\"muted\">This order is not paid.</p>"; return; }
    box.innerHTML = '<div class="eyebrow">' + esc(QS.site.site_name) + " by " + esc(QS.site.owner) + "</div><h1>Receipt</h1>" +
      '<dl class="kv pad"><dt>Receipt for</dt><dd>' + esc(QS.user.name) + " (" + esc(QS.user.email) + ")</dd><dt>Order</dt><dd class=\"mono\">" + esc(o.id) + "</dd><dt>Item</dt><dd>" + esc(o.kind === "pass" ? o.label : "Poster download: " + (o.label || "QR")) + "</dd><dt>Amount paid</dt><dd><b>" + (o.amount_paise ? esc(rs(o.amount_paise)) : "Free with pass") + "</b></dd><dt>Method</dt><dd>UPI</dd><dt>Reference</dt><dd class=\"mono\">" + esc(o.utr || "-") + "</dd><dt>Paid on</dt><dd>" + esc(date(o.paid_at)) + "</dd></dl>" +
      '<p class="small muted pad">This is a payment confirmation for a digital download. It is not a tax invoice.</p>';
    $("#rcActions").classList.remove("hide");
    $("#rcPrint").onclick = () => window.print();
  } catch (e) { box.innerHTML = "<h1>Receipt not found</h1><p class=\"muted\">" + esc(e.message) + "</p>"; }
})();
