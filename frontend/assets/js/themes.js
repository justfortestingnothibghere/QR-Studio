(async function () {
  await QS.ready;
  const { $, $$, esc } = QS;
  let all = [], cat = "All";
  try { all = (await QS.api("/api/themes")).themes; } catch (e) { $("#grid").textContent = "Could not load themes."; return; }
  const cats = ["All"].concat([...new Set(all.map((t) => t.category).filter(Boolean))]);
  const cbox = $("#cats");
  cats.forEach((c) => { const b = document.createElement("button"); b.type = "button"; b.textContent = c; b.dataset.v = c; b.setAttribute("aria-pressed", String(c === cat)); cbox.appendChild(b); });
  cbox.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; cat = b.dataset.v; $$("button", cbox).forEach((x) => x.setAttribute("aria-pressed", String(x === b))); draw(); });
  function draw() {
    const g = $("#grid"); g.innerHTML = "";
    all.filter((t) => cat === "All" || t.category === cat).forEach((t) => {
      const a = document.createElement("a"); a.className = "tcard"; a.href = "/studio?theme=" + encodeURIComponent(t.id);
      a.innerHTML = '<img loading="lazy" alt="' + esc(t.name) + '" src="/api/themes/' + encodeURIComponent(t.id) + '/thumb"><span>' + esc(t.name) + "<small>" + esc(t.category) + "</small></span>";
      g.appendChild(a);
    });
  }
  draw();
  if (!all.some((t) => t.mine)) $("#mineHint").classList.remove("hide");
})();
