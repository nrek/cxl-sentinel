"""Tests for [NOTIFY] email subject tagging."""

from api.config import BrandingConfig
from api.notifications.renderer import render_deploy_email


def test_subject_prefixed_when_notify_marker():
    branding = BrandingConfig()
    subject, _html = render_deploy_email(
        repo_alias="p",
        server_id="s",
        environment="production",
        commit_hash="a" * 40,
        commit_message="[NOTIFY] urgent deploy",
        commit_author="dev",
        files_changed=1,
        commit_count=1,
        contributors=["dev@example.com"],
        branch="main",
        detected_at="2026-01-01 00:00:00 UTC",
        previous_commit_hash=None,
        branding=branding,
    )
    assert subject.startswith("[NOTIFY] ")


def test_subject_not_prefixed_without_marker():
    branding = BrandingConfig()
    subject, _html = render_deploy_email(
        repo_alias="p",
        server_id="s",
        environment="production",
        commit_hash="a" * 40,
        commit_message="Regular deploy",
        commit_author="dev",
        files_changed=1,
        commit_count=1,
        contributors=["dev@example.com"],
        branch="main",
        detected_at="2026-01-01 00:00:00 UTC",
        previous_commit_hash=None,
        branding=branding,
    )
    assert not subject.startswith("[NOTIFY] ")


def test_multiline_commit_first_line_only():
    branding = BrandingConfig()
    subject, _html = render_deploy_email(
        repo_alias="p",
        server_id="s",
        environment="production",
        commit_hash="a" * 40,
        commit_message="[NOTIFY] x\nsecond line",
        commit_author="dev",
        files_changed=1,
        commit_count=1,
        contributors=["dev@example.com"],
        branch="main",
        detected_at="2026-01-01 00:00:00 UTC",
        previous_commit_hash=None,
        branding=branding,
    )
    assert subject.startswith("[NOTIFY] ")
