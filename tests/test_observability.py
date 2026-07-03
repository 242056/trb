from explainlaw.observability.recorder import _resolve_status


def test_resolve_status_success():
    assert _resolve_status({"new": 5, "errors": 0}).value == "success"


def test_resolve_status_partial():
    assert _resolve_status({"new": 1, "errors": 2}).value == "partial"


def test_resolve_status_failed():
    assert _resolve_status({"errors": 3}).value == "failed"
