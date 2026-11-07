(async function () {
  await QS.ready;
  const { $, api } = QS;
  const next = (() => { const n = new URLSearchParams(location.search).get("next") || "/dashboard"; return /^\/(?!\/)/.test(n) ? n : "/dashboard"; })();
  if (QS.user) { location.replace(next); return; }
  const nx = location.search ? location.search : "";
  const a1 = $("#toSignup"), a2 = $("#toLogin");
  if (a1) a1.href = "/signup" + nx; if (a2) a2.href = "/login" + nx;
  const isSignup = !!$("#name");
  if (isSignup && QS.stored("qs_ref") && $("#refNote")) $("#refNote").classList.remove("hide");
  $("#f").addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("#msg"), btn = $("#go");
    msg.className = "msg"; msg.textContent = "";
    const body = { email: $("#email").value, password: $("#pw").value };
    if (isSignup) { body.name = $("#name").value; body.accept_terms = $("#terms").checked; body.ref = QS.stored("qs_ref"); body.src = QS.stored("qs_src"); }
    btn.disabled = true;
    try { await api(isSignup ? "/api/signup" : "/api/login", { json: body }); location.href = next; }
    catch (err) { msg.className = "msg bad"; msg.textContent = err.message; btn.disabled = false; }
  });
})();
