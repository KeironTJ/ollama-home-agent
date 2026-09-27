Promise.all([
  fetch("/health").then(response => response.json()),
  fetch("/api/config").then(response => response.json()),
]).then(([health, config]) => {
  const available = health.status === "ok" || health.status === "standby";
  document.querySelector("#health-dot").classList.toggle("ok", available);
  document.querySelector("#health-text").textContent = health.status === "ok"
    ? "All local services ready"
    : health.status === "standby"
      ? `${health.ollama.device} asleep · wakes on request`
      : "Some services need attention";
  document.querySelector("#model").textContent =
    `${config.model} on ${config.ollama_device_name} · ${config.proxmox_configured ? "Proxmox connected" : "Setup required"}`;
}).catch(() => {
  document.querySelector("#health-text").textContent = "Application unavailable";
});
