from datetime import date
from types import SimpleNamespace

from explainlaw.delta.builder import _cap_delta_quote, _is_amendment_event
from explainlaw.db.models import NormEventType


def test_is_amendment_event_skips_baseline():
    baseline = SimpleNamespace(event_type=NormEventType.baseline)
    amendment = SimpleNamespace(event_type=NormEventType.amendment)
    assert not _is_amendment_event(baseline)
    assert _is_amendment_event(amendment)


def test_cap_delta_quote_truncates_huge_text():
    huge = "Статья 1. " + ("Много одинаковых слов подряд. " * 500)
    capped = _cap_delta_quote(huge)
    assert capped is not None
    assert len(capped) <= 2000
    assert len(capped) < len(huge)
