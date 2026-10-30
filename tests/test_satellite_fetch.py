"""Tests for the real Sentinel-2 fetch logic, using small synthetic GeoTIFFs (no network)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from src import geo_utils, satellite_fetch as sf
from src.spatial_config import SpatialSettings, Zone

CRS_UTM = CRS.from_epsg(32640)
X0, Y0 = 300000.0, 2900000.0


def _write_scene(tmp_path, name, cloud_rows=0):
    vis = np.full((3, 1000, 1000), 40, dtype=np.uint8)
    with rasterio.open(tmp_path / f"{name}_vis.tif", "w", driver="GTiff", height=1000, width=1000,
                       count=3, dtype="uint8", crs=CRS_UTM, transform=from_origin(X0, Y0, 10, 10)) as dst:
        dst.write(vis)
    scl = np.full((500, 500), 6, dtype=np.uint8)
    if cloud_rows:
        scl[:cloud_rows, :] = 9
    with rasterio.open(tmp_path / f"{name}_scl.tif", "w", driver="GTiff", height=500, width=500,
                       count=1, dtype="uint8", crs=CRS_UTM, transform=from_origin(X0, Y0, 20, 20)) as dst:
        dst.write(scl, 1)


def _item(tmp_path, item_id, days_ago, scene, hour=6):
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return SimpleNamespace(
        id=item_id, datetime=when, collection_id="sentinel-2-l2a",
        assets={"visual": SimpleNamespace(href=str(tmp_path / f"{scene}_vis.tif")),
                "scl": SimpleNamespace(href=str(tmp_path / f"{scene}_scl.tif"))},
    )


def _bbox(x_min, x_max, y_min, y_max):
    lons, lats = warp_transform(CRS_UTM, "EPSG:4326", [X0 + x_min, X0 + x_max], [Y0 - y_max, Y0 - y_min])
    return (min(lons), min(lats), max(lons), max(lats))


# ---- fake Supabase -------------------------------------------------------------------------
class _Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.op, self.payload, self.order_by = db, name, [], "select", None, None

    def select(self, *_): self.op = "select"; return self
    def eq(self, k, v): self.filters.append((k, "eq", v)); return self
    def in_(self, k, vs): self.filters.append((k, "in", vs)); return self
    def order(self, k, desc=False): self.order_by = (k, desc); return self
    def upsert(self, row, on_conflict=None): self.op, self.payload = "upsert", (row, on_conflict); return self
    def delete(self): self.op = "delete"; return self

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        match = lambda r: all((r.get(k) == v) if o == "eq" else (r.get(k) in v) for k, o, v in self.filters)
        if self.op == "upsert":
            row, conflict = self.payload
            keys = conflict.split(",")
            for r in rows:
                if all(r.get(k) == row.get(k) for k in keys):
                    r.update(row)
                    break
            else:
                rows.append({**row, "id": len(rows) + 1})
            return SimpleNamespace(data=[row])
        if self.op == "delete":
            self.db.tables[self.name] = [r for r in rows if not match(r)]
            return SimpleNamespace(data=[])
        out = [dict(r) for r in rows if match(r)]
        if self.order_by:
            out.sort(key=lambda r: r.get(self.order_by[0]) or "", reverse=self.order_by[1])
        return SimpleNamespace(data=out)


class _Storage:
    def __init__(self, db): self.db = db
    def from_(self, _): return self
    def upload(self, path, data, _opts): self.db.files[path] = len(data)
    def get_public_url(self, path): return f"https://example.test/{path}"
    def remove(self, paths): [self.db.files.pop(p, None) for p in paths]


class _FakeDB:
    def __init__(self): self.tables, self.files, self.storage = {}, {}, _Storage(self)
    def table(self, name): return _Query(self, name)


class _FakeStac:
    def __init__(self, items): self._items = items
    def search(self, **_kw): return SimpleNamespace(items=lambda: iter(self._items))


# ---- geometry ------------------------------------------------------------------------------
def test_pixel_lonlat_round_trip():
    transform = from_origin(X0, Y0, 10, 10)
    lon, lat = geo_utils.pixel_to_lonlat(transform, "EPSG:32640", 10, 20)
    assert geo_utils.lonlat_to_pixel(transform, "EPSG:32640", lon, lat) == (10, 20)


def test_range_bearing_north_and_east():
    km, bearing = geo_utils.range_bearing_km(26.0, 56.0, 26.1, 56.0)
    assert km == pytest.approx(11.12, abs=0.05) and bearing == pytest.approx(0, abs=0.1)
    _, bearing = geo_utils.range_bearing_km(26.0, 56.0, 26.0, 56.1)
    assert bearing == pytest.approx(90, abs=0.5)


def test_dead_reckon_east_one_hour():
    lat, lon = geo_utils.dead_reckon(26.0, 56.0, 10, 90, 3600)
    assert lat == pytest.approx(26.0, abs=0.01) and lon == pytest.approx(56.185, abs=0.005)


# ---- scene quality -------------------------------------------------------------------------
def test_cloud_and_coverage_are_measured_inside_the_zone_box(tmp_path):
    _write_scene(tmp_path, "cloudy", cloud_rows=100)  # top 2 km of the scene is cloud
    item = _item(tmp_path, "c", 1, "cloudy")
    info = sf.read_scl(item, _bbox(1000, 5000, 0, 4000))
    valid, cloud = sf.scl_quality(info["scl"], info["requested_pixels"])
    assert valid > 95 and cloud == pytest.approx(50, abs=3)


def test_partial_coverage_is_reported(tmp_path):
    _write_scene(tmp_path, "clear")
    info = sf.read_scl(_item(tmp_path, "a", 1, "clear"), _bbox(-4000, 4000, -4000, 4000))
    valid, _ = sf.scl_quality(info["scl"], info["requested_pixels"])
    assert valid == pytest.approx(25, abs=2)


def test_no_overlap_returns_none(tmp_path):
    _write_scene(tmp_path, "clear")
    assert sf.read_scl(_item(tmp_path, "a", 1, "clear"), _bbox(50000, 52000, 2000, 4000)) is None


def test_visual_is_read_at_native_10m(tmp_path):
    _write_scene(tmp_path, "clear")
    item = _item(tmp_path, "a", 1, "clear")
    info = sf.read_scl(item, _bbox(1000, 5000, 1000, 5000))
    rgb, transform, crs = sf.read_visual(item, info["bounds"])
    assert transform.a == 10 and -transform.e == 10 and rgb.shape[0] == 3 and crs == "EPSG:32640"
    assert rgb.shape[1] > 350 and rgb.shape[2] > 350  # 4 km at 10 m is ~400 px, not a thumbnail


# ---- full zone flow ------------------------------------------------------------------------
@pytest.fixture
def zone_flow(tmp_path, monkeypatch):
    _write_scene(tmp_path, "clear")
    _write_scene(tmp_path, "cloudy", cloud_rows=400)  # cloud over the whole zone box
    db = _FakeDB()
    monkeypatch.setattr(sf, "supabase", db)
    items = [_item(tmp_path, "A_new", 1, "clear"), _item(tmp_path, "A_dupe_same_day", 1, "clear", hour=5),
             _item(tmp_path, "B_cloudy", 2, "cloudy"), _item(tmp_path, "C", 3, "clear"),
             _item(tmp_path, "D", 4, "clear"), _item(tmp_path, "E", 5, "clear")]
    zone = Zone("fujairah", "Fujairah anchorage", "anchorage", _bbox(1000, 5000, 1000, 5000), None, 25.1, 56.4, (5, 10, 20), 100)
    return db, _FakeStac(items), zone, SpatialSettings(keep_per_zone=3)


def test_dry_run_writes_nothing(zone_flow):
    db, stac, zone, settings = zone_flow
    result = sf.process_zone(zone, settings, stac, dry_run=True)
    assert [a["scene"] for a in result["accepted"]] == ["A_new", "C", "D"]
    assert not db.tables.get("spatial_snapshots") and not db.files


def test_cloudy_scene_is_never_stored_and_one_capture_per_day(zone_flow):
    db, stac, zone, settings = zone_flow
    result = sf.process_zone(zone, settings, stac)
    stored = [r["scene_id"] for r in db.tables["spatial_snapshots"]]
    assert stored == ["A_new", "C", "D"] and "B_cloudy" not in stored
    assert any(r["scene"] == "B_cloudy" for r in result["rejected"])
    assert all(r["status"] == "fetched" and r["gsd_m"] == 10 for r in db.tables["spatial_snapshots"])


def test_second_run_does_not_churn(zone_flow):
    db, stac, zone, settings = zone_flow
    sf.process_zone(zone, settings, stac)
    before = sorted(db.files)
    again = sf.process_zone(zone, settings, stac)
    assert again["stored"] == [] and sorted(db.files) == before


def test_old_captures_are_pruned(zone_flow):
    db, stac, zone, settings = zone_flow
    sf.process_zone(zone, SpatialSettings(keep_per_zone=3), stac)
    sf.process_zone(zone, SpatialSettings(keep_per_zone=2), stac)
    assert [r["scene_id"] for r in db.tables["spatial_snapshots"]] == ["A_new", "C"]
    assert "fujairah/D.jpg" not in db.files and "fujairah/D_thumb.jpg" not in db.files
