// Menu sur mobile, et numéro de la dernière version lu sur GitHub (repli : celui écrit dans la page).
(function () {
  const btn = document.querySelector(".menu-btn");
  const links = document.querySelector(".nav-links");
  if (btn && links) {
    btn.addEventListener("click", () => {
      const open = links.classList.toggle("open");
      btn.setAttribute("aria-expanded", String(open));
    });
    links.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => links.classList.remove("open")));
  }
  const slot = document.querySelector("[data-version]");
  if (!slot || !window.fetch) return;
  fetch("https://api.github.com/repos/riyadhHDA/pixplot-v2/releases/latest", { headers: { Accept: "application/vnd.github+json" } })
    .then((r) => (r.ok ? r.json() : null))
    .then((rel) => { if (rel && rel.tag_name) slot.textContent = rel.tag_name; })
    .catch(() => { /* hors ligne ou limite de l'API : on garde la valeur écrite */ });
})();
