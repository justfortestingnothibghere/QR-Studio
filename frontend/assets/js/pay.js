/* Shared payment panel: pay exact amount -> Fam email -> paste UTR -> unlock. Used by Studio and Dashboard. */
(function () {
  const { api, esc, rs, toast } = QS;

  function downloads(o) {
    const base = "/api/orders/" + o.id + "/download/";
    const b = (f, label) => '<a class="btn ghost" href="' + base + f + '">' + label + "</a>";
    return '<div class="dl">' + b("png", "PNG · 2048×3072") + b("jpg", "JPG") + b("pdf", "PDF · print") +
      (o.print || (QS.user && QS.user.pass_active) ? b("svg", "QR as SVG") + b("qrpng", "QR transparent PNG") : "") + "</div>";
  }

  function mount(box, order, opts) {
    opts = opts || {};
    box.classList.remove("hide");
    if (order.status === "paid") return paid(box, order, opts);
    const exp = new Date(order.expires * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    box.innerHTML =
      '<h3>Pay ' + esc(QS.rs(order.amount_paise)) + ' by UPI</h3>' +
      '<ol class="steps4" id="st"><li class="now">Pay the exact amount</li><li>Payment email arrives</li><li>Paste the UTR</li><li>Download unlocks</li></ol>' +
      '<div class="paybox"><img id="pq" alt="UPI QR to pay this order" width="170" height="170">' +
      '<div><div class="lab">Pay exactly</div><div class="amount">' + esc(QS.rs(order.amount_paise)) + '</div>' +
      '<p class="small muted pad">to <span class="mono">' + esc(order.payee || "") + '</span>. The paise identify your order, so do not round the amount.</p>' +
      '<div class="actions pad"><a class="btn blue sm" href="' + esc(order.upi_link || "#") + '">Open UPI app</a><button class="btn ghost sm" id="cp" type="button">Copy amount</button>' +
      (QS.cfg.mode === "mock" ? '<button class="btn ghost sm" id="sim" type="button">Simulate payment (demo)</button>' : "") + '</div>' +
      '<p class="small muted pad">Order ' + esc(order.id) + ' · pay before ' + esc(exp) + '</p></div></div>' +
      '<div class="lab pad">After paying, copy the 12-digit UTR from your payment email</div>' +
      '<div class="verify"><input id="utr" type="text" inputmode="numeric" maxlength="14" placeholder="12-digit UTR" autocomplete="off" aria-label="UTR"><button class="btn" id="vf" type="button">Verify payment</button></div>' +
      '<p class="msg" id="vm" role="status"></p>';
    const img = box.querySelector("#pq");
    fetch("/api/orders/" + order.id + "/payqr", { credentials: "same-origin" }).then((r) => r.ok ? r.blob() : Promise.reject()).then((b) => { img.src = URL.createObjectURL(b); }).catch(() => { img.alt = "Could not load the QR. Use the Open UPI app button."; });
    const msg = box.querySelector("#vm");
    const say = (k, t) => { msg.className = "msg " + k; msg.textContent = t; };
    box.querySelector("#cp").onclick = async () => {
      const t = (order.amount_paise / 100).toFixed(2);
      try { await navigator.clipboard.writeText(t); toast("Amount copied: " + t, "ok"); } catch (e) { toast("Amount: " + t); }
    };
    const sim = box.querySelector("#sim");
    if (sim) sim.onclick = async () => {
      try { const d = await api("/api/orders/" + order.id + "/simulate", { method: "POST", json: {} }); box.querySelector("#utr").value = d.utr; say("ok", "Demo payment recorded. Press Verify."); box.querySelector("#st").children[0].className = "done"; box.querySelector("#st").children[1].className = "done"; box.querySelector("#st").children[2].className = "now"; } catch (e) { say("bad", e.message); }
    };
    const verify = async () => {
      const utr = box.querySelector("#utr").value.replace(/\s/g, "");
      if (!/^\d{12}$/.test(utr)) return say("bad", "A UTR has 12 digits. Copy it from the payment email.");
      const btn = box.querySelector("#vf"); btn.disabled = true; say("", "Checking…");
      try {
        await api("/api/orders/" + order.id + "/verify", { json: { utr } });
        const d = await api("/api/orders/" + order.id);
        await QS.load();
        paid(box, d.order, opts);
        if (opts.onPaid) opts.onPaid(d.order);
      } catch (e) { say("bad", e.message); btn.disabled = false; }
    };
    box.querySelector("#vf").onclick = verify;
    box.querySelector("#utr").addEventListener("keydown", (e) => { if (e.key === "Enter") verify(); });
  }

  function paid(box, o, opts) {
    box.classList.remove("hide");
    const isPass = o.kind === "pass";
    box.innerHTML = '<div class="done"><b>' + (isPass ? "Pass is active." : "Payment confirmed.") + '</b><p class="muted">' +
      (isPass ? "Unlimited HD downloads are unlocked on your account." : "Your clean files are ready. They are saved in My QRs, so you can download them again any time.") + "</p>" + (isPass ? "" : downloads(o)) + "</div>";
  }

  window.QSPay = { mount, paid, downloads };
})();
