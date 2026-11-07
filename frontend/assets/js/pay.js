/* Shared payment panel. Pay the exact amount -> the Fam email is matched automatically -> download unlocks.
   Fallbacks: paste the UTR or Fam Transaction ID, or press "my payment has no UTR" (Fam to Fam transfers). */
(function () {
  const { api, esc, toast } = QS;

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
      '<h3>' + (order.kind === "test" ? "Payment test: pay " : "Pay ") + esc(QS.rs(order.amount_paise)) + ' by UPI</h3>' +
      '<ol class="steps4" id="st"><li class="now">Pay the exact amount</li><li>Payment email arrives</li><li>Matched automatically</li><li>Download unlocks</li></ol>' +
      '<div class="paybox"><img id="pq" alt="UPI QR to pay this order" width="170" height="170">' +
      '<div><div class="lab">Pay exactly</div><div class="amount">' + esc(QS.rs(order.amount_paise)) + '</div>' +
      '<div class="lab pad">Or pay manually to this UPI ID</div><div class="upibox"><span class="mono" id="upiid">' + esc(order.payee || "") + '</span><button class="btn ghost sm" id="cpu" type="button">Copy UPI ID</button></div>' +
      '<p class="small muted pad">Type the exact amount <b>' + esc(QS.rs(order.amount_paise)) + '</b> including paise. The paise identify your order, so do not round it.</p>' +
      '<div class="actions pad"><a class="btn blue sm" href="' + esc(order.upi_link || "#") + '">Open UPI app</a><button class="btn ghost sm" id="cp" type="button">Copy amount</button>' +
      (QS.cfg.mode === "mock" ? '<button class="btn ghost sm" id="sim" type="button">Simulate payment (demo)</button>' : "") + '</div>' +
      '<p class="small muted pad">Order ' + esc(order.id) + ' · pay before ' + esc(exp) + '</p></div></div>' +
      '<p class="msg" id="wait" role="status"><span class="chip warn">Waiting for your payment…</span> <span class="small muted">This page confirms by itself, no need to refresh.</span></p>' +
      '<details class="pad" id="manual"><summary>Paid but not confirmed? Confirm by hand</summary>' +
      '<div class="lab pad">Copy the UTR (12 digits) or the Transaction ID from your Fam payment email</div>' +
      '<div class="verify"><input id="utr" type="text" maxlength="40" placeholder="UTR or Transaction ID" autocomplete="off" autocapitalize="characters" aria-label="UTR or Transaction ID"><button class="btn" id="vf" type="button">Verify payment</button></div>' +
      '<p class="small muted pad">Paid from Fam to a Fam wallet and the email shows no UTR? Use this instead:</p>' +
      '<p class="pad"><button class="btn ghost sm" id="noutr" type="button">My payment has no UTR</button></p>' +
      '<p class="msg" id="vm" role="status"></p></details>';
    const img = box.querySelector("#pq");
    fetch("/api/orders/" + order.id + "/payqr", { credentials: "same-origin" }).then((r) => r.ok ? r.blob() : Promise.reject()).then((b) => { img.src = URL.createObjectURL(b); }).catch(() => { img.alt = "Could not load the QR. Use the Open UPI app button."; });
    const msg = box.querySelector("#vm");
    const say = (k, t) => { msg.className = "msg " + k; msg.textContent = t; };
    let stopped = false, tries = 0, timer = null;

    const finish = async () => {
      stopped = true; clearTimeout(timer);
      const d = await api("/api/orders/" + order.id);
      await QS.load();
      paid(box, d.order, opts);
      if (opts.onPaid) opts.onPaid(d.order);
    };
    // the server marks the order paid the moment the Fam email arrives; we just look every few seconds
    const poll = async () => {
      if (stopped || !box.isConnected || !box.querySelector("#wait")) return;
      tries++;
      try {
        const d = await api("/api/orders/" + order.id);
        if (d.order.status === "paid") return finish();
        if (d.order.status !== "pending") { box.querySelector("#wait").innerHTML = '<span class="chip bad">This order expired</span> <span class="small muted">Create a new one. If you already paid, confirm by hand below.</span>'; if (d.order.status === "expired" && tries < 400) { timer = setTimeout(poll, 15000); } return; }
      } catch (e) { /* network blip: keep trying */ }
      if (tries === 24) box.querySelector("#manual").open = true;       // after about 2 minutes show the manual box
      timer = setTimeout(poll, tries < 12 ? 4000 : 8000);
    };
    timer = setTimeout(poll, 3000);

    box.querySelector("#cp").onclick = async () => {
      const t = (order.amount_paise / 100).toFixed(2);
      try { await navigator.clipboard.writeText(t); toast("Amount copied: " + t, "ok"); } catch (e) { toast("Amount: " + t); }
    };
    box.querySelector("#cpu").onclick = async () => {
      try { await navigator.clipboard.writeText(order.payee || ""); toast("UPI ID copied", "ok"); } catch (e) { toast("UPI ID: " + (order.payee || "")); }
    };
    const sim = box.querySelector("#sim");
    if (sim) sim.onclick = async () => {
      try { await api("/api/orders/" + order.id + "/simulate", { method: "POST", json: {} }); await finish(); } catch (e) { toast(e.message, "bad"); }
    };
    const send = async (payload, btn) => {
      btn.disabled = true; say("", "Checking…");
      try { await api("/api/orders/" + order.id + "/verify", { json: payload }); await finish(); }
      catch (e) { say("bad", e.message); btn.disabled = false; }
    };
    const vf = box.querySelector("#vf");
    vf.onclick = () => {
      const ref = box.querySelector("#utr").value.replace(/\s/g, "");
      if (!/^[A-Za-z0-9]{8,40}$/.test(ref)) return say("bad", "Enter the 12-digit UTR or the Transaction ID from the payment email.");
      send({ utr: ref }, vf);
    };
    box.querySelector("#noutr").onclick = (e) => send({ mode: "amount" }, e.currentTarget);
    box.querySelector("#utr").addEventListener("keydown", (e) => { if (e.key === "Enter") vf.click(); });
  }

  function paid(box, o, opts) {
    box.classList.remove("hide");
    const isPass = o.kind === "pass", isTest = o.kind === "test";
    const title = isTest ? "Payment test passed." : isPass ? "Pass is active." : "Payment confirmed.";
    const text = isTest ? "The payment email was received, read, matched to this order and unlocked it. Your payment flow works."
      : isPass ? "Unlimited HD downloads are unlocked on your account."
        : "Your clean files are ready. They are saved in My QRs, so you can download them again any time.";
    box.innerHTML = '<div class="done"><b>' + title + '</b><p class="muted">' + text + "</p>" + (isPass || isTest ? "" : downloads(o)) +
      (isTest ? "" : '<p class="small pad"><a href="/receipt?id=' + esc(o.id) + '">View receipt</a></p>') + "</div>";
  }

  window.QSPay = { mount, paid, downloads };
})();
