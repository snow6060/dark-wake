"""Regression tests for AIS endpoint failure (timeout / unreachable)."""
import pytest
from src import ais_client


def test_fetch_bbox_history_raises_on_timeout(monkeypatch):
    """If the AIS server is unreachable (timeout), the request must not
    return a fake empty success or mask the error."""
    monkeypatch.setattr(ais_client, "BASE", "https://data.aisvesseltracker.com")
    monkeypatch.setattr(ais_client.time, "sleep", lambda _s: None)

    def timeout_get(*_args, **_kwargs):
        raise ais_client.requests.exceptions.Timeout("AIS server unreachable")

    monkeypatch.setattr(ais_client.requests, "get", timeout_get)

    with pytest.raises(ais_client.requests.exceptions.Timeout, match="unreachable"):
        ais_client.fetch_bbox_history(
            (56.3, 26.45, 56.7, 26.8),
            "2026-10-26T07:02:15Z",
            key="test",
        )


def test_fetch_bbox_history_does_not_write_empty_analysis_on_500(monkeypatch):
    """Server errors must propagate; never return [] as success."""
    monkeypatch.setattr(ais_client, "BASE", "https://data.aisvesseltracker.com")
    monkeypatch.setattr(ais_client.time, "sleep", lambda _s: None)

    class FakeResponse:
        status_code = 500
        text = '{"error":"internal"}'
        headers = {}
        def raise_for_status(self):
            raise ais_client.requests.HTTPError("HTTP 500")

    monkeypatch.setattr(ais_client.requests, "get", lambda *_a, **_k: FakeResponse())

    with pytest.raises(ais_client.requests.HTTPError, match="HTTP 500"):
        ais_client.fetch_bbox_history(
            (56.3, 26.45, 56.7, 26.8),
            "2026-10-26T07:02:15Z",
            key="test",
        )
