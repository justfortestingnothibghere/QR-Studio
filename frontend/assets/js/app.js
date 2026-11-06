/* Shared helpers: API client, auth state, nav, toasts. No framework. */
(function () {
  const S = { user: null, csrf: null, cfg: {} };
  window.QS = S;

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  QS.esc = esc; QS.$ = $; QS.$$ = $$;

  QS.toast = function (msg, kind) {
    let box = $("#toasts");
    if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
    const t = document.createElement("div");
    t.className = "toast " + (kind || ""); t.textContent = msg; t.setAttribute("role", "status");
    box.appendChild(t);
    setTimeout(() => t.remove(), 4200);
  };

  QS.api = async function (path, opts) {
    opts = opts || {};
    const init = { method: opts.method || "GET", credentials: "same-origin", headers: {} };
    if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers["Content-Type"] = "application/json"; if (!opts.method) init.method = "POST"; }
    if (opts.form) { init.body = opts.form; if (!opts.method) init.method = "POST"; }
    if (init.method !== "GET" && S.csrf) init.headers["X-CSRF-Token"] = S.csrf;
    let res;
    try { res = await fetch(path, init); } catch (e) { throw new Error("Network problem. Check your connection."); }
    if (opts.raw) return res;
    let data = {};
    try { data = await res.json(); } catch (e) { /* non json */ }
    if (!res.ok) { const err = new Error(data.error || "Something went wrong"); err.status = res.status; throw err; }
    return data;
  };

  QS.rs = (paise) => "₹" + (paise / 100).toFixed(2);
  QS.date = (t) => new Date(t * 1000).toLocaleString([], { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

  QS.site = { site_name: "QR Studio", owner: "TeamDev", support_email: "" };
  QS.load = async function () {
    try { const r = await fetch("/config.json", { credentials: "same-origin" }); if (r.ok) Object.assign(QS.site, await r.json()); } catch (e) { /* defaults */ }
    try {
      const d = await QS.api("/api/me");
      S.user = d.user; S.csrf = d.csrf; S.cfg = { pricing: d.pricing, mode: d.payments_mode, upi: d.upi_id };
    } catch (e) { S.user = null; }
    return S.user;
  };

  QS.requireLogin = function () {
    if (!S.user) { location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search); return false; }
    return true;
  };

  QS.logoSvg = '<svg width="28" height="28" viewBox="0 0 30 30" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="3"><rect x="2" y="2" width="10" height="10" rx="3"/><rect x="18" y="2" width="10" height="10" rx="3"/><rect x="2" y="18" width="10" height="10" rx="3"/></g><g fill="currentColor"><circle cx="23" cy="23" r="3"/><circle cx="17" cy="17" r="2"/><circle cx="26.5" cy="17" r="1.6"/><circle cx="17" cy="27" r="1.6"/></g></svg>';

  function nav() {
    const here = location.pathname;
    const L = [["/themes", "Themes"], ["/pricing", "Pricing"], ["/studio", "Studio"], ["/how-it-works", "How it works"]];
    if (S.user) L.push(["/dashboard", "My QRs"]);
    const links = L.map(([h, t]) => '<a href="' + h + '"' + (here === h ? ' class="on"' : "") + ">" + t + "</a>").join("");
    const right = S.user
      ? (S.user.admin ? '<a class="btn ghost sm" href="/admin">Admin</a>' : "") + '<a class="btn ghost sm" href="/dashboard">' + esc(S.user.name.split(" ")[0]) + '</a><button class="btn ghost sm" id="logoutBtn" type="button">Log out</button>'
      : '<a class="btn ghost sm" href="/login">Log in</a><a class="btn sm" href="/signup">Sign up</a>';
    const el = $("#nav");
    if (!el) return;
    el.className = "nav";
    el.innerHTML = '<div class="wrap"><a class="logo" href="/">' + QS.logoSvg + esc(QS.site.site_name) + ' <small>by ' + esc(QS.site.owner) + '</small></a><nav class="links" id="links" aria-label="Main">' + links + '</nav><span class="sp"></span><div class="navr">' + right + '<button class="btn ghost sm themebtn" id="themeBtn" type="button" aria-label="Switch light or dark look" title="Light / dark"></button><button class="btn ghost sm burger" id="burger" type="button" aria-label="Menu">Menu</button></div></div>';
    $("#burger").onclick = () => $("#links").classList.toggle("open");
    theme.paint();
    $("#themeBtn").onclick = theme.toggle;
    banner();
    const lo = $("#logoutBtn");
    if (lo) lo.onclick = async () => { try { await QS.api("/api/logout", { method: "POST" }); } catch (e) { /* ignore */ } location.href = "/"; };
  }

  // light / dark toggle (the page also follows the system until the visitor chooses)
  const theme = {
    cur() { const a = document.documentElement.getAttribute("data-theme"); return a || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); },
    paint() {
      const b = $("#themeBtn"); if (!b) return;
      b.innerHTML = theme.cur() === "light"
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
    },
    toggle() {
      const n = theme.cur() === "light" ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", n);
      try { localStorage.setItem("qs-theme", n); } catch (e) { /* ignore */ }
      theme.paint();
    }
  };

  // owner announcement (set in /admin)
  function banner() {
    const a = QS.site.announcement;
    if (!a || $(".banner")) return;
    let seen = ""; try { seen = localStorage.getItem("qs-banner"); } catch (e) { /* ignore */ }
    if (seen === a) return;
    const el = document.createElement("div");
    el.className = "wrap banner" + (QS.site.announcement_kind === "warn" ? " warn" : "");
    el.setAttribute("role", "status");
    el.innerHTML = "<span></span><button type=\"button\" aria-label=\"Dismiss\">×</button>";
    el.firstChild.textContent = a;
    el.lastChild.onclick = () => { el.remove(); try { localStorage.setItem("qs-banner", a); } catch (e) { /* ignore */ } };
    const nav = $("#nav"); nav.parentNode.insertBefore(el, nav.nextSibling);
  }

  // fast navigation: start loading a page when the pointer or finger gets close
  function prefetch() {
    const done = new Set();
    const go = (e) => {
      const a = e.target.closest && e.target.closest("a[href^='/']");
      if (!a || a.target || a.hasAttribute("download") || a.pathname.startsWith("/api/") || done.has(a.pathname)) return;
      done.add(a.pathname);
      const l = document.createElement("link"); l.rel = "prefetch"; l.href = a.pathname + a.search; document.head.appendChild(l);
    };
    document.addEventListener("pointerenter", go, { capture: true, passive: true });
    document.addEventListener("touchstart", go, { capture: true, passive: true });
  }

  // gentle scroll reveal
  function reveal() {
    if (!("IntersectionObserver" in window) || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const els = $$("main .card, main .step, main .tcard, main .section > h2, main .hero > *, main .faq details, main .qcard");
    if (!els.length) return;
    document.documentElement.classList.add("js-reveal");
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { rootMargin: "0px 0px -6% 0px", threshold: 0.05 });
    els.forEach((el, i) => { el.classList.add("reveal"); el.style.setProperty("--i", String(i % 6)); io.observe(el); });
    // content that loads later (lists built by page scripts) is revealed too
    new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => {
      if (n.nodeType !== 1) return;
      const add = (el) => { if (!el.classList.contains("reveal")) { el.classList.add("reveal"); io.observe(el); } };
      if (n.matches && n.matches(".card,.tcard,.qcard,.step")) add(n);
      n.querySelectorAll && n.querySelectorAll(".card,.tcard,.qcard,.step").forEach(add);
    }))).observe($("main") || document.body, { childList: true, subtree: true });
  }

  QS.countUp = function (el, to, fmt) {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches || !isFinite(to)) { el.textContent = fmt ? fmt(to) : to; return; }
    const t0 = performance.now(), dur = 700;
    (function tick(t) { const p = Math.min(1, (t - t0) / dur), v = Math.round(to * (1 - Math.pow(1 - p, 3))); el.textContent = fmt ? fmt(v) : v; if (p < 1) requestAnimationFrame(tick); })(t0);
  };

  function footer() {
    const el = $("#footer");
    if (!el) return;
    el.className = "footer";
    el.innerHTML = '<div class="wrap"><div>© ' + new Date().getFullYear() + ' ' + esc(QS.site.owner) + '. ' + esc(QS.site.site_name) + ' is built and run by ' + esc(QS.site.owner) + '.' + (QS.site.support_email ? ' Support: <span class="mono">' + esc(QS.site.support_email) + '</span>' : '') + '</div><nav><a href="/how-it-works">How it works</a><a href="/faq">FAQ</a><a href="/contact">Support</a><a href="/pricing">Pricing</a><a href="/refund">Refunds</a><a href="/terms">Terms</a><a href="/privacy">Privacy</a></nav></div>';
  }

  // shield: stop easy right-click saving of previews (deterrent only, the real protection is the server-side watermark)
  QS.shield = function (el) {
    el.addEventListener("contextmenu", (e) => e.preventDefault());
    el.addEventListener("dragstart", (e) => e.preventDefault());
  };

  QS.ready = (async function () {
    await QS.load();
    nav(); footer(); prefetch();
    document.documentElement.classList.add("ready");
    requestAnimationFrame(reveal);
  })();
})();
