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
    project: str,
    client: str,
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
    subject = f"[{env_label}] {project} updated — {files_changed} files, {commit_count} commit{'s' if commit_count != 1 else ''}"

    contributor_count = len(contributors) if contributors else 1
    contributors_display = ", ".join(contributors) if contributors else commit_author

    variables = {
        "project": _esc(project),
        "client": _esc(client),
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
