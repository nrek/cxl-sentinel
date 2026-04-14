#!/usr/bin/env python3
"""Send a welcome email to all configured notification recipients.

Usage (on Central):
    SENTINEL_CONFIG=api/config.yaml python api/send_welcome.py

Collects every unique recipient across all notification rules and sends
a single welcome email introducing them to Sentinel notifications.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.config import load_api_config
from api.notifications import smtp_provider, sendgrid_provider


def _build_welcome_html(branding) -> tuple[str, str]:
    accent = branding.accent_color or "#2563eb"
    header_bg = branding.header_background or accent
    logo_url = branding.logo_url or ""
    company = branding.company_name or ""
    footer = branding.footer_text or ""

    ht = branding.header_theme
    if ht == "light":
        title_color = "#1a1a2e"
        subtitle_color = "#555"
    else:
        title_color = "#ffffff"
        subtitle_color = "rgba(255,255,255,0.75)"

    logo_block = ""
    if logo_url:
        alt = company or "Logo"
        logo_block = f'<img src="{logo_url}" alt="{alt}" style="max-height:28px; margin-bottom:12px; display:block;" />'

    footer_extra = ""
    if footer:
        footer_extra = f"{footer}<br/>"

    subject = "Welcome to Sentinel"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{subject}</title>
</head>
<body style="margin:0; padding:0; background-color:#f4f5f7; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f5f7; padding:32px 16px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.08);">

  <!-- Header -->
  <tr>
    <td style="background-color:{header_bg}; padding:28px 32px;">
      {logo_block}
      <p style="margin:0 0 4px; font-size:22px; font-weight:600; color:{title_color}; line-height:1.3;">
        Welcome to Sentinel
      </p>
      <p style="margin:0; font-size:14px; color:{subtitle_color};">
        Automated deployment notifications
      </p>
    </td>
  </tr>

  <!-- Body -->
  <tr>
    <td style="padding:28px 32px;">
      <p style="margin:0 0 16px; font-size:15px; color:#374151; line-height:1.6;">
        Hi there &mdash; you&rsquo;re now set up to receive deployment updates from Sentinel.
      </p>

      <p style="margin:0 0 20px; font-size:15px; color:#374151; line-height:1.6;">
        Whenever the projects you&rsquo;re connected to are updated, you&rsquo;ll get an email summary. Here&rsquo;s what to expect:
      </p>

      <!-- What to expect -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
        <tr>
          <td style="padding:16px; background-color:#f9fafb; border-left:3px solid {accent}; border-radius:0 6px 6px 0;">
            <p style="margin:0 0 10px; font-size:14px; color:#374151; line-height:1.6;">
              <strong style="color:#1a1a2e;">Scheduled summaries</strong> &mdash; emails arrive on a set schedule (not on every single change), so your inbox stays manageable.
            </p>
            <p style="margin:0 0 10px; font-size:14px; color:#374151; line-height:1.6;">
              <strong style="color:#1a1a2e;">Quick glance stats</strong> &mdash; each email shows the number of files changed, updates made, and who made them.
            </p>
            <p style="margin:0; font-size:14px; color:#374151; line-height:1.6;">
              <strong style="color:#1a1a2e;">No action needed</strong> &mdash; these are informational. You don&rsquo;t need to reply or do anything unless something looks unexpected.
            </p>
          </td>
        </tr>
      </table>

      <p style="margin:0 0 8px; font-size:14px; color:#6b7280; line-height:1.5;">
        This is an automated system &mdash; replies to these emails are not monitored. If you have questions, reach out to your project team directly.
      </p>
    </td>
  </tr>

  <!-- Footer -->
  <tr>
    <td style="padding:18px 32px; border-top:1px solid #e5e7eb; background-color:#fafafa;">
      <p style="margin:0; font-size:12px; color:#9ca3af; line-height:1.5;">
        {footer_extra}
        Sent by <strong><a href="https://craftxlogic.com" style="color:#666; text-decoration: none;">Craft &amp; Logic</a></strong> &ndash; Sentinel &bull; Deployment Tracking
      </p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    return subject, html


def _send(n, recipients, subject, html):
    use_bcc = n.use_bcc
    to_address = n.to_address or ""

    if n.sendgrid.enabled:
        return sendgrid_provider.send_email(
            n.sendgrid, recipients, subject, html,
            use_bcc=use_bcc, to_address=to_address,
        )
    return smtp_provider.send_email(
        n.smtp, recipients, subject, html,
        use_bcc=use_bcc, to_address=to_address,
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Send Sentinel welcome email to all recipients")
    parser.add_argument(
        "--preview", metavar="EMAIL",
        help="Send a preview to this address only (does not email other recipients)",
    )
    args = parser.parse_args()

    config_path = os.environ.get("SENTINEL_CONFIG", "api/config.yaml")
    try:
        config = load_api_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    n = config.notifications

    if not n.smtp.enabled and not n.sendgrid.enabled:
        print("No email provider enabled in config. Enable smtp or sendgrid first.", file=sys.stderr)
        sys.exit(1)

    subject, html = _build_welcome_html(n.branding)

    if args.preview:
        print(f"Sending preview to: {args.preview}")
        ok = _send(n, [args.preview.strip()], subject, html)
        if ok:
            print("Preview sent.")
        else:
            print("Preview send failed. Check SMTP/SendGrid settings.", file=sys.stderr)
            sys.exit(1)
        return

    all_recipients = set()
    for rule in n.rules:
        all_recipients.update(rule.recipients)

    if not all_recipients:
        print("No recipients found in notification rules.", file=sys.stderr)
        sys.exit(1)

    recipients = sorted(all_recipients)
    print(f"Sending welcome email to {len(recipients)} recipient(s):")
    for r in recipients:
        print(f"  {r}")

    ok = _send(n, recipients, subject, html)
    if ok:
        print("Welcome email sent successfully.")
    else:
        print("Send failed. Check SMTP/SendGrid settings.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
