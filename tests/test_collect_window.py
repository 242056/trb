"""Окно daily collect: вчера+сегодня при lookback=1."""

from datetime import date
from unittest.mock import patch

from explainlaw.collector.service import collect_window


def test_collect_window_default_lookback_yesterday_and_today():
    anchor = date(2026, 8, 5)
    with patch("explainlaw.collector.service.settings") as s:
        s.collect_lookback_days = 1
        assert collect_window(anchor=anchor) == (date(2026, 8, 4), date(2026, 8, 5))


def test_collect_window_explicit_lookback():
    anchor = date(2026, 8, 5)
    assert collect_window(anchor=anchor, lookback_days=0) == (anchor, anchor)
    assert collect_window(anchor=anchor, lookback_days=2) == (
        date(2026, 8, 3),
        date(2026, 8, 5),
    )


def test_collect_window_negative_lookback_clamped():
    anchor = date(2026, 8, 5)
    assert collect_window(anchor=anchor, lookback_days=-3) == (anchor, anchor)
