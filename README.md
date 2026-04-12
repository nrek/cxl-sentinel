# CXL Sentinel

Lightweight deployment tracking for manually deployed web applications.

CXL Sentinel monitors git-based project directories on your servers, detects when deployments happen, and records the events to a central API. It is designed for teams that deploy manually or semi-manually and want visibility into what was deployed, when, and by whom -- without adopting a full CI/CD pipeline.

## Features

- **Git-based detection**: Watches `HEAD` for changes in configured project directories
- **Commit metadata capture**: Hash, author, message, timestamp, changed file count
- **Multi-tenant**: Supports multiple clients, projects, servers, and environments
- **Systemd service or cron**: Runs as a persistent service (preferred) or one-shot via cron
- **Offline resilience**: Queues events locally when the API is unreachable
- **Token authentication**: Per-agent bearer tokens with role-based access
- **Email notifications**: Branded HTML emails via SMTP or SendGrid with per-project subscriber rules
- **Minimal dependencies**: Agent requires only `requests` and `pyyaml`

## Architecture

```
┌─────────────────────┐       HTTPS         ┌─────────────────────┐
│   Server (Agent)    │ ──────────────────▶|    Central (API)    │
│                     │  POST /api/v1/events│                     │
│  - scans git repos  │  POST /api/v1/hbeat │  - FastAPI + SQLite │
│  - systemd service  │                     │  - token auth       │
│  - offline queue    │                     │  - query endpoints  │
└─────────────────────┘                     └─────────────────────┘
```

Agents run on each monitored server. The central API can run on any server reachable by the agents.

---

## Prerequisites

### Agent (each monitored server)

| Requirement   | Minimum | Notes                                      |
|---------------|---------|---------------------------------------------|
| OS            | Ubuntu 20.04+ | Any systemd-based Linux works        |
| Python        | 3.10+   | Used for the agent process                   |
| Git           | 2.25+   | Must be installed and on `PATH`              |
| systemd       | 232+    | For service mode; optional if using cron     |
| Network       | outbound HTTPS | Agent must reach the central API URL  |
| Disk          | ~20 MB  | Agent code, venv, state file, log rotation   |

The monitored project directories must be git repositories. The agent reads git metadata -- it does not modify repositories.

### Central API server

| Requirement   | Minimum | Notes                                      |
|---------------|---------|---------------------------------------------|
| OS            | Ubuntu 20.04+ | Any Linux or container runtime       |
| Python        | 3.10+   | FastAPI + Uvicorn                            |
| Disk          | ~50 MB+ | Grows with event volume; SQLite DB + logs    |
| Network       | inbound on port 8400 | Or custom port behind a reverse proxy |

For production, place the API behind a reverse proxy (Nginx, Caddy, ALB) with TLS termination.

### Development machine

| Requirement   | Minimum | Notes                                      |
|---------------|---------|---------------------------------------------|
| Python        | 3.10+   |                                              |
| Git           | 2.25+   |                                              |
| pip           | 22+     |                                              |

---

## Quick Start

### 1. Set up the Central API

```bash
git clone https://github.com/nrek/cxl-sentinel.git
cd cxl-sentinel

python3 -m venv .venv
source .venv/bin/activate
pip install -r api/requirements.txt

# Copy and edit the config BEFORE initializing the database
cp api/config.yaml.example api/config.yaml
# Edit api/config.yaml with your database URL and settings
nano api/config.yaml

# Initialize the database and create your first admin token
python api/manage.py init-db
python api/manage.py create-token --name "admin" --role admin
# Save the printed token -- it will not be shown again

# Create an agent token for your first server
python api/manage.py create-token --name "prod-web-01" --role agent

# Start the API (foreground, for testing)
uvicorn api.main:app --host 0.0.0.0 --port 8400
```

> For production, run the API as a systemd service instead of in the foreground. See [Running the API in Production](#running-the-api-in-production) below.

### 2. Install the Agent on a server

```bash
git clone https://github.com/nrek/cxl-sentinel.git /tmp/cxl-sentinel
cd /tmp/cxl-sentinel
sudo bash agent/install.sh
```

After installation:

```bash
# Edit the agent config with your API URL, token, and project paths
sudo nano /etc/sentinel/agent.yaml

# Enable and start the service
sudo systemctl enable --now sentinel-agent

# Verify it is running
sudo systemctl status sentinel-agent
sudo journalctl -u sentinel-agent -f
```

### 3. Verify agent ↔ central connectivity

**On the agent machine** (same host where the agent runs), use the built-in check. It hits the public health endpoint (no auth), then sends an authenticated heartbeat using your `agent.yaml`:

```bash
# Installed agent (/opt/sentinel) — run from repo root so `agent` is importable
cd /opt/sentinel
sudo -u sentinel ./venv/bin/python -m agent.verify_connection --config /etc/sentinel/agent.yaml

# Same check, full path to script (no `cd`; works after you deploy verify_connection.py)
sudo -u sentinel /opt/sentinel/venv/bin/python /opt/sentinel/agent/verify_connection.py \
  --config /etc/sentinel/agent.yaml

# From a git checkout (repo root)
python -m agent.verify_connection --config /path/to/agent.yaml
```

If you see `No module named agent.verify_connection`, `/opt/sentinel/agent/` is missing that file (install was from an older tree). **Pull latest** into a git checkout (not `/opt/sentinel` — that tree is not a clone), then run `sudo bash agent/install.sh` from the **repo root**, or copy `agent/verify_connection.py` into `/opt/sentinel/agent/`.

**`/opt/sentinel` is not a git repository** — deploy updates from a clone elsewhere (`git pull` → `sudo bash agent/install.sh`). Re-running `install.sh` from `/opt/sentinel` is supported (in-place upgrade); older scripts incorrectly deleted the source before copying; use the latest `install.sh` if you see `cp: cannot stat` after `rm -rf`.

If `/opt/sentinel/agent` was removed accidentally, restore from a fresh clone on the server: `git clone … /tmp/cxl-sentinel && cd /tmp/cxl-sentinel && sudo bash agent/install.sh`.

You should see `OK` for both steps. If step 1 fails, fix DNS, TLS, firewall, or the reverse proxy to central. If step 2 fails with `401`, the token is wrong or revoked — create a new agent token on central and update `api_token` in `agent.yaml`.

**On the central server** (or any machine that can reach the API with an admin token), confirm the heartbeat was stored:

```bash
curl -sS -H "Authorization: Bearer <admin-token>" \
  "https://sentinel.example.com/api/v1/servers" | python3 -m json.tool
```

Look for your `server_id` and a recent `last_seen` / `is_alive`.

---

## Agent Configuration

The agent reads `/etc/sentinel/agent.yaml`:

```yaml
sentinel:
  api_url: "https://sentinel.example.com/api/v1"
  api_token: "sk-agent-xxxxxxxxxxxx"
  server_id: "prod-web-01"
  environment: "production"   # production | staging
  scan_interval: 300           # seconds between scans (service mode)
  state_file: "/var/lib/sentinel/state.json"

projects:
  - name: "my-web-app"
    path: "/var/www/my-web-app"
    client: "acme-corp"
    branch: "main"
  - name: "my-dashboard"
    path: "/var/www/my-dashboard"
    client: "acme-corp"
    branch: "main"

logging:
  level: "INFO"
  file: "/var/log/sentinel/agent.log"
  max_bytes: 10485760          # 10 MB
  backup_count: 5
```

### Configuration Reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `sentinel.api_url` | string | *required* | Full URL to the central API (include `/api/v1`) |
| `sentinel.api_token` | string | *required* | Bearer token for this agent |
| `sentinel.server_id` | string | *required* | Unique identifier for this server |
| `sentinel.environment` | string | *required* | `production` or `staging` |
| `sentinel.scan_interval` | int | `300` | Seconds between scans in service mode |
| `sentinel.state_file` | string | `/var/lib/sentinel/state.json` | Path to state persistence file |
| `projects[].name` | string | *required* | Human-readable project name |
| `projects[].path` | string | *required* | Absolute path to the git repository |
| `projects[].client` | string | *required* | Client/organization identifier |
| `projects[].branch` | string | current HEAD | Branch to track |
| `logging.level` | string | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `logging.file` | string | `/var/log/sentinel/agent.log` | Log file path |
| `logging.max_bytes` | int | `10485760` | Max log file size before rotation |
| `logging.backup_count` | int | `5` | Number of rotated log files to keep |

---

## API Endpoints

All endpoints (except `/health`) require `Authorization: Bearer <token>`.

| Method | Path | Auth Role | Description |
|--------|------|-----------|-------------|
| `POST` | `/api/v1/events` | agent | Record a deploy event |
| `POST` | `/api/v1/heartbeat` | agent | Agent liveness heartbeat |
| `GET`  | `/api/v1/events` | admin, readonly | Query deploy events |
| `GET`  | `/api/v1/servers` | admin, readonly | List servers and heartbeat status |
| `GET`  | `/api/v1/health` | *none* | API health check |

See the [API contract](docs/api.md) for full request/response schemas (generated after first run).

---

## Email Notifications

CXL Sentinel can send branded HTML email notifications when deploys are detected. Two providers are supported -- configure one in `api/config.yaml`:

### Provider: SMTP (Gmail, Outlook, self-hosted)

```yaml
notifications:
  smtp:
    enabled: true
    host: "smtp.gmail.com"
    port: 587
    use_tls: true
    username: "sentinel@example.com"
    password: "your-app-password"
    from_address: "sentinel@example.com"
    from_name: "Deploy Notifications"
```

For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833) rather than your account password.

### Provider: SendGrid

```yaml
notifications:
  sendgrid:
    enabled: true
    api_key: "SG.xxxxxxxxxxxx"
    from_address: "sentinel@example.com"
    from_name: "Deploy Notifications"
```

If both providers are enabled, SendGrid takes priority.

### Notification Rules

Rules map projects and clients to recipient lists. Use `"*"` as a wildcard. Multiple rules can overlap -- recipients are de-duplicated.

```yaml
notifications:
  rules:
    # All production deploys go to the ops team
    - project: "*"
      client: "*"
      environments: ["production"]
      recipients:
        - "ops-team@example.com"
        - "lead@example.com"

    # Client-specific notifications
    - project: "my-web-app"
      client: "acme-corp"
      environments: ["production", "staging"]
      recipients:
        - "client@acme-corp.com"
```

### Branding

Customize the email appearance:

```yaml
notifications:
  branding:
    logo_url: "https://example.com/logo.png"
    accent_color: "#2563eb"
    company_name: "Your Company"
    footer_text: "Managed by Your Company"
```

The HTML template is in `api/notifications/templates/deploy_notification.html` and can be edited directly for deeper customization.

---

## Running Modes

### Service mode (recommended)

The agent runs as a systemd service, scanning at a configurable interval:

```bash
sudo systemctl enable --now sentinel-agent
sudo systemctl status sentinel-agent
sudo journalctl -u sentinel-agent -f
```

### Oneshot mode (cron)

For environments where a persistent service is not desired:

```bash
# Manual test
/opt/sentinel/venv/bin/python /opt/sentinel/agent/agent.py --mode oneshot --config /etc/sentinel/agent.yaml

# Cron entry (every 5 minutes)
*/5 * * * * /opt/sentinel/venv/bin/python /opt/sentinel/agent/agent.py --mode oneshot --config /etc/sentinel/agent.yaml >> /var/log/sentinel/cron.log 2>&1
```

---

## Uninstalling the Agent

```bash
sudo bash /opt/sentinel/agent/uninstall.sh
```

This stops the service, removes the systemd unit, deletes `/opt/sentinel`, `/etc/sentinel`, `/var/lib/sentinel`, and the `sentinel` system user. Log files in `/var/log/sentinel/` are preserved for review.

---

## Running the API in Production

For production, run the central API as a systemd service rather than in the foreground.

Create `/etc/systemd/system/sentinel-api.service`:

```ini
[Unit]
Description=CXL Sentinel API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/cxl-sentinel
ExecStart=/var/www/cxl-sentinel/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8400
Restart=on-failure
RestartSec=10
Environment=SENTINEL_CONFIG=/var/www/cxl-sentinel/api/config.yaml
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Then enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sentinel-api
sudo systemctl status sentinel-api
sudo journalctl -u sentinel-api -f
```

#### Heartbeat returns 500 but `/health` is OK

`/health` does not touch the database; **`POST /heartbeat` writes SQLite**. A 500 almost always means the API process cannot write the DB file or the file’s schema is older than the code.

1. **Inspect the real error** (on the central server):

   ```bash
   sudo journalctl -u sentinel-api -n 80 --no-pager
   ```

   Look for `OperationalError`, `readonly database`, or `no such column`.

2. **Fix permissions** — the user running Uvicorn (often `www-data`) must own or be able to write the DB and WAL files next to it:

   ```bash
   sudo chown -R www-data:www-data /var/www/cxl-sentinel/sentinel.db /var/www/cxl-sentinel/sentinel.db-wal /var/www/cxl-sentinel/sentinel.db-shm 2>/dev/null
   # or chown the whole project dir if the DB lives there
   sudo systemctl restart sentinel-api
   ```

   If `database_url` uses an absolute path (e.g. `sqlite:////var/lib/sentinel/sentinel.db`), ensure that path exists and is writable by the service user.

3. **Schema drift** — after upgrading code, restart `sentinel-api` once so startup can run SQLite column fixes (`commit_count` / `contributors` on `deploy_events`). If problems persist, paste the journal traceback.

Bind to `127.0.0.1` and place a reverse proxy (Nginx, Caddy) in front for TLS. A minimal Nginx config:

```nginx
server {
    listen 443 ssl;
    server_name sentinel.example.com;

    ssl_certificate     /etc/letsencrypt/live/sentinel.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sentinel.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8400;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### After `git pull` on a server

Python is loaded once at startup. **Restart** the service that owns the code you updated, or changes will not apply.

| What you changed | Action |
|------------------|--------|
| **Central API** code or `api/requirements.txt` under e.g. `/var/www/cxl-sentinel` | `cd` there → `git pull` → `pip install -r api/requirements.txt` if deps changed → `sudo systemctl restart sentinel-api` |
| **Agent** code or `agent/requirements.txt` under e.g. `/opt/sentinel` | `git pull` (or re-copy from your checkout) → `pip install -r agent/requirements.txt` if deps changed → `sudo systemctl restart sentinel-agent` |
| **`api/config.yaml`** or **`/etc/sentinel/agent.yaml`** only | Restart the matching service so the process reloads config (`sentinel-api` / `sentinel-agent`). |

Quick checks:

```bash
sudo systemctl status sentinel-api sentinel-agent
sudo journalctl -u sentinel-api -n 30 --no-pager
sudo journalctl -u sentinel-agent -n 30 --no-pager
```

---

## Development

```bash
git clone https://github.com/nrek/cxl-sentinel.git
cd cxl-sentinel
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r agent/requirements.txt -r api/requirements.txt

# Run tests
pytest tests/ -v

# Run the API locally
python api/manage.py init-db
python api/manage.py create-token --name "dev" --role admin
cp api/config.yaml.example api/config.yaml
uvicorn api.main:app --reload --port 8400

# Run the agent in oneshot mode against local API
cp agent/agent.yaml.example agent.yaml
# Edit agent.yaml: set api_url to http://localhost:8400/api/v1
python agent/agent.py --mode oneshot --config agent.yaml
```

---

## Project Structure

```
cxl-sentinel/
├── README.md
├── LICENSE
├── SECURITY.md
├── CONTRIBUTING.md
├── VERSION
├── requirements.txt            # dev dependencies (pytest, ruff)
├── .gitignore
├── agent/
│   ├── agent.py                # entry point: --mode service|oneshot
│   ├── verify_connection.py    # test health + heartbeat to central
│   ├── config.py               # YAML config loader + validation
│   ├── detector.py             # git change detection
│   ├── collector.py            # commit metadata extraction
│   ├── reporter.py             # HTTP client for the central API
│   ├── queue.py                # offline event queue
│   ├── state.py                # state file persistence
│   ├── requirements.txt        # agent runtime deps
│   ├── install.sh              # server install script
│   ├── uninstall.sh            # server removal script
│   ├── sentinel-agent.service  # systemd unit file
│   └── agent.yaml.example      # example configuration
├── api/
│   ├── main.py                 # FastAPI application
│   ├── config.py               # API config loader
│   ├── auth.py                 # bearer token middleware
│   ├── models.py               # SQLAlchemy ORM models
│   ├── schemas.py              # Pydantic request/response schemas
│   ├── database.py             # DB engine + session factory
│   ├── routers/
│   │   ├── events.py           # deploy event endpoints
│   │   ├── heartbeat.py        # heartbeat endpoint
│   │   ├── servers.py          # server listing endpoint
│   │   └── health.py           # health check
│   ├── notifications/
│   │   ├── dispatcher.py       # rule matching + provider routing
│   │   ├── renderer.py         # HTML template engine
│   │   ├── smtp_provider.py    # SMTP/Gmail sender
│   │   ├── sendgrid_provider.py # SendGrid API sender
│   │   └── templates/
│   │       └── deploy_notification.html
│   ├── manage.py               # CLI: init-db, create-token
│   ├── requirements.txt        # API runtime deps
│   └── config.yaml.example     # example configuration
└── tests/
    ├── test_detector.py
    ├── test_collector.py
    ├── test_reporter.py
    ├── test_api_events.py
    └── test_api_auth.py
```

---

## Security

See [SECURITY.md](SECURITY.md) for the security policy, architecture details, and responsible disclosure instructions.

Key points:
- Tokens are SHA-256 hashed at rest; plaintext only in agent config files (mode `0600`)
- Agent runs as an unprivileged `sentinel` system user
- HTTPS is required for production deployments
- All API input is validated via Pydantic with strict types

---

## License

[MIT](LICENSE)
