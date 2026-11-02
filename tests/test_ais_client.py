import pytest

from src import ais_client


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self.payload = payload or {"type": "FeatureCollection", "features": []}
        self.headers = headers or {}
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


def test_parse_features_reads_documented_vessel_metadata():
    ships = ais_client.parse_features({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [56.4, 26.5]},
            "properties": {
                "id": 123456789,
                "shipName": "Example Vessel",
                "flag": "PA",
                "country": "Panama",
                "type": 80,
                "shipType": "Tanker",
                "sog": 0,
                "cog": 0,
                "imoNumber": 9876543,
                "time_utc": "2026-10-26T12:00:00Z",
            },
        }],
    })

    assert ships == [{
        "mmsi": 123456789,
        "name": "Example Vessel",
        "lat": 26.5,
        "lon": 56.4,
        "sog": 0,
        "cog": 0,
        "heading": None,
        "nav": None,
        "type_code": 80,
        "ship_type": "Tanker",
        "country": "Panama",
        "flag": "PA",
        "imo": 9876543,
        "time_utc": "2026-10-26T12:00:00Z",
    }]


def test_history_fetch_rejects_sandbox_without_making_request(monkeypatch):
    monkeypatch.setattr(ais_client, "BASE", "https://sandbox.aisvesseltracker.com")
    monkeypatch.setattr(
        ais_client.requests,
        "get",
        lambda *_args, **_kwargs: pytest.fail("sandbox request must not be sent"),
    )

    with pytest.raises(RuntimeError, match="points to the sandbox"):
        ais_client.fetch_bbox_history((56.0, 26.0, 57.0, 27.0), "2026-10-26T12:00:00Z", key="test")


def test_parse_features_rejects_missing_coordinates():
    with pytest.raises(ValueError, match="missing vessel coordinates"):
        ais_client.parse_features({"features": [{"properties": {"id": 123456789}}]})


def test_history_fetch_retries_server_error_and_returns_success(monkeypatch):
    monkeypatch.setattr(ais_client, "BASE", "https://data.aisvesseltracker.com")
    responses = iter([
        FakeResponse(500),
        FakeResponse(200, headers={"X-Credits-Remaining": "42"}),
    ])
    requests_seen = []

    def fake_get(url, **kwargs):
        requests_seen.append((url, kwargs))
        return next(responses)

    monkeypatch.setattr(ais_client.requests, "get", fake_get)
    monkeypatch.setattr(ais_client.time, "sleep", lambda _seconds: None)

    ships, credits, window_s = ais_client.fetch_bbox_history(
        (56.3, 26.45, 56.7, 26.8),
        "2026-10-26T07:02:15Z",
        key="test",
    )

    assert ships == []
    assert credits == "42"
    assert window_s == 86400
    assert len(requests_seen) == 2
    assert requests_seen[0] == requests_seen[1]
    assert requests_seen[0][1]["params"] == {
        "swLat": 26.45,
        "swLng": 56.3,
        "neLat": 26.8,
        "neLng": 56.7,
        "at": "2026-10-26T07:02:15Z",
        "window": 86400,
    }


def test_history_fetch_does_not_retry_client_error(monkeypatch):
    monkeypatch.setattr(ais_client, "BASE", "https://data.aisvesseltracker.com")
    calls = []

    def fake_get(*_args, **_kwargs):
        calls.append(True)
        return FakeResponse(400)

    monkeypatch.setattr(ais_client.requests, "get", fake_get)
    monkeypatch.setattr(
        ais_client.time,
        "sleep",
        lambda _seconds: pytest.fail("client errors must not be retried"),
    )

    with pytest.raises(ais_client.requests.HTTPError, match="HTTP 400"):
        ais_client.fetch_bbox_history(
            (56.3, 26.45, 56.7, 26.8),
            "2026-10-26T07:02:15Z",
            key="test",
        )

    assert len(calls) == 1


def test_history_fetch_falls_back_to_narrower_window_after_server_error(monkeypatch):
    monkeypatch.setattr(ais_client, "BASE", "https://data.aisvesseltracker.com")
    calls = []
    requested_windows = []

    def fake_get(_url, **kwargs):
        calls.append(True)
        requested_windows.append(kwargs["params"]["window"])
        if len(calls) == ais_client.HISTORY_REQUEST_ATTEMPTS + 1:
            return FakeResponse(200, headers={"X-Credits-Remaining": "42"})
        return FakeResponse(500)

    monkeypatch.setattr(ais_client.requests, "get", fake_get)
    monkeypatch.setattr(ais_client.time, "sleep", lambda _seconds: None)

    ships, credits, window_s = ais_client.fetch_bbox_history(
        (56.3, 26.45, 56.7, 26.8),
        "2026-10-26T07:02:15Z",
        key="test",
    )

    assert ships == []
    assert credits == "42"
    assert window_s == ais_client.HISTORY_WINDOW_FALLBACKS[1]
    assert len(calls) == ais_client.HISTORY_REQUEST_ATTEMPTS + 1
    assert requested_windows == [86400] * ais_client.HISTORY_REQUEST_ATTEMPTS + [21600]


def test_history_fetch_immediately_falls_back_for_provider_window_query_error(monkeypatch):
    monkeypatch.setattr(ais_client, "BASE", "https://data.aisvesseltracker.com")
    requested_windows = []

    def fake_get(_url, **kwargs):
        window = kwargs["params"]["window"]
        requested_windows.append(window)
        if window == 86400:
            return FakeResponse(500, {
                "error": {
                    "code": "server_error",
                    "message": (
                        "failed to query vessels in bounding box at the requested time"
                    ),
                },
            })
        return FakeResponse(200, headers={"X-Credits-Remaining": "42"})

    monkeypatch.setattr(ais_client.requests, "get", fake_get)
    monkeypatch.setattr(
        ais_client.time,
        "sleep",
        lambda _seconds: pytest.fail("known query-window errors should not be retried"),
    )

    ships, credits, window_s = ais_client.fetch_bbox_history(
        (56.3, 25.0, 56.7, 25.35),
        "2026-10-26T07:02:30Z",
        key="test",
    )

    assert ships == []
    assert credits == "42"
    assert window_s == 21600
    assert requested_windows == [86400, 21600]


def test_history_fetch_raises_after_all_fallback_windows_fail(monkeypatch):
    monkeypatch.setattr(ais_client, "BASE", "https://data.aisvesseltracker.com")
    calls = []

    def fake_get(*_args, **_kwargs):
        calls.append(True)
        return FakeResponse(500)

    monkeypatch.setattr(ais_client.requests, "get", fake_get)
    monkeypatch.setattr(ais_client.time, "sleep", lambda _seconds: None)

    with pytest.raises(ais_client.requests.HTTPError, match="HTTP 500"):
        ais_client.fetch_bbox_history(
            (56.3, 26.45, 56.7, 26.8),
            "2026-10-26T07:02:15Z",
            key="test",
        )

    assert len(calls) == (
        ais_client.HISTORY_REQUEST_ATTEMPTS * len(ais_client.HISTORY_WINDOW_FALLBACKS)
    )
