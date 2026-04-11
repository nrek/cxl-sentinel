# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | Yes                |

## Reporting a Vulnerability

If you discover a security vulnerability in CXL Sentinel, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, email **security@craftxlogic.com** with:

- A description of the vulnerability
- Steps to reproduce
- The affected component (agent, API, install scripts)
- Any potential impact assessment

We will acknowledge receipt within 48 hours and aim to provide a fix or mitigation plan within 7 business days.

## Security Architecture

### Authentication

- All agent-to-API communication is authenticated via bearer tokens.
- Tokens are stored as SHA-256 hashes in the database; plaintext tokens exist only in the agent config file.
- API tokens are role-scoped: `agent`, `admin`, and `readonly`.

### Transport

- HTTPS is required for all production deployments.
- TLS termination is expected at a reverse proxy (Nginx, ALB, etc.) in front of the API.

### Agent Isolation

- The agent runs as a dedicated `sentinel` system user with no login shell.
- Config files containing tokens are restricted to mode `0600`, owned by the service user.
- State and queue files are stored in `/var/lib/sentinel/` with mode `0700`.

### Secrets Management

- API tokens should be generated using the provided `manage.py create-token` CLI, which uses `secrets.token_urlsafe()` for cryptographic randomness.
- Never commit `agent.yaml`, `config.yaml`, or `.db` files to version control. The `.gitignore` is preconfigured to exclude these.

### Input Validation

- All API inputs are validated via Pydantic schemas with strict type enforcement.
- Git-derived data (commit hashes, messages, authors) is treated as untrusted input and sanitized before storage.

### Rate Limiting

- The API enforces per-token rate limits to prevent abuse (default: 100 requests/minute).

## Hardening Recommendations

1. **Restrict network access**: Limit inbound traffic to the API port (default 8400) to known agent IPs using security groups or firewall rules.
2. **Rotate tokens periodically**: Use `manage.py create-token` to generate new tokens and deactivate old ones.
3. **Monitor heartbeats**: An agent that stops sending heartbeats may indicate a compromised or failed server.
4. **Keep Python updated**: Run the agent and API on a supported Python version (3.10+) with regular security patches.
5. **Use a reverse proxy**: Do not expose the FastAPI/Uvicorn process directly to the internet. Place Nginx or an ALB in front with TLS.
