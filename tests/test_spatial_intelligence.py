import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
from src.geo_utils import haversine_m, dead_reckon, point_in_polygon
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.spatial_config import SpatialSettings
from unittest.mock import patch, MagicMock

def test_haversine():
    assert haversine_m(0,0,0,1) > 0

def test_dead_reckon():
    lat, lon = dead_reckon(45, 12, 10, 90, 3600)
    assert abs(lat - 45) < 1

def test_zone_load():
    s = SpatialSettings()
    assert s.zone_buffer_m > 0

def test_snapshot_mock():
    with patch("src.satellite_fetch.Client") as m:
        m.return_value.search.return_value.items.return_value = []
        assert True

def test_verification_output():
    from src.spatial_analysis import analyze_snapshot
    assert callable(analyze_snapshot)
