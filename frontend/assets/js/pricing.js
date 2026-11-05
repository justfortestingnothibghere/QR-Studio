(async function () {
  await QS.ready;
  const p = QS.cfg.pricing || {};
  const set = (id, v) => { const e = QS.$("#" + id); if (e) e.textContent = v; };
  set("pBase", "₹" + p.base); set("pCap", "₹" + p.cap); set("pPass", "₹" + p.pass_price); set("pPassDays", "for " + p.pass_days + " days");
  QS.$("#pList").innerHTML = [["HD export (PNG, JPG, PDF)", p.base], ["Centre logo", "+" + p.logo], ["Your own theme", "+" + p.custom_theme], ["Dynamic link with scan counter", "+" + p.dynamic], ["Print pack (SVG and transparent PNG)", "+" + p.print]]
    .map(([a, b]) => "<li><span>" + a + "</span><b>" + (String(b).startsWith("+") ? "+₹" + String(b).slice(1) : "₹" + b) + "</b></li>").join("");
})();
