# Home Diagnostic Agent

An always-on, safety-bounded home-server coordinator with a local web chat, Ollama inference, the documented Proxmox and Crafty HTTPS APIs, and optional restricted SSH diagnostics. Ollama may run beside the app or on an allowlisted Wake-on-LAN laptop.

The agent is read-only by default. Restarting a service or starting/rebooting a guest creates a short-lived pending approval in the UI. Only the explicit **Approve** button can execute it; chat text can never count as approval. Targets are enforced against code-level node, guest, host, service, and port allowlists.

## Project structure

The application uses a FastAPI application factory and focused routers:

```text
src/home_agent/
├── app.py             # create_app() and router registration
├── container.py       # construction of shared application services
├── dependencies.py    # typed FastAPI dependencies and local-access guards
├── schemas.py         # HTTP request models
├── core/
│   ├── config.py      # typed configuration and source loading
│   └── security.py    # redaction and output bounds
├── services/
│   ├── agent.py       # bounded Ollama orchestration loop
│   ├── coordinator.py # fixed routing and specialist execution
│   ├── specialists.py # specialist definitions and tool scopes
│   ├── approvals.py   # transactional approval lifecycle
│   ├── audit.py       # security audit persistence
│   └── history.py     # bounded conversation persistence
├── integrations/
│   ├── crafty.py      # Crafty Controller v2 API client
│   ├── ollama.py      # local model API client
│   ├── proxmox.py     # TLS-verified Proxmox API client
│   ├── wake_on_lan.py # fixed-target magic packet generation
│   └── errors.py      # safe integration errors
├── tools/
│   ├── crafty.py      # Minecraft/Crafty schemas and operations
│   ├── registry.py    # common invocation, audit, and dispatch facade
│   ├── proxmox.py     # Proxmox schemas and allowlisted operations
│   ├── ssh.py         # restricted SSH schemas and operations
│   └── base.py        # shared tool contracts
├── templates/
│   ├── base.html
│   ├── components/    # reusable server-rendered UI fragments
│   └── pages/         # landing and agent pages
├── static/
│   ├── css/           # shared and page-specific styles
│   └── js/            # landing, setup, and chat behavior
├── routers/
│   ├── pages.py
│   ├── system.py
│   ├── chat.py
│   ├── history.py
│   ├── approvals.py
│   ├── setup.py
│   └── voice.py
```

`container.py` is the composition root: it creates clients, persistence services, approvals, tool sets, and the agent runner once per application instance. Dependencies flow inward from routers to services/tools, then to explicit integrations and core primitives. New HTTP surfaces use a router; new diagnostic capabilities use an isolated tool set and are registered in `tools/registry.py`.

The master coordinator routes each request to a fixed specialist registry. Minecraft, Proxmox, network, and general diagnostics each receive a narrow prompt and an explicit subset of currently available tools. Model-generated specialist names or tools cannot be loaded dynamically, and every specialist shares the same allowlist, audit, output-limit, and approval boundaries.

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

The root page is an agent dashboard. Open **Home diagnostics** to use the chat at <http://127.0.0.1:8080/agents/home-diagnostics>. Typed tool results are returned as structured artifacts and rendered as status cards with human-readable CPU, memory, uptime, guests, and ports. Conversations and their artifacts are stored locally in the same SQLite database as the audit data, with secret redaction, bounded message sizes, a 200-message limit per conversation, and a 100-conversation retention limit. The chat sidebar can reopen or delete saved conversations.

Open **Configuration** from the landing dashboard to configure non-secret local settings such as URLs, model, CA path, token ID, and Proxmox allowlists. The setup component writes the ignored `home-agent.config.json` file. Click **Restart application** to stop Uvicorn gracefully, reload configuration, restart on the same port, and refresh the page; this is available when launched with `python -m home_agent`. Setup and restart are available from localhost when the app is bound to localhost, or from any client when `HOME_AGENT_ADMIN_PASSWORD` is set (see Linux server deployment), and both writes require a per-process anti-CSRF token. The Proxmox token secret is deliberately never returned to or stored by the web page; keep it in `.env`.

## Always-on server with a Wake-on-LAN Ollama laptop

The FastAPI application is the coordinator. It retains chat history and audit data, selects specialists, exposes tools, validates allowlists, and executes approved operations. The laptop runs only Ollama inference; it receives prompts and tool schemas but no infrastructure credentials.

Configure the laptop from the dashboard or with:

```dotenv
HOME_AGENT_OLLAMA_URL=http://192.168.1.50:11434
HOME_AGENT_OLLAMA_MODEL=llama3.1:8b
HOME_AGENT_OLLAMA_DEVICE_NAME=AI laptop
HOME_AGENT_OLLAMA_WOL_ENABLED=true
HOME_AGENT_OLLAMA_WOL_MAC=AA:BB:CC:DD:EE:FF
HOME_AGENT_OLLAMA_WOL_BROADCAST=192.168.1.255
HOME_AGENT_OLLAMA_WOL_PORT=9
HOME_AGENT_OLLAMA_WAKE_TIMEOUT_SECONDS=90
```

When a chat request arrives, Home Agent first checks `/api/tags`. If Ollama is unavailable, it sends one standard magic packet to the configured MAC/broadcast/port, polls only the configured Ollama URL until the wake deadline, audits the wake, and then starts the normal bounded agent loop. Health checks never wake the laptop.

On the laptop, enable Wake-on-LAN in firmware and the network adapter, arrange for Ollama to start after wake, set Ollama to listen on the LAN interface, and restrict TCP `11434` in the laptop firewall to the Home Agent server IP. Wired Ethernet is recommended; Wake-on-WLAN and wake from full shutdown depend on the laptop hardware.

## Linux server deployment

Run Home Agent in a dedicated unprivileged Debian 12 or Ubuntu LXC rather than on the Proxmox host or Minecraft guest. The installer runs **inside an existing container**; it does not create or configure the LXC itself.

Recommended LXC properties:

- Unprivileged container
- 2 vCPU, 2 GiB RAM, and 8 GiB disk for the coordinator
- Bridged network interface on the home LAN so UDP broadcast can reach the laptop
- Static DHCP reservation
- `nesting` is not required

Copy or clone this repository into the LXC, then run:

```bash
cd /path/to/ollama-home-agent
sudo bash ./deploy/install-lxc.sh
```

The idempotent installer:

- installs only Python, venv, pip, and CA prerequisites through `apt`;
- creates the non-login `home-agent` service account;
- installs the application under `/opt/home-agent`;
- preserves existing secrets and state on repeat runs;
- creates `/etc/home-agent/home-agent.env` with mode `0640`;
- stores writable configuration/audit data under `/var/lib/home-agent`;
- installs and enables the hardened systemd service;
- does not start a new installation unless `--start` is supplied.

Edit the environment file and add only the API secrets:

```bash
sudoedit /etc/home-agent/home-agent.env
sudo systemctl start home-agent
sudo systemctl --no-pager --full status home-agent
curl http://127.0.0.1:8080/health
```

The supplied unit binds to `0.0.0.0`, keeps secrets in a root-owned environment file, stores writable state under `/var/lib/home-agent`, drops privileges, and applies basic systemd hardening. Limit port `8080` to the trusted LAN with the host firewall. For access outside the LAN, use an authenticated VPN or an HTTPS reverse proxy with authentication; do not expose Uvicorn directly to the internet.

To use **Configuration** directly at `http://<lxc-ip>:8080`, set an admin password (12+ characters) in `/etc/home-agent/home-agent.env` and restart:

```bash
openssl rand -base64 18   # example generator
sudoedit /etc/home-agent/home-agent.env   # HOME_AGENT_ADMIN_PASSWORD=...
systemctl restart home-agent
```

The Configuration dialog then asks for the password; it is held only in page memory and sent in a request header. Ten wrong attempts lock that client out for five minutes, and failures are audited. Without the password, Configuration is refused for every non-localhost request. Plain HTTP exposes the password to anyone sniffing your LAN, so use this only on a trusted home network; add an HTTPS reverse proxy for anything stronger.

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

Optional SSH uses a dedicated key and rejects unknown host keys. Password authentication and arbitrary shell commands are not supported. Configure hosts in the dashboard under **Configuration → Restricted SSH hosts**, or directly with:

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

## Optional Crafty Controller integration

Crafty Controller 4 exposes an official HTTPS API under `/api/v2`. Configure its URL, CA certificate, and allowed server IDs on the dashboard. Keep API keys in `.env`:

```dotenv
HOME_AGENT_CRAFTY_READ_TOKEN=
HOME_AGENT_CRAFTY_ACTION_TOKEN=
```

Use two dedicated, non-full-access Crafty API keys. The read key should be scoped only to the two managed servers with terminal/log visibility and no Crafty-wide user, role, or server-creation permissions. The separate action key may add only the per-server Commands permission and is loaded only for an already-approved start, stop, or restart. The application never exposes Crafty stdin, file management, kill, executable update, user management, or role management.

Crafty uses HTTPS port `8443` by default and commonly starts with a self-signed certificate. Trust/export that certificate through `HOME_AGENT_CRAFTY_CA_FILE`; keep `HOME_AGENT_CRAFTY_INSECURE_TLS=false`. After saving and restarting, **Discover token-visible servers** can populate the allowlist from the authenticated API without exposing server paths or credentials.

## Optional local voice input

Text chat always works without voice packages. For local CPU transcription:

```powershell
pip install -e ".[voice]"
```

The browser records audio and sends it only to this local FastAPI server, where `faster-whisper` transcribes it. No browser cloud speech API is used. The first transcription may download the configured Whisper model; pre-stage it if the machine must remain offline. Set `HOME_AGENT_WHISPER_MODEL_SIZE=tiny` or another local faster-whisper model size.

## Safety and audit behavior

- Ollama receives a strict system prompt and a maximum of 5 tool iterations, 4 calls per turn, 45 seconds of agent execution after compute readiness, 900 generated tokens per call, and bounded tool output.
- Wake-on-LAN targets only the configured MAC and broadcast address, has a bounded readiness timeout, and exposes no arbitrary packet or remote-command tool.
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
