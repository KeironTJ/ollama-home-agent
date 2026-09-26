# Home Diagnostic Agent

A local, safety-bounded chat UI for investigating a home server with Ollama, the documented Proxmox HTTPS JSON API, and optional restricted SSH diagnostics. It is designed for questions such as **“my Minecraft server stopped working”**.

The agent is read-only by default. Restarting a service or starting/rebooting a guest creates a short-lived pending approval in the UI. Only the explicit **Approve** button can execute it; chat text can never count as approval. Targets are enforced against code-level node, guest, host, service, and port allowlists.

## Windows setup

Prerequisites:

- Windows PowerShell
- Python 3.11 or newer (`python --version`)
- Ollama 0.34.4 running locally with `llama3.1:8b`

From this repository:

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[test]"
Copy-Item .env.example .env
ollama pull llama3.1:8b
ollama serve
```

Run the app in a second PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m home_agent
```

Open <http://127.0.0.1:8080>. Check <http://127.0.0.1:8080/health> if chat reports that Ollama is unavailable. `llama3.1:8b` is the recommended default because it supports Ollama tool calling; change `HOME_AGENT_OLLAMA_MODEL` if another installed model proves more reliable in your environment.

## Proxmox least-privilege token

Create a dedicated audit-only identity in the Proxmox shell or UI. The CLI example below creates `home-agent@pve`, grants the built-in `PVEAuditor` role at `/`, and creates a separated-privilege API token:

```text
pveum user add home-agent@pve --comment "Local diagnostic agent"
pveum acl modify / -user home-agent@pve -role PVEAuditor
pveum user token add home-agent@pve diagnostic --privsep 1
pveum acl modify / -token 'home-agent@pve!diagnostic' -role PVEAuditor
```

Copy the token secret once into your untracked `.env`:

```dotenv
HOME_AGENT_PROXMOX_TOKEN_ID=home-agent@pve!diagnostic
HOME_AGENT_PROXMOX_TOKEN_SECRET=the-one-time-token-secret
```

`PVEAuditor` is enough for inventory, node/guest status, and recent tasks. It intentionally cannot perform start/reboot operations. If you later want approved guest power actions, create a **separate custom role** limited to the required guests and only the necessary `VM.PowerMgmt` privilege, then assign it to the token at `/vms/<VMID>`. Do not grant `Administrator`.

## Trust the Proxmox certificate

TLS verification is on by default. With the current self-signed certificate at `https://192.168.1.232:8006`, export the Proxmox cluster CA certificate and configure it rather than disabling TLS.

On the Proxmox node, copy `/etc/pve/pve-root-ca.pem` to a safe local path such as `C:\Users\you\.config\home-agent\pve-root-ca.pem`. Verify its fingerprint over a trusted channel, then set:

```dotenv
HOME_AGENT_PROXMOX_CA_FILE=C:\Users\you\.config\home-agent\pve-root-ca.pem
HOME_AGENT_PROXMOX_INSECURE_TLS=false
```

As a temporary private-network diagnostic only, `HOME_AGENT_PROXMOX_INSECURE_TLS=true` disables certificate verification. This is opt-in, is unsafe against interception, and displays a prominent warning in the UI.

## Configure allowlists

Only configured targets are visible or callable:

```dotenv
HOME_AGENT_PROXMOX_ALLOWED_NODES=pve
HOME_AGENT_PROXMOX_ALLOWED_GUESTS=100,101
```

For example, if Minecraft is VM `100`, include `100`. Guest discovery only searches this allowlisted subset.

Optional SSH uses a dedicated key and rejects unknown host keys. Password authentication and arbitrary shell commands are not supported:

```dotenv
HOME_AGENT_SSH_USERNAME=diagnostic-agent
HOME_AGENT_SSH_KEY_FILE=C:\Users\you\.ssh\home-agent
HOME_AGENT_SSH_HOSTS_JSON={"minecraft":{"hostname":"192.168.1.50","services":["minecraft"],"ports":[25565]}}
```

Install SSH support:

```powershell
pip install -e ".[ssh]"
```

On the Linux guest, create the unprivileged `diagnostic-agent` account, add its public key to `~/.ssh/authorized_keys`, and connect once manually to record the host key in the Windows user’s `known_hosts`. Read-only commands are fixed to `systemctl status`, bounded `journalctl`, `df`, and `free`. The configured user needs permission to read the relevant journal. If approved service restarts are desired, add a tightly scoped sudoers rule for only that exact unit, for example:

```text
diagnostic-agent ALL=(root) NOPASSWD: /usr/bin/systemctl restart minecraft
```

Do not grant a shell wildcard or unrestricted `sudo`. The application validates service names and membership in the per-host allowlist before constructing this fixed command.

Configuration can also come from a JSON object by setting `HOME_AGENT_CONFIG_FILE`; environment variables override defaults, while values explicitly loaded from that file provide local configuration. Never commit `.env`, private keys, tokens, or CA private material.

## Optional local voice input

Text chat always works without voice packages. For local CPU transcription:

```powershell
pip install -e ".[voice]"
```

The browser records audio and sends it only to this local FastAPI server, where `faster-whisper` transcribes it. No browser cloud speech API is used. The first transcription may download the configured Whisper model; pre-stage it if the machine must remain offline. Set `HOME_AGENT_WHISPER_MODEL_SIZE=tiny` or another local faster-whisper model size.

## Safety and audit behavior

- Ollama receives a strict system prompt and a maximum of 5 tool iterations, 4 calls per turn, 45 seconds total, 900 generated tokens per call, and bounded tool output.
- Tool output and logs are treated as untrusted data and cannot become instructions.
- Mutations produce single-use approval UUIDs that expire after 5 minutes. Approvals are transactionally claimed before execution.
- Proxmox uses `/api2/json/...`; the UI is never scraped.
- SQLite audit data is stored at `data\audit.sqlite3`. It records messages, tool calls/outcomes, and approvals with common secrets redacted and output truncated.
- SSH exposes no arbitrary command endpoint. Host keys must already be trusted.
- The web server binds to `127.0.0.1` by default. Add authentication and TLS before exposing it beyond the local machine.

Run the focused test suite:

```powershell
pytest -q
```
