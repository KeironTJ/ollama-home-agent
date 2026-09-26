let setupToken = "";
const setupDialog = document.querySelector("#setup-dialog");
const setupStatus = document.querySelector("#setup-status");

function addSshHostRow(host = {}) {
  const row = document.createElement("div");
  row.className = "ssh-host-row";
  const fields = [
    ["Alias", "alias", host.alias || "minecraft"],
    ["Hostname / IP", "hostname", host.hostname || ""],
    ["Services", "services", (host.services || []).join(",")],
    ["Ports", "ports", (host.ports || []).join(",")],
  ];
  fields.forEach(([labelText, name, value]) => {
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = document.createElement("input");
    input.dataset.field = name;
    input.value = value;
    if (name === "services") input.placeholder = "minecraft";
    if (name === "ports") input.placeholder = "25565";
    label.appendChild(input);
    row.appendChild(label);
  });
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "button ssh-host-remove";
  remove.textContent = "Remove";
  remove.addEventListener("click", () => row.remove());
  row.appendChild(remove);
  document.querySelector("#ssh-hosts").appendChild(row);
}

document.querySelector("#add-ssh-host").addEventListener("click", () => addSshHostRow());

async function openSetup() {
  setupStatus.textContent = "Loading…";
  setupDialog.showModal();
  try {
    const response = await fetch("/api/setup");
    const config = await response.json();
    if (!response.ok) throw new Error(config.detail || "Could not load setup");
    setupToken = config.setup_token;
    document.querySelector("#setup-ollama-url").value = config.ollama_url;
    document.querySelector("#setup-ollama-model").value = config.ollama_model;
    document.querySelector("#setup-proxmox-url").value = config.proxmox_url;
    document.querySelector("#setup-token-id").value = config.proxmox_token_id;
    document.querySelector("#setup-ca-file").value = config.proxmox_ca_file;
    document.querySelector("#setup-nodes").value = config.proxmox_allowed_nodes.join(",");
    document.querySelector("#setup-guests").value = config.proxmox_allowed_guests.join(",");
    document.querySelector("#setup-insecure").checked = config.proxmox_insecure_tls;
    document.querySelector("#setup-ssh-username").value = config.ssh_username;
    document.querySelector("#setup-ssh-key-file").value = config.ssh_key_file;
    document.querySelector("#ssh-hosts").replaceChildren();
    config.ssh_hosts.forEach(addSshHostRow);
    document.querySelector("#secret-status").textContent = config.proxmox_token_secret_configured
      ? "Proxmox token secret: configured in the environment (the value is never exposed here)."
      : "Proxmox token secret: missing. Add HOME_AGENT_PROXMOX_TOKEN_SECRET to .env.";
    const restart = document.querySelector("#restart-app");
    restart.disabled = !config.restart_available;
    restart.title = config.restart_available ? "" : "Launch with: python -m home_agent";
    setupStatus.textContent = "";
  } catch (error) {
    setupStatus.textContent = error.message;
  }
}

document.querySelector("#open-setup").addEventListener("click", openSetup);
document.querySelector("#open-setup-card").addEventListener("click", openSetup);
document.querySelector("#close-setup").addEventListener("click", () => setupDialog.close());

document.querySelector("#restart-app").addEventListener("click", async event => {
  const button = event.currentTarget;
  button.disabled = true;
  setupStatus.textContent = "Requesting restart…";
  try {
    const response = await fetch("/api/restart", {
      method: "POST",
      headers: {"X-Home-Agent-Setup-Token": setupToken},
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not restart");
    setupStatus.textContent = "Restarting; waiting for the application…";
    setTimeout(async () => {
      for (let attempt = 0; attempt < 40; attempt++) {
        try {
          const health = await fetch("/health", {cache: "no-store"});
          if (health.ok) {
            window.location.href = "/";
            return;
          }
        } catch (_) {}
        await new Promise(resolve => setTimeout(resolve, 500));
      }
      setupStatus.textContent = "Restart is taking longer than expected. Refresh shortly.";
      button.disabled = false;
    }, 1500);
  } catch (error) {
    setupStatus.textContent = error.message;
    button.disabled = false;
  }
});

document.querySelector("#setup-form").addEventListener("submit", async event => {
  event.preventDefault();
  const insecure = document.querySelector("#setup-insecure").checked;
  if (insecure && !confirm("Disable TLS verification? This permits network interception.")) return;
  const nodes = document.querySelector("#setup-nodes").value.split(",").map(value => value.trim()).filter(Boolean);
  const guests = document.querySelector("#setup-guests").value.split(",").map(value => value.trim()).filter(Boolean).map(Number);
  if (guests.some(value => !Number.isInteger(value) || value < 1)) {
    setupStatus.textContent = "Guest IDs must be positive whole numbers separated by commas.";
    return;
  }
  const body = {
    ollama_url: document.querySelector("#setup-ollama-url").value.trim(),
    ollama_model: document.querySelector("#setup-ollama-model").value.trim(),
    proxmox_url: document.querySelector("#setup-proxmox-url").value.trim(),
    proxmox_token_id: document.querySelector("#setup-token-id").value.trim(),
    proxmox_ca_file: document.querySelector("#setup-ca-file").value.trim(),
    proxmox_insecure_tls: insecure,
    proxmox_allowed_nodes: nodes,
    proxmox_allowed_guests: guests,
    ssh_username: document.querySelector("#setup-ssh-username").value.trim(),
    ssh_key_file: document.querySelector("#setup-ssh-key-file").value.trim(),
    ssh_hosts: Array.from(document.querySelectorAll(".ssh-host-row")).map(row => ({
      alias: row.querySelector('[data-field="alias"]').value.trim(),
      hostname: row.querySelector('[data-field="hostname"]').value.trim(),
      services: row.querySelector('[data-field="services"]').value.split(",").map(value => value.trim()).filter(Boolean),
      ports: row.querySelector('[data-field="ports"]').value.split(",").map(value => value.trim()).filter(Boolean).map(Number),
      ssh_port: 22,
    })),
  };
  if (body.ssh_hosts.some(host => !host.alias || !host.hostname || host.ports.some(port => !Number.isInteger(port) || port < 1 || port > 65535))) {
    setupStatus.textContent = "SSH hosts need an alias and hostname; ports must be valid whole numbers.";
    return;
  }
  setupStatus.textContent = "Saving…";
  try {
    const response = await fetch("/api/setup", {
      method: "PUT",
      headers: {"Content-Type": "application/json", "X-Home-Agent-Setup-Token": setupToken},
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not save configuration");
    setupStatus.textContent = result.message;
  } catch (error) {
    setupStatus.textContent = error.message;
  }
});

if (new URLSearchParams(window.location.search).get("setup") === "1") openSetup();
