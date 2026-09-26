const chat = document.querySelector("#chat");
const form = document.querySelector("#chat-form");
const message = document.querySelector("#message");
const send = document.querySelector("#send");
const voice = document.querySelector("#voice");
let sessionId = crypto.randomUUID();
let conversations = [];
let recorder;
let chunks = [];

function addMessage(text, kind = "assistant") {
  const element = document.createElement("div");
  element.className = `message ${kind}`;
  element.textContent = text;
  chat.appendChild(element);
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
    conversation.messages.forEach(item => addMessage(item.content, item.role));
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
    addMessage(body.message);
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
    `${config.model} · ${config.proxmox_configured ? "Proxmox connected" : "Setup required"}`;
  document.querySelector("#warning").style.display = config.insecure_tls ? "block" : "none";
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
