# CXL Sentinel

Lightweight deployment tracking for manually deployed web applications.

Monitors git repos on your servers, detects when `HEAD` changes, and records events to a central API. Digest emails summarize deploys on a schedule; `[NOTIFY]` commits bypass the schedule and send immediately.

## Table of contents

- [Quick Start](#quick-start)
- [Agent Configuration](#agent-configuration)
- [Central API Configuration](#central-api-configuration)
- [API Endpoints](#api-endpoints)
- [Email Notifications](#email-notifications)
- [Running Modes](#running-modes)
- [Production Deployment](#production-deployment)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Project Structure](#project-structure)

## Quick Start

**Requirements:** Python 3.10+, Git 2.25+, systemd (agent only). Both sides run on any modern Linux.

### 1. Central API

```bash
git clone https://github.com/nrek/cxl-sentinel.git && cd cxl-sentinel
python3 -m venv .venv && source .venv/bin/activate
pip install -r api/requirements.txt

cp api/config.yaml.example api/config.yaml
nano api/config.yaml                        # set DB path, SMTP/SendGrid, rules

python api/manage.py init-db
python api/manage.py create-token --name "admin" --role admin
python api/manage.py create-token --name "prod-web-01" --role agent

uvicorn api.main:app --host 0.0.0.0 --port 8400
```

### 2. Agent (each server)

```bash
git clone https://github.com/nrek/cxl-sentinel.git /tmp/cxl-sentinel
cd /tmp/cxl-sentinel && sudo bash agent/install.sh

sudo nano /etc/sentinel/agent.yaml          # set API URL, token, repo paths
sudo systemctl enable --now sentinel-agent
```

### 3. Verify connectivity

```bash
cd /opt/sentinel
sudo -u sentinel ./venv/bin/python -m agent.verify_connection --config /etc/sentinel/agent.yaml
```

---

## Agent Configuration

File: `/etc/sentinel/agent.yaml`

```yaml
sentinel:
  api_url: "https://sentinel.example.com/api/v1"
  api_token: "sk-agent-xxxxxxxxxxxx"
  server_id: "acme-web"
  environment: "production"       # production | staging
  scan_interval: "5m"             # 5m, 10m, 1h (minimum 1m)
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
  max_bytes: 10485760
  backup_count: 5
```

A single `api_token` can be reused across multiple servers sharing the same `server_id`. Central groups events by `server_id + environment`.

See `agent/agent.yaml.example` for the full reference.

---

## Central API Configuration

File: `api/config.yaml` (or path set via `SENTINEL_CONFIG` env var). See `api/config.yaml.example` for the fully documented reference.

### Notification Rules & Digest Scheduling

```yaml
notifications:
  rules:
    - server_id: "acme-web"
      server_alias: "Acme Web"
      environments: ["production", "staging"]
      send_schedule: "6h"           # 10m, 6h, 1d, 7d
      recipients:
        - "ops@example.com"
```

- `server_id` matches the agent's `sentinel.server_id` (`"*"` = wildcard).
- `send_schedule` sets the digest cadence, anchored at **midnight UTC** (e.g. `6h` fires at 00:00, 06:00, 12:00, 18:00).
- Events are batched into a single digest email per window. No events = no email.
- **`[NOTIFY]` bypass:** commits starting with `[NOTIFY]` send immediately *and* appear in the next digest.

---

## API Endpoints

All endpoints except `/health` require `Authorization: Bearer <token>`.

| Method | Path | Role | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/events` | agent | Record a deploy event |
| `POST` | `/api/v1/heartbeat` | agent | Agent liveness heartbeat |
| `GET`  | `/api/v1/events` | admin, readonly | Query deploy events |
| `GET`  | `/api/v1/servers` | admin, readonly | List servers + heartbeat status |
| `GET`  | `/api/v1/health` | *none* | Health check |

---

## Email Notifications

Configure one provider in `api/config.yaml` — SMTP or SendGrid. If both are enabled, SendGrid takes priority. See the example config for all fields.

### Branding

```yaml
notifications:
  branding:
    logo_url: "https://example.com/logo.png"
    accent_color: "#2563eb"
    header_theme: "dark"            # "dark" = light text; "light" = dark text
    header_background: ""           # empty = same as accent_color
    company_name: ""
    footer_text: ""
```

### Test email

```bash
python api/manage.py test-email --dry-run                    # print HTML only
python api/manage.py test-email --to you@example.com         # send one test
```

Templates live in `api/notifications/templates/` — `deploy_notification.html` (single event) and `digest_notification.html` (batched digest).

---

## Running Modes

### Service (recommended)

```bash
sudo systemctl enable --now sentinel-agent
sudo journalctl -u sentinel-agent -f
```

### Oneshot (cron)

```bash
*/5 * * * * /opt/sentinel/venv/bin/python /opt/sentinel/agent/agent.py \
  --mode oneshot --config /etc/sentinel/agent.yaml >> /var/log/sentinel/cron.log 2>&1
```

### `[NOTIFY]` — immediate scan + email

If a commit message starts with `[NOTIFY]`, Central sends the email immediately (bypassing digest). To also skip the agent's `scan_interval` wait:

```bash
sudo systemctl kill --signal=SIGUSR1 sentinel-agent
```

Automate this with a git `post-merge` hook — see `agent/hooks/post-merge-notify.example.sh`.

---

## Production Deployment

### Central API as a systemd service

```ini
[Unit]
Description=CXL Sentinel API
After=network-online.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/cxl-sentinel
ExecStart=/var/www/cxl-sentinel/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8400
Restart=on-failure
Environment=SENTINEL_CONFIG=/var/www/cxl-sentinel/api/config.yaml

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now sentinel-api
```

Place behind a reverse proxy (Nginx, Caddy) with TLS for production.

### After updating code

```bash
# Central
cd /var/www/cxl-sentinel && git pull && sudo systemctl restart sentinel-api

# Agent
cd /tmp/cxl-sentinel && git pull && sudo bash agent/install.sh
sudo systemctl restart sentinel-agent
```

### Uninstalling the agent

```bash
sudo bash /opt/sentinel/agent/uninstall.sh
```

---

## Troubleshooting

### Git "dubious ownership"

The agent runs as the `sentinel` user but monitors repos owned by `www-data`. Git 2.35+ blocks this unless the path is registered as safe.

**`install.sh` handles this automatically** — it reads `agent.yaml` and runs `git config --system --add safe.directory` for each repo path. To re-run after adding new repos:

```bash
sudo bash /opt/sentinel/agent/fix-safe-dirs.sh
```

Do **not** use `git config --global` — the `sentinel` user has no home directory, and `ProtectHome=yes` in the systemd unit makes `/home` invisible. Only `--system` (`/etc/gitconfig`) works.

### `manage.py`: readonly database

The SQLite file is owned by the service user (usually `www-data`). Run CLI commands as that user:

```bash
sudo -u www-data env SENTINEL_CONFIG=/var/www/cxl-sentinel/api/config.yaml \
  .venv/bin/python api/manage.py create-token --name "my-token" --role agent
```

### Heartbeat returns 500

Check `sudo journalctl -u sentinel-api -n 50`. Usually a permissions issue — ensure `www-data` owns the `.db`, `.db-wal`, and `.db-shm` files.

---

## Development

```bash
git clone https://github.com/nrek/cxl-sentinel.git && cd cxl-sentinel
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r agent/requirements.txt -r api/requirements.txt

pytest tests/ -v

python api/manage.py init-db
cp api/config.yaml.example api/config.yaml
uvicorn api.main:app --reload --port 8400
```

---

## Project Structure

```
cxl-sentinel/
├── agent/
│   ├── agent.py                # entry point (service | oneshot)
│   ├── config.py               # YAML config loader
│   ├── detector.py             # git HEAD change detection
│   ├── collector.py            # commit metadata extraction
│   ├── reporter.py             # HTTP client → central API
│   ├── queue.py                # offline event queue
│   ├── state.py                # state persistence
│   ├── verify_connection.py    # connectivity check tool
│   ├── install.sh              # server install (runs fix-safe-dirs)
│   ├── fix-safe-dirs.sh        # register repo paths in git safe.directory
│   ├── uninstall.sh
│   ├── sentinel-agent.service
│   ├── agent.yaml.example
│   └── hooks/
│       └── post-merge-notify.example.sh
├── api/
│   ├── main.py                 # FastAPI app + digest scheduler
│   ├── config.py               # config loader (rules, branding, providers)
│   ├── auth.py                 # bearer token middleware
│   ├── models.py               # SQLAlchemy models
│   ├── schemas.py              # Pydantic schemas
│   ├── database.py             # DB engine + sessions
│   ├── digest_scheduler.py     # background digest task
│   ├── manage.py               # CLI: init-db, create-token, test-email
│   ├── simulate_central_flow.py
│   ├── routers/                # events, heartbeat, servers, health
│   ├── notifications/
│   │   ├── dispatcher.py       # rule matching + send routing
│   │   ├── renderer.py         # HTML template engine
│   │   ├── smtp_provider.py
│   │   ├── sendgrid_provider.py
│   │   └── templates/          # deploy + digest HTML emails
│   ├── config.yaml.example
│   └── requirements.txt
└── tests/
```

---

## Security

See [SECURITY.md](SECURITY.md). Tokens are SHA-256 hashed at rest. Agent runs as an unprivileged system user. HTTPS required in production. All input validated via Pydantic.

## License

[MIT](LICENSE)
