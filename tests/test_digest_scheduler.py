"""Tests for digest scheduling window calculations and rule key generation."""

from datetime import datetime, timezone, timedelta

from api.config import ServerNotificationRule
from api.digest_scheduler import _rule_key, _current_window_start, _is_window_due


class TestRuleKey:
    def test_deterministic(self):
        rule = ServerNotificationRule(
            server_id="cs", environments=["production"],
            recipients=["a@x.com", "b@x.com"],
        )
        k1 = _rule_key(rule, "production")
        k2 = _rule_key(rule, "production")
        assert k1 == k2

    def test_different_env_different_key(self):
        rule = ServerNotificationRule(
            server_id="cs", environments=["production", "staging"],
            recipients=["a@x.com"],
        )
        k1 = _rule_key(rule, "production")
        k2 = _rule_key(rule, "staging")
        assert k1 != k2

    def test_recipient_order_irrelevant(self):
        r1 = ServerNotificationRule(server_id="s", recipients=["b@x.com", "a@x.com"])
        r2 = ServerNotificationRule(server_id="s", recipients=["a@x.com", "b@x.com"])
        assert _rule_key(r1, "production") == _rule_key(r2, "production")


class TestCurrentWindowStart:
    def test_6h_at_midnight(self):
        now = datetime(2026, 4, 13, 0, 0, 0, tzinfo=timezone.utc)
        ws = _current_window_start(now, 6 * 3600)
        assert ws == datetime(2026, 4, 13, 0, 0, 0, tzinfo=timezone.utc)

    def test_6h_at_0715(self):
        now = datetime(2026, 4, 13, 7, 15, 0, tzinfo=timezone.utc)
        ws = _current_window_start(now, 6 * 3600)
        assert ws == datetime(2026, 4, 13, 6, 0, 0, tzinfo=timezone.utc)

    def test_6h_at_1800(self):
        now = datetime(2026, 4, 13, 18, 0, 0, tzinfo=timezone.utc)
        ws = _current_window_start(now, 6 * 3600)
        assert ws == datetime(2026, 4, 13, 18, 0, 0, tzinfo=timezone.utc)

    def test_1d_window(self):
        now = datetime(2026, 4, 13, 15, 30, 0, tzinfo=timezone.utc)
        ws = _current_window_start(now, 86400)
        assert ws == datetime(2026, 4, 13, 0, 0, 0, tzinfo=timezone.utc)

    def test_10m_window(self):
        now = datetime(2026, 4, 13, 2, 25, 0, tzinfo=timezone.utc)
        ws = _current_window_start(now, 600)
        assert ws == datetime(2026, 4, 13, 2, 20, 0, tzinfo=timezone.utc)


class TestIsWindowDue:
    def test_none_last_sent_is_due(self):
        now = datetime(2026, 4, 13, 6, 5, 0, tzinfo=timezone.utc)
        assert _is_window_due(now, 6 * 3600, None) is True

    def test_sent_in_current_window_not_due(self):
        now = datetime(2026, 4, 13, 7, 30, 0, tzinfo=timezone.utc)
        last = datetime(2026, 4, 13, 6, 1, 0, tzinfo=timezone.utc)
        assert _is_window_due(now, 6 * 3600, last) is False

    def test_sent_in_previous_window_is_due(self):
        now = datetime(2026, 4, 13, 12, 5, 0, tzinfo=timezone.utc)
        last = datetime(2026, 4, 13, 6, 1, 0, tzinfo=timezone.utc)
        assert _is_window_due(now, 6 * 3600, last) is True

    def test_boundary_exact_window_start(self):
        now = datetime(2026, 4, 13, 6, 0, 0, tzinfo=timezone.utc)
        last = datetime(2026, 4, 13, 0, 30, 0, tzinfo=timezone.utc)
        assert _is_window_due(now, 6 * 3600, last) is True

    def test_daily_window_same_day_not_due(self):
        now = datetime(2026, 4, 13, 23, 59, 0, tzinfo=timezone.utc)
        last = datetime(2026, 4, 13, 0, 5, 0, tzinfo=timezone.utc)
        assert _is_window_due(now, 86400, last) is False

    def test_daily_window_next_day_is_due(self):
        now = datetime(2026, 4, 14, 0, 5, 0, tzinfo=timezone.utc)
        last = datetime(2026, 4, 13, 0, 5, 0, tzinfo=timezone.utc)
        assert _is_window_due(now, 86400, last) is True
