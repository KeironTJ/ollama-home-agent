Promise.all([
  fetch("/health").then(response => response.json()),
  fetch("/api/config").then(response => response.json()),
]).then(([health, config]) => {
  document.querySelector("#health-dot").classList.toggle("ok", health.status === "ok");
  document.querySelector("#health-text").textContent =
    health.status === "ok" ? "All local services ready" : "Some services need attention";
  document.querySelector("#model").textContent =
    `${config.model} · ${config.proxmox_configured ? "Proxmox connected" : "Setup required"}`;
}).catch(() => {
  document.querySelector("#health-text").textContent = "Application unavailable";
});
