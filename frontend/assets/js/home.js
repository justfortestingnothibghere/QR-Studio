(async function () {
  await QS.ready;
  try {
    const d = await QS.api("/api/themes");
    const box = QS.$("#strip");
    d.themes.slice(0, 12).forEach((t) => {
      const a = document.createElement("a"); a.href = "/studio?theme=" + encodeURIComponent(t.id);
      a.innerHTML = '<img loading="lazy" alt="' + QS.esc(t.name) + ' theme" src="/api/themes/' + encodeURIComponent(t.id) + '/thumb">';
      box.appendChild(a);
    });
  } catch (e) { /* strip stays empty */ }
  const m = QS.site.support_email;
  if (QS.$("#trMail")) QS.$("#trMail").textContent = m || "";
  if (QS.$("#trIg") && QS.igLink()) QS.$("#trIg").innerHTML = "Instagram " + QS.igLink();
  try {
    const s = await QS.api("/api/public-stats");
    if (s.show) { const el = QS.$("#trCount"); el.classList.remove("hide"); el.textContent = "🎨 " + s.qrs.toLocaleString("en-IN") + "+ posters designed"; }
  } catch (e) {}
  try {
    const r = await QS.api("/api/reviews");
    if (r.reviews && r.reviews.length) {
      QS.$("#revs").classList.remove("hide");
      QS.$("#revAvg").textContent = r.count + " review" + (r.count > 1 ? "s" : "") + " · average " + r.average + " / 5";
      QS.$("#revList").innerHTML = r.reviews.slice(0, 6).map((v) => '<div class="card"><div style="color:#f5b301">' + "★".repeat(v.stars) + "</div><p>" + QS.esc(v.text) + '</p><div class="small muted">' + QS.esc(v.name) + "</div></div>").join("");
    }
  } catch (e) {}
})();
