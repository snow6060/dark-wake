import unittest
from unittest.mock import patch, MagicMock

from src.vision import (
    process_satellite_tile,
    get_spatial_telemetry,
    CHOKEPOINTS,
    SAM_3_1_ENABLED,
    LOCATION_BBOXES,
    FALLBACK_ASSETS,
    _extract_thumbnail_url,
    fetch_and_store_daily_snapshots,
)
from main import get_spatial_snapshots


class VisionModuleTests(unittest.TestCase):
    def test_spatial_telemetry_returns_fallback_when_disabled(self):
        result = get_spatial_telemetry("Strait of Hormuz")
        self.assertEqual(result["chokepoint"], "Strait of Hormuz")
        self.assertIn("spatial_congestion_index", result)
        self.assertEqual(result["token_metadata"]["model"], "SAM 3.1 (mocked)")

    def test_spatial_telemetry_for_bab_el_mandeb(self):
        result = get_spatial_telemetry("Bab el-Mandeb")
        self.assertEqual(result["chokepoint"], "Bab el-Mandeb")
        self.assertIn("segment_bboxes", result)

    def test_spatial_telemetry_for_malacca(self):
        result = get_spatial_telemetry("Malacca Strait / Singapore Hub")
        self.assertEqual(result["chokepoint"], "Malacca Strait / Singapore Hub")
        self.assertIn("mask_reference", result)

    @patch("src.vision.SAM_3_1_ENABLED", True)
    def test_live_sam_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            process_satellite_tile("Strait of Hormuz")

    def test_chokepoints_configured(self):
        names = [c["name"] for c in CHOKEPOINTS]
        self.assertIn("Strait of Hormuz", names)
        self.assertIn("Bab el-Mandeb", names)
        self.assertIn("Malacca Strait / Singapore Hub", names)

    def test_location_bboxes_covers_all_chokepoints_and_docks(self):
        expected_keys = [
            "Strait of Hormuz",
            "Bab el-Mandeb",
            "Port of Fujairah",
            "Suez Canal",
            "Malacca Strait",
            "Port of Singapore",
            "Port of Rotterdam",
            "Port of Jebel Ali",
        ]
        for key in expected_keys:
            self.assertIn(key, LOCATION_BBOXES)
            self.assertIn(key, FALLBACK_ASSETS)
            self.assertEqual(len(LOCATION_BBOXES[key]), 4)

    def test_extract_thumbnail_url(self):
        feature_with_thumb = {
            "assets": {
                "thumbnail": {"href": "https://example.com/thumb.png"},
                "visual": {"href": "https://example.com/visual.tif"},
            }
        }
        self.assertEqual(_extract_thumbnail_url(feature_with_thumb), "https://example.com/thumb.png")

        feature_with_preview = {
            "assets": {
                "rendered_preview": {"href": "https://example.com/preview.jpg"},
            }
        }
        self.assertEqual(_extract_thumbnail_url(feature_with_preview), "https://example.com/preview.jpg")

        feature_empty = {"assets": {}}
        self.assertIsNone(_extract_thumbnail_url(feature_empty))

    def test_get_spatial_snapshots_endpoint(self):
        res = get_spatial_snapshots()
        self.assertIn("snapshots", res)
        self.assertIn("rolling_window_days", res)
        self.assertEqual(res["rolling_window_days"], 3)
        self.assertTrue(len(res["snapshots"]) > 0)
        first = res["snapshots"][0]
        self.assertIn("location_name", first)
        self.assertIn("image_url", first)
        self.assertIn("fallback_url", first)


if __name__ == "__main__":
    unittest.main()
