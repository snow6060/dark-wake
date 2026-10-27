import unittest
from unittest.mock import patch, MagicMock

from src.vision import (
    process_satellite_tile,
    get_spatial_telemetry,
    CHOKEPOINTS,
    SAM_3_1_ENABLED,
)


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


if __name__ == "__main__":
    unittest.main()
