(async function () {
  await QS.ready;
  const m = QS.site.support_email;
  QS.$("#abMail").innerHTML = m ? '<a href="mailto:' + QS.esc(m) + '">' + QS.esc(m) + "</a>" : "";
  QS.$("#abIg").innerHTML = QS.igLink() || "";
  try {
    const r = await fetch("/api/reviews").then((x) => x.json());
    if (r.reviews && r.reviews.length) {
      QS.$("#revs").hidden = false;
      QS.$("#revList").innerHTML = r.reviews.map((v) => '<div class="card"><div style="color:#f5b301">' + "★".repeat(v.stars) + '</div><p>' + QS.esc(v.text) + '</p><div class="small muted">' + QS.esc(v.name) + "</div></div>").join("");
    }
  } catch (e) {}
})();
