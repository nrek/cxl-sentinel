"""HTML template rendering for deploy notification emails.

Uses a lightweight Jinja2-like approach with simple string replacement
to avoid adding Jinja2 as a dependency. Supports {{ var }} and
basic {% if var %}...{% endif %} blocks.
"""

import re
from pathlib import Path
from typing import Optional

from api.config import BrandingConfig

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_NOTIFY_PREFIX = "[NOTIFY]"


def _commit_requests_immediate_notify(commit_message: str) -> bool:
    """True if the first line of the latest commit message starts with [NOTIFY]."""
    first_line = (commit_message or "").split("\n", 1)[0].lstrip()
    return first_line.startswith(_NOTIFY_PREFIX)


def _header_style_vars(branding: BrandingConfig) -> dict[str, str]:
    """Colors for the top banner only. Body still uses accent_color."""
    accent = branding.accent_color or "#2563eb"
    bg = (branding.header_background or "").strip() or accent
    theme = (branding.header_theme or "dark").strip().lower()
    if theme not in ("dark", "light"):
        theme = "dark"

    if theme == "dark":
        return {
            "header_background": _esc(bg),
            "header_title_color": _esc("#ffffff"),
            "header_subtitle_color": _esc("rgba(255,255,255,0.8)"),
            "header_badge_background": _esc("rgba(255,255,255,0.2)"),
            "header_badge_color": _esc("#ffffff"),
        }

    return {
        "header_background": _esc(bg),
        "header_title_color": _esc("#0f172a"),
        "header_subtitle_color": _esc("#475569"),
        "header_badge_background": _esc("rgba(15,23,42,0.08)"),
        "header_badge_color": _esc("#334155"),
    }


def render_deploy_email(
    repo_alias: str,
    server_id: str,
    environment: str,
    commit_hash: str,
    commit_message: str,
    commit_author: str,
    files_changed: int,
    commit_count: int,
    contributors: list[str],
    branch: str,
    detected_at: str,
    previous_commit_hash: Optional[str],
    branding: BrandingConfig,
) -> tuple[str, str]:
    """Render the deploy notification email as an executive summary.

    Returns:
        (subject, html_body) tuple.
    """
    template_path = _TEMPLATE_DIR / "deploy_notification.html"
    html = template_path.read_text(encoding="utf-8")

    env_label = environment.capitalize()
    notify_tag = f"{_NOTIFY_PREFIX} " if _commit_requests_immediate_notify(commit_message) else ""
    subject = (
        f"{notify_tag}[{env_label}] {repo_alias} updated — {files_changed} files, "
        f"{commit_count} commit{'s' if commit_count != 1 else ''}"
    )

    contributor_count = len(contributors) if contributors else 1
    contributors_display = ", ".join(contributors) if contributors else commit_author

    variables = {
        "repo_alias": _esc(repo_alias),
        "server_id": _esc(server_id),
        "environment": _esc(environment),
        "commit_hash_short": _esc(commit_hash[:12]),
        "commit_message": _esc(commit_message or "(no message)"),
        "commit_author": _esc(commit_author or "unknown"),
        "files_changed": str(files_changed),
        "commit_count": str(commit_count),
        "commit_count_label": "Commit" if commit_count == 1 else "Commits",
        "contributor_count": str(contributor_count),
        "contributor_count_label": "Contributor" if contributor_count == 1 else "Contributors",
        "contributors_list": _esc(contributors_display),
        "branch": _esc(branch),
        "detected_at": _esc(detected_at),
        "accent_color": _esc(branding.accent_color or "#2563eb"),
        "logo_url": _esc(branding.logo_url or ""),
        "company_name": _esc(branding.company_name or ""),
        "footer_text": _esc(branding.footer_text or ""),
    }
    variables.update(_header_style_vars(branding))

    html = _process_conditionals(html, variables)
    html = _replace_variables(html, variables)

    return subject, html


def render_digest_email(
    server_alias: str,
    server_id: str,
    environment: str,
    events: list[dict],
    branding: BrandingConfig,
) -> tuple[str, str]:
    """Render a digest summary email for batched deploy events.

    Each event in `events` should be a dict with keys:
        repo_alias, commit_hash, commit_message, commit_author,
        files_changed, commit_count, contributors, branch, detected_at,
        notified_immediately (bool).

    Returns:
        (subject, html_body) tuple.
    """
    template_path = _TEMPLATE_DIR / "digest_notification.html"
    html = template_path.read_text(encoding="utf-8")

    env_label = environment.capitalize()
    total_events = len(events)
    subject = (
        f"[Digest] [{env_label}] {server_alias} — {total_events} "
        f"deploy{'s' if total_events != 1 else ''} since last digest"
    )

    event_rows_html = ""
    for ev in events:
        already = ev.get("notified_immediately", False)
        already_badge = (
            ' <span style="display:inline-block;padding:1px 6px;font-size:10px;'
            'background:#fef3c7;color:#92400e;border-radius:3px;margin-left:4px;">'
            'sent immediately</span>'
        ) if already else ""

        msg = _esc(ev.get("commit_message", "(no message)") or "(no message)")
        first_line = msg.split("\n", 1)[0][:120]
        author = _esc(ev.get("commit_author", "unknown") or "unknown")
        short_hash = _esc((ev.get("commit_hash", "") or "")[:12])
        repo = _esc(ev.get("repo_alias", ""))
        files = ev.get("files_changed", 0)
        det = _esc(ev.get("detected_at", ""))

        event_rows_html += (
            '<tr>'
            f'<td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;">'
            f'<p style="margin:0 0 4px;font-size:14px;font-weight:600;color:#1a1a2e;">'
            f'{first_line}{already_badge}</p>'
            f'<p style="margin:0;font-size:12px;color:#6b7280;">'
            f'{repo} &middot; {author} &middot; {short_hash} &middot; {files} files &middot; {det}</p>'
            f'</td>'
            '</tr>'
        )

    total_files = sum(ev.get("files_changed", 0) for ev in events)
    total_commits = sum(ev.get("commit_count", 1) for ev in events)
    all_contributors: set[str] = set()
    for ev in events:
        for c in (ev.get("contributors") or []):
            all_contributors.add(c)

    variables = {
        "server_alias": _esc(server_alias),
        "server_id": _esc(server_id),
        "environment": _esc(environment),
        "total_events": str(total_events),
        "total_files": str(total_files),
        "total_commits": str(total_commits),
        "total_contributors": str(len(all_contributors) or 1),
        "event_rows": event_rows_html,
        "accent_color": _esc(branding.accent_color or "#2563eb"),
        "logo_url": _esc(branding.logo_url or ""),
        "company_name": _esc(branding.company_name or ""),
        "footer_text": _esc(branding.footer_text or ""),
    }
    variables.update(_header_style_vars(branding))

    html = _process_conditionals(html, variables)
    html = _replace_variables(html, variables)

    return subject, html


def _esc(value: str) -> str:
    """Minimal HTML escaping for template variables."""
    return (
        value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _replace_variables(html: str, variables: dict[str, str]) -> str:
    """Replace {{ var_name }} placeholders."""
    def _replacer(match):
        key = match.group(1).strip()
        return variables.get(key, "")
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", _replacer, html)


def _process_conditionals(html: str, variables: dict[str, str]) -> str:
    """Process {% if var %}...{% endif %} blocks.

    Truthy = non-empty string after escaping. Nested ifs are not supported.
    """
    def _replacer(match):
        key = match.group(1).strip()
        body = match.group(2)
        if variables.get(key, ""):
            return body
        return ""

    return re.sub(
        r"\{%\s*if\s+(\w+)\s*%\}(.*?)\{%\s*endif\s*%\}",
        _replacer,
        html,
        flags=re.DOTALL,
    )
