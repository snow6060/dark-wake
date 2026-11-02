import pytest

from src import ais_client


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
