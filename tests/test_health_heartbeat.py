from explainlaw.observability.health import send_alerts, send_telegram_heartbeat


def test_send_alerts_healthy_without_heartbeat_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "explainlaw.observability.health.send_telegram_heartbeat",
        lambda health: calls.append("hb") or True,
    )
    assert send_alerts({"healthy": True, "alerts": []}) is False
    assert calls == []


def test_send_alerts_healthy_with_heartbeat(monkeypatch):
    monkeypatch.setattr(
        "explainlaw.observability.health.send_telegram_heartbeat",
        lambda health: True,
    )
    assert send_alerts({"healthy": True, "alerts": []}, allow_heartbeat=True) is True


def test_heartbeat_message_shape(monkeypatch):
    sent: list[str] = []

    monkeypatch.setattr("explainlaw.config.settings.alert_telegram_heartbeat", True)
    monkeypatch.setattr(
        "explainlaw.observability.health._telegram_alert_budget_remaining",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "explainlaw.observability.health._record_telegram_alert_sent",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "explainlaw.messaging.telegram.send_telegram_text",
        lambda text, **kwargs: sent.append(text) or True,
    )
    ok = send_telegram_heartbeat(
        {
            "healthy": True,
            "last_collect": {"at": "2026-08-05T08:00:00+03:00"},
            "last_daily": {"at": "2026-08-05T08:05:00+03:00"},
        }
    )
    assert ok is True
    assert "ExplainLaw" in sent[0]
    assert "OK" in sent[0]
    assert "2026-08-05T08:00:00+03:00" in sent[0]
