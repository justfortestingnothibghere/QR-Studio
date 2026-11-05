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
})();
