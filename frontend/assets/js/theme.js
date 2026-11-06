/* Runs in <head> before first paint so the chosen look never flashes. */
(function () {
  try { var t = localStorage.getItem("qs-theme"); if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t); } catch (e) { /* storage blocked: follow the system */ }
})();
