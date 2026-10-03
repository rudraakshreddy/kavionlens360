/* Light/dark toggle. The OS setting is the default; an explicit choice is remembered per browser. */
(() => {
  const root = document.documentElement;
  let saved = null;
  try { saved = localStorage.getItem("kl360-theme"); } catch (e) { /* storage blocked */ }
  if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  const isDark = () => root.getAttribute("data-theme") === "dark" ||
    (!root.getAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
  const label = (btn) => { btn.textContent = isDark() ? "☀" : "☾"; btn.setAttribute("aria-label", isDark() ? "Switch to light theme" : "Switch to dark theme"); };
  addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("theme-btn");
    if (!btn) return;
    label(btn);
    btn.addEventListener("click", () => {
      const next = isDark() ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("kl360-theme", next); } catch (e) { /* ignore */ }
      label(btn);
      dispatchEvent(new Event("themechange"));
    });
  });
})();
