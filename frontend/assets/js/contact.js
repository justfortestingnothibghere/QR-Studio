(async function () {
  await QS.ready;
  const m = QS.site.support_email, t = QS.site.support_telegram;
  QS.$("#ctMail").innerHTML = m ? '<a href="mailto:' + QS.esc(m) + '">' + QS.esc(m) + "</a>" : "Not set yet";
  const h = (t || "").replace(/^@/, "");
  QS.$("#ctTg").innerHTML = h ? '<a href="https://t.me/' + encodeURIComponent(h) + '" target="_blank" rel="noopener">@' + QS.esc(h) + "</a>" : "Not set yet";
})();
