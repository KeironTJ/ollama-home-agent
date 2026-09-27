const chat = document.querySelector("#chat");
const form = document.querySelector("#chat-form");
const message = document.querySelector("#message");
const send = document.querySelector("#send");
const voice = document.querySelector("#voice");
let sessionId = crypto.randomUUID();
let conversations = [];
let recorder;
let chunks = [];

function formatBytes(value) {
  if (value === null || value === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = Number(value);
  let unit = 0;
  while (Math.abs(amount) >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit++;
  }
  return `${amount.toFixed(unit > 1 ? 1 : 0)} ${units[unit]}`;
}

function formatUptime(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const value = Number(seconds);
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  return [days && `${days}d`, hours && `${hours}h`, `${minutes}m`].filter(Boolean).join(" ");
}

function statusPill(status) {
  const pill = document.createElement("span");
  pill.className = `status-pill ${status === "running" || status === "online" ? "healthy" : "inactive"}`;
  pill.textContent = status || "unknown";
  return pill;
}

function metric(label, value) {
  const item = document.createElement("div");
  item.className = "artifact-metric";
  const name = document.createElement("span");
  name.textContent = label;
  const content = document.createElement("strong");
  content.textContent = value;
  item.append(name, content);
  return item;
}

function renderArtifact(artifact) {
  if (artifact.type === "routing") {
    const route = document.createElement("div");
    route.className = "specialist-route";
    route.textContent = `Routed to ${artifact.data?.name || "specialist"}`;
    route.title = artifact.data?.description || "";
    return route;
  }
  const card = document.createElement("article");
  card.className = "artifact-card";
  const data = artifact.data || {};
  if (artifact.type === "infrastructure") {
    const heading = document.createElement("div");
    heading.className = "artifact-heading";
    heading.textContent = `Infrastructure · ${(data.nodes || []).length} node · ${(data.guests || []).length} guests`;
    card.appendChild(heading);
    const grid = document.createElement("div");
    grid.className = "guest-grid";
    (data.guests || []).forEach(guest => {
      const guestCard = document.createElement("div");
      guestCard.className = "guest-card";
      const title = document.createElement("strong");
      title.textContent = guest.name || `Guest ${guest.vmid}`;
      const details = document.createElement("span");
      details.textContent = `#${guest.vmid} · ${guest.type || "guest"} · ${formatBytes(guest.mem)}`;
      guestCard.append(title, statusPill(guest.status), details);
      grid.appendChild(guestCard);
    });
    card.appendChild(grid);
  } else if (artifact.type === "minecraft_servers") {
    const heading = document.createElement("div");
    heading.className = "artifact-heading";
    heading.textContent = `Crafty servers · ${Array.isArray(data) ? data.length : 0}`;
    card.appendChild(heading);
    const grid = document.createElement("div");
    grid.className = "guest-grid";
    (Array.isArray(data) ? data : []).forEach(server => {
      const serverCard = document.createElement("div");
      serverCard.className = "guest-card";
      const title = document.createElement("strong");
      title.textContent = server.server_name || server.name || "Minecraft server";
      const id = document.createElement("span");
      id.textContent = server.server_id || server.server_uuid || server.id || "Unknown ID";
      serverCard.append(title, id);
      grid.appendChild(serverCard);
    });
    card.appendChild(grid);
  } else if (artifact.type === "minecraft_status") {
    const heading = document.createElement("div");
    heading.className = "artifact-heading";
    heading.textContent = data.server_name || "Minecraft server status";
    card.appendChild(heading);
    const metrics = document.createElement("div");
    metrics.className = "artifact-metrics";
    metrics.appendChild(metric("State", data.running ? "running" : "stopped"));
    if (data.online !== undefined) metrics.appendChild(metric("Players", `${data.online}/${data.max ?? "—"}`));
    if (data.cpu !== undefined) metrics.appendChild(metric("CPU", `${Number(data.cpu).toFixed(2)}%`));
    if (data.mem !== undefined) metrics.appendChild(metric("Memory", formatBytes(data.mem)));
    if (data.version) metrics.appendChild(metric("Version", String(data.version)));
    card.appendChild(metrics);
  } else if (artifact.type === "minecraft_logs") {
    const heading = document.createElement("div");
    heading.className = "artifact-heading";
    heading.textContent = "Recent Crafty logs";
    const pre = document.createElement("pre");
    pre.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
    card.append(heading, pre);
  } else if (artifact.type === "guest_status" || artifact.type === "node_status") {
    const heading = document.createElement("div");
    heading.className = "artifact-heading";
    heading.textContent = artifact.type === "guest_status"
      ? `${data.name || `Guest ${data.vmid || ""}`} status`
      : "Node status";
    card.appendChild(heading);
    const metrics = document.createElement("div");
    metrics.className = "artifact-metrics";
    if (data.status) metrics.appendChild(metric("State", data.status));
    if (data.uptime !== undefined) metrics.appendChild(metric("Uptime", formatUptime(data.uptime)));
    if (data.cpu !== undefined) metrics.appendChild(metric("CPU", `${(Number(data.cpu) * 100).toFixed(2)}%`));
    if (data.mem !== undefined) metrics.appendChild(metric("Memory", formatBytes(data.mem)));
    card.appendChild(metrics);
  } else if (artifact.type === "port_status") {
    const heading = document.createElement("div");
    heading.className = "artifact-heading";
    heading.textContent = `TCP ${data.host}:${data.port}`;
    card.append(heading, statusPill(data.reachable ? "online" : "unreachable"));
  } else if (artifact.type === "guest_list") {
    const heading = document.createElement("div");
    heading.className = "artifact-heading";
    heading.textContent = `Guest matches · ${Array.isArray(data) ? data.length : 0}`;
    card.appendChild(heading);
  } else if (artifact.type === "task_list") {
    const heading = document.createElement("div");
    heading.className = "artifact-heading";
    heading.textContent = `Recent tasks · ${Array.isArray(data) ? data.length : 0}`;
    card.appendChild(heading);
  } else {
    const heading = document.createElement("div");
    heading.className = "artifact-heading";
    heading.textContent = artifact.type.replaceAll("_", " ");
    const pre = document.createElement("pre");
    pre.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
    card.append(heading, pre);
  }
  return card;
}

function addMessage(text, kind = "assistant", artifacts = []) {
  const element = document.createElement("div");
  element.className = `message ${kind}`;
  element.textContent = text;
  chat.appendChild(element);
  artifacts.forEach(artifact => chat.appendChild(renderArtifact(artifact)));
  chat.scrollTop = chat.scrollHeight;
}

function startNewConversation() {
  sessionId = crypto.randomUUID();
  chat.replaceChildren();
  addMessage("Describe the problem. I will use only configured, allowlisted diagnostics and will ask before any change.");
  renderHistory();
  message.focus();
}

async function loadConversation(id) {
  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`);
    const conversation = await response.json();
    if (!response.ok) throw new Error(conversation.detail || "Could not load conversation");
    sessionId = id;
    chat.replaceChildren();
    conversation.messages.forEach(item => addMessage(item.content, item.role, item.artifacts || []));
    renderHistory();
  } catch (error) {
    addMessage(error.message, "error");
  }
}

async function deleteConversation(id) {
  if (!confirm("Delete this local conversation history?")) return;
  const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, {method: "DELETE"});
  if (!response.ok && response.status !== 404) return;
  if (id === sessionId) startNewConversation();
  await loadHistory();
}

async function loadHistory() {
  try {
    const response = await fetch("/api/conversations");
    conversations = response.ok ? await response.json() : [];
  } catch (_) {
    conversations = [];
  }
  renderHistory();
}

function renderHistory() {
  const list = document.querySelector("#history");
  list.replaceChildren();
  conversations.forEach(item => {
    const row = document.createElement("div");
    row.className = "history-row";
    const open = document.createElement("button");
    open.className = `history-item${item.id === sessionId ? " active" : ""}`;
    open.textContent = item.title;
    open.title = item.title;
    open.addEventListener("click", () => loadConversation(item.id));
    const remove = document.createElement("button");
    remove.className = "history-delete";
    remove.textContent = "×";
    remove.title = "Delete conversation";
    remove.addEventListener("click", () => deleteConversation(item.id));
    row.append(open, remove);
    list.appendChild(row);
  });
}

function showApproval(approval) {
  const box = document.createElement("div");
  box.className = "approval";
  const text = document.createElement("div");
  text.textContent = `${approval.description}\nExpires: ${new Date(approval.expires_at).toLocaleString()}`;
  box.appendChild(text);
  [["Approve", true, ""], ["Reject", false, "secondary"]].forEach(([label, approved, style]) => {
    const button = document.createElement("button");
    button.textContent = label;
    button.className = `button ${style}`;
    button.addEventListener("click", async () => {
      box.querySelectorAll("button").forEach(item => { item.disabled = true; });
      try {
        const response = await fetch(`/api/approvals/${approval.id}`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({approved}),
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "Approval failed");
        addMessage(approved ? `Approved action result:\n${JSON.stringify(body.outcome, null, 2)}` : "Action rejected.");
        box.remove();
      } catch (error) {
        addMessage(error.message, "error");
      }
    });
    box.appendChild(button);
  });
  chat.appendChild(box);
  chat.scrollTop = chat.scrollHeight;
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const text = message.value.trim();
  if (!text) return;
  addMessage(text, "user");
  message.value = "";
  send.disabled = true;
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: text, session_id: sessionId}),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "Request failed");
    sessionId = body.session_id;
    addMessage(body.message, "assistant", body.artifacts || []);
    if (body.pending_approval) showApproval(body.pending_approval);
    await loadHistory();
  } catch (error) {
    addMessage(error.message, "error");
  } finally {
    send.disabled = false;
    message.focus();
  }
});

document.querySelector("#new-chat").addEventListener("click", startNewConversation);
fetch("/api/config").then(response => response.json()).then(config => {
  document.querySelector("#meta").textContent =
    `${config.model} on ${config.ollama_device_name} · ${config.proxmox_configured ? "Proxmox connected" : "Setup required"}`;
  const warning = document.querySelector("#warning");
  const insecureServices = [];
  if (config.proxmox_insecure_tls) insecureServices.push("Proxmox");
  if (config.crafty_insecure_tls) insecureServices.push("Crafty");
  warning.textContent = insecureServices.length
    ? `Warning: TLS verification is explicitly disabled for ${insecureServices.join(" and ")}. Trust the service CA instead.`
    : "";
  warning.style.display = insecureServices.length ? "block" : "none";
  if (config.voice_available && navigator.mediaDevices && window.MediaRecorder) voice.hidden = false;
});
loadHistory();

voice.addEventListener("click", async () => {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
    voice.textContent = "Record";
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.addEventListener("dataavailable", event => chunks.push(event.data));
    recorder.addEventListener("stop", async () => {
      stream.getTracks().forEach(track => track.stop());
      const audio = new Blob(chunks, {type: recorder.mimeType});
      voice.disabled = true;
      try {
        const response = await fetch("/api/transcribe", {
          method: "POST",
          headers: {"X-Audio-Extension": ".webm"},
          body: audio,
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "Transcription failed");
        message.value = body.text;
        message.focus();
      } catch (error) {
        addMessage(error.message, "error");
      } finally {
        voice.disabled = false;
      }
    });
    recorder.start();
    voice.textContent = "Stop";
  } catch (error) {
    addMessage(`Microphone unavailable: ${error.message}`, "error");
  }
});
