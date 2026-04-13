# CXL Sentinel

Lightweight deployment tracking for manually deployed web applications.

CXL Sentinel monitors git-based repo directories on your servers, detects when deployments happen, and records the events to a central API. It is designed for teams that deploy manually or semi-manually and want visibility into what was deployed, when, and by whom -- without adopting a full CI/CD pipeline.

## Table of contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Agent Configuration](#agent-configuration)
  - [Troubleshooting: dubious Git ownership](#troubleshooting-dubious-git-ownership)
- [Central API Configuration](#central-api-configuration)
  - [Notification Rules & Digest Scheduling](#notification-rules--digest-scheduling)
- [API Endpoints](#api-endpoints)
- [Email Notifications](#email-notifications)
- [Running Modes](#running-modes)
  - [NOTIFY: immediate scan after pull](#notify-immediate-scan-after-pull)
- [Uninstalling the Agent](#uninstalling-the-agent)
- [Running the API in Production](#running-the-api-in-production)
- [Development](#development)
- [Project Structure](#project-structure)
- [Security](#security)
- [License](#license)

## Features

- **Git-based detection**: Watches `HEAD` for changes in configured repo directories
- **Commit metadata capture**: Hash, author, message, timestamp, changed file count
- **Multi-server**: Supports multiple servers, repos, and environments under one Central API
- **Digest emails**: Batched summary emails on a configurable schedule (10m, 6h, 1d, 7d) anchored at midnight UTC
- **`[NOTIFY]` commits**: Bypasses the digest and sends an immediate email; subject is tagged `[NOTIFY]`
- **Systemd service or cron**: Runs as a persistent service (preferred) or one-shot via cron
- **Offline resilience**: Queues events locally when the API is unreachable
- **Token authentication**: Per-agent bearer tokens with role-based access
- **Branded HTML emails**: Via SMTP or SendGrid with server-level notification rules
- **Minimal dependencies**: Agent requires only `requests` and `pyyaml`

## Architecture

```
┌─────────────────────┐       HTTPS         ┌─────────────────────────┐
│   Server (Agent)    │ ──────────────────▶ │    Central (API)         │
│                     │  POST /api/v1/events│                          │
│  - scans git repos  │  POST /api/v1/hbeat │  - FastAPI + SQLite      │
│  - systemd service  │                     │  - token auth            │
│  - offline queue    │                     │  - digest scheduler      │
│                     │                     │  - [NOTIFY] immediate    │
└─────────────────────┘                     └──────────────────────────┘
```

Agents run on each monitored server. The central API can run on any server reachable by the agents. One API token (`sk-...`) can be shared across multiple servers using the same `server_id`.

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

The monitored repo directories must be git repositories. The agent reads git metadata -- it does not modify repositories.

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

# Initialize the database (drops + recreates tables) and create your first admin token
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
# Edit the agent config with your API URL, token, and repo paths
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

**`/opt/sentinel` is not a git repository** — deploy updates from a clone elsewhere (`git pull` → `sudo bash agent/install.sh`). Re-running `install.sh` from `/opt/sentinel` is supported (in-place upgrade).

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
  server_id: "acme-web"
  environment: "production"   # production | staging
  scan_interval: "5m"         # 5m, 10m, 1h, 6h (minimum 1m)
  state_file: "/var/lib/sentinel/state.json"

repos:
  - alias: "front-end"
    path: "/var/www/my-frontend"
    branch: "main"

  - alias: "backend"
    path: "/var/www/my-backend"
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
| `sentinel.server_id` | string | *required* | Unique identifier for this server/project group |
| `sentinel.environment` | string | *required* | `production` or `staging` |
| `sentinel.scan_interval` | string | `5m` | Duration between scans: `5m`, `10m`, `1h` (minimum `1m`) |
| `sentinel.state_file` | string | `/var/lib/sentinel/state.json` | Path to state persistence file |
| `repos[].alias` | string | *required* | Human-readable name for the repo |
| `repos[].path` | string | *required* | Absolute path to the git repository |
| `repos[].branch` | string | current HEAD | Branch to track |
| `logging.level` | string | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `logging.file` | string | `/var/log/sentinel/agent.log` | Log file path |
| `logging.max_bytes` | int | `10485760` | Max log file size before rotation |
| `logging.backup_count` | int | `5` | Number of rotated log files to keep |

**One token, many servers:** A single `api_token` (`sk-...`) can be reused across multiple servers sharing the same `server_id`. Each server reports its `environment` and the repos it watches. Central groups events by `server_id + environment`.

### Git safe.directory (automated fix)

On production servers the git checkout is often owned by **`www-data`** or another deploy user, while the Sentinel agent runs as the unprivileged **`sentinel`** user. Git 2.35+ treats that as **dubious ownership** and refuses to run in the repo. The agent logs a warning and skips the repo:

```text
Skipping 'front-end': git rev-parse HEAD failed: fatal: detected dubious ownership in repository at '/var/www/...'
```

**`install.sh` fixes this automatically** — during install or upgrade, it reads your `agent.yaml`, resolves each `repos[].path` to its canonical path, and registers it in `git config --system safe.directory`. This applies to all users on the host, including the `sentinel` systemd service.

If you add new repos to your config after installation, run the fix manually:

```bash
sudo bash /opt/sentinel/agent/fix-safe-dirs.sh
```

Or with an explicit config path:

```bash
sudo bash /opt/sentinel/agent/fix-safe-dirs.sh /etc/sentinel/agent.yaml
```

**Verify** (must succeed before the agent can scan):

```bash
sudo git config --system --get-all safe.directory
sudo -u sentinel git -C /var/www/your-app rev-parse HEAD
```

#### Why not `--global`?

**Do not use** `git config --global` for this. `--global` writes to a user's `~/.gitconfig`. The `sentinel` system user has **no home directory**, and `sentinel-agent.service` uses **`ProtectHome=yes`**, making `/home` invisible to the service. The `--system` scope (`/etc/gitconfig`) is the only one the daemon reads.

#### Manual fallback

If the automated script doesn't cover your case:

```bash
sudo git config --system --add safe.directory "$(readlink -f /var/www/your-app)"
```

Last resort (trust all paths — weaker security, Git 2.35.2+):

```bash
sudo git config --system --add safe.directory '*'
```

---

## Central API Configuration

The central API reads `api/config.yaml` (or the path in `SENTINEL_CONFIG`). See `api/config.yaml.example` for the full reference.

### Notification Rules & Digest Scheduling

Rules map a `server_id` (or `"*"` wildcard) to a list of recipient emails with a digest schedule:

```yaml
notifications:
  rules:
    - server_id: "acme-web"
      server_alias: "Acme Web"          # human-readable, used in email headers
      environments: ["production", "staging"]
      send_schedule: "6h"               # digest cadence: 10m, 6h, 1d, 7d
      recipients:
        - "ops@example.com"
        - "lead@example.com"

    - server_id: "*"
      environments: ["staging"]
      send_schedule: "10m"
      recipients:
        - "dev-team@example.com"
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `server_id` | string | `"*"` | Match against the agent's `sentinel.server_id`; `"*"` matches all |
| `server_alias` | string | server_id | Human-readable label used in email headers |
| `environments` | list | `["production", "staging"]` | Which environments trigger this rule |
| `send_schedule` | string | `"6h"` | Digest cadence: `10m`, `6h`, `1d`, `7d` |
| `recipients` | list | `[]` | Email addresses to receive the digest |

**How digests work:**

- Deploy events are stored in the database as they arrive.
- A background scheduler ticks every 60 seconds and checks each rule's window.
- Windows are anchored at **midnight UTC**: a `6h` schedule fires at 00:00, 06:00, 12:00, 18:00 UTC.
- When a window boundary is crossed, all unsent events for that `server_id + environment` are collected into a single **digest email**.
- If no events occurred since the last digest, no email is sent.

**`[NOTIFY]` bypass:** When a commit message starts with `[NOTIFY]`, the event is sent **immediately** as a single-event email (current behavior) in addition to appearing in the next digest. The digest template notes which events were already sent immediately.

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

---

## Email Notifications

CXL Sentinel sends branded HTML email notifications when deploys are detected. Two providers are supported -- configure one in `api/config.yaml`:

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

### Branding

Customize the email appearance:

```yaml
notifications:
  branding:
    logo_url: "https://example.com/logo.png"
    accent_color: "#2563eb"       # stats row + "Latest change" callout border (body)
    header_theme: "light"         # "dark" = light text on header; "light" = dark text
    header_background: "#cdcdcd"  # top banner strip only; omit to reuse accent_color
    company_name: "Your Company"
    footer_text: "Managed by Your Company"
```

Use `header_theme` + `header_background` when the logo is dark on a light strip (or the inverse): the header title, subtitle, and environment pill follow the theme. `accent_color` stays on the summary stats and the left border of the latest-commit block.

### Email templates

| Template | Used for |
|----------|----------|
| `api/notifications/templates/deploy_notification.html` | Single-event email (immediate `[NOTIFY]`) |
| `api/notifications/templates/digest_notification.html` | Batched digest summary |

Both templates support `{{ variable }}` and `{% if var %}...{% endif %}` blocks.

### Test email (dry-run)

From the repo root with `SENTINEL_CONFIG` pointing at your `config.yaml` (or `api/config.yaml` in cwd):

```bash
python api/manage.py test-email --dry-run
```

Prints the subject and full HTML using sample deploy data—no SMTP/SendGrid call. To send one real test message with the same template and your enabled provider:

```bash
python api/manage.py test-email --to you@example.com
```

Optional flags: `--repo-alias`, `--server`, `--environment` (`production` or `staging`), `--message`, `--author`, `--files`, `--commits`, `--contributor` (comma-separated), `--branch`, `--detected-at`.

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

### NOTIFY: immediate scan after pull

Long `scan_interval` values mean a deploy can sit on disk for minutes before the next scan. If the **latest commit's first line** starts with **`[NOTIFY]`** (example: `[NOTIFY] Hotfix payment callback`), you can:

1. **Immediate email** — the central API sends the notification **immediately** to all matched recipients, bypassing the digest schedule. The email subject is prefixed with `[NOTIFY]`.
2. **Skip the rest of the wait** — signal the agent to run the next scan **immediately** instead of sleeping until `scan_interval` elapses:

   ```bash
   sudo systemctl kill --signal=SIGUSR1 sentinel-agent
   ```

   The running service catches `SIGUSR1`, ends the sleep early, and runs another full scan cycle on the next loop iteration.

**Git hook (recommended):** after `git pull` / merge, only signal when the new `HEAD` commit uses the prefix. Copy and adapt the example:

`agent/hooks/post-merge-notify.example.sh` → `.git/hooks/post-merge` in each monitored repo (executable). It runs `systemctl kill --signal=SIGUSR1 sentinel-agent` when `git log -1 --pretty=%s` starts with `[NOTIFY]`.

**Manual test:** after a pull that updates `HEAD` with a `[NOTIFY]` message, run the `systemctl kill` line above; check `journalctl -u sentinel-agent` for `Immediate scan requested (SIGUSR1)`.

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

`/health` does not touch the database; **`POST /heartbeat` writes SQLite**. A 500 almost always means the API process cannot write the DB file or the file's schema is older than the code.

1. **Inspect the real error** (on the central server):

   ```bash
   sudo journalctl -u sentinel-api -n 80 --no-pager
   ```

   Look for `OperationalError`, `readonly database`, or `no such column`.

2. **Fix permissions** — the user running Uvicorn (often `www-data`) must own or be able to write the DB and WAL files next to it:

   ```bash
   sudo chown -R www-data:www-data /var/www/cxl-sentinel/sentinel.db /var/www/cxl-sentinel/sentinel.db-wal /var/www/cxl-sentinel/sentinel.db-shm 2>/dev/null
   sudo systemctl restart sentinel-api
   ```

3. **Schema drift** — after upgrading code, run `python api/manage.py init-db` to drop and recreate tables (clean slate). This is a **destructive** operation—back up the DB first if you need historical data.

#### `manage.py`: `attempt to write a readonly database`

`init-db`, `create-token`, `revoke-token`, and other `manage.py` commands open the **same** SQLite file as the API. If the database was created or is normally written by **`www-data`** (the systemd service user), running `manage.py` as root or as your SSH user opens the file **read-only** for you, and commits fail with `sqlite3.OperationalError: attempt to write a readonly database`.

**Run CLI commands as the database owner** (usually `www-data`):

```bash
cd /var/www/cxl-sentinel
sudo -u www-data env SENTINEL_CONFIG=/var/www/cxl-sentinel/api/config.yaml \
  .venv/bin/python api/manage.py create-token --name "my-admin" --role admin
```

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
│   ├── install.sh              # server install script (also runs fix-safe-dirs)
│   ├── fix-safe-dirs.sh        # register repo paths in git safe.directory
│   ├── uninstall.sh            # server removal script
│   ├── sentinel-agent.service  # systemd unit file
│   ├── agent.yaml.example      # example configuration
│   └── hooks/
│       └── post-merge-notify.example.sh  # optional: SIGUSR1 after [NOTIFY] pull
├── api/
│   ├── main.py                 # FastAPI application + digest scheduler launch
│   ├── config.py               # API config loader (rules, branding, providers)
│   ├── auth.py                 # bearer token middleware
│   ├── models.py               # SQLAlchemy ORM models (deploy_events, digest_state, etc.)
│   ├── schemas.py              # Pydantic request/response schemas
│   ├── database.py             # DB engine + session factory
│   ├── digest_scheduler.py     # background task: midnight-anchored digest windows
│   ├── routers/
│   │   ├── events.py           # deploy event endpoints + [NOTIFY] immediate send
│   │   ├── heartbeat.py        # heartbeat endpoint
│   │   ├── servers.py          # server listing endpoint
│   │   └── health.py           # health check
│   ├── notifications/
│   │   ├── dispatcher.py       # rule matching + provider routing (immediate + digest)
│   │   ├── renderer.py         # HTML template engine (single-event + digest)
│   │   ├── smtp_provider.py    # SMTP/Gmail sender
│   │   ├── sendgrid_provider.py # SendGrid API sender
│   │   └── templates/
│   │       ├── deploy_notification.html   # single-event email
│   │       └── digest_notification.html   # batched digest email
│   ├── manage.py               # CLI: init-db, create-token, test-email
│   ├── simulate_central_flow.py # end-to-end flow simulation for testing
│   ├── requirements.txt        # API runtime deps
│   ├── example.config.yaml     # quick-start example config
│   └── config.yaml.example     # fully documented example config
└── tests/
    ├── test_detector.py
    ├── test_collector.py
    ├── test_reporter.py
    ├── test_api_events.py
    ├── test_api_auth.py
    ├── test_renderer_notify.py
    └── test_digest_scheduler.py
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
