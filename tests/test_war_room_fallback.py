import unittest
from unittest.mock import patch

from fastapi import HTTPException

import main
from src.agents import _context_prompt


class WarRoomFallbackTests(unittest.TestCase):
    def test_weekend_last_close_is_explicit_in_agent_context(self):
        prompt = _context_prompt(
            {
                "market_context": {
                    "market_is_closed": True,
                    "price_basis": "last_close",
                    "price_as_of": "2026-10-09T00:00:00",
                }
            }
        )

        self.assertIn("closed for the weekend", prompt)
        self.assertIn("not a live weekend quote", prompt)
        self.assertIn("price_as_of", prompt)

    @patch("main.get_recent_debates")
    @patch("main.run_debate_if_due", side_effect=RuntimeError("Yahoo Finance unavailable"))
    def test_debates_endpoint_returns_saved_runs_when_refresh_fails(
        self,
        _run_debate,
        get_recent_debates,
    ):
        saved = [{"id": "saved-debate", "market_price": 80.5}]
        get_recent_debates.return_value = saved

        result = main.get_war_room_debates()

        self.assertEqual(result, saved)
        get_recent_debates.assert_called_once_with()

    @patch("main.get_recent_debates", return_value=[])
    @patch("main.run_debate_if_due", side_effect=RuntimeError("Yahoo Finance unavailable"))
    def test_debates_endpoint_reports_refresh_failure_without_saved_history(
        self,
        _run_debate,
        _get_recent_debates,
    ):
        with self.assertRaises(HTTPException) as raised:
            main.get_war_room_debates()

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "Yahoo Finance unavailable")


if __name__ == "__main__":
    unittest.main()
