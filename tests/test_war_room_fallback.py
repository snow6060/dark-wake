import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException

import main
from src.agents import _context_prompt, run_debate_if_due


class WarRoomLoadingTests(unittest.TestCase):
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

    @patch("main.run_debate_if_due")
    @patch("main.get_recent_debates")
    def test_debates_endpoint_returns_saved_runs_without_running_analysis(
        self,
        get_recent_debates,
        run_debate,
    ):
        saved = [{"id": "saved-debate", "market_price": 80.5}]
        get_recent_debates.return_value = saved

        result = main.get_war_room_debates()

        self.assertEqual(result, saved)
        get_recent_debates.assert_called_once_with()
        run_debate.assert_not_called()

    @patch("main.run_debate_if_due")
    @patch("main.get_recent_debates", side_effect=RuntimeError("Supabase read failed"))
    def test_debates_endpoint_surfaces_history_read_failure(
        self,
        get_recent_debates,
        run_debate,
    ):
        with self.assertRaises(HTTPException) as raised:
            main.get_war_room_debates()

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "Supabase read failed")
        get_recent_debates.assert_called_once_with()
        run_debate.assert_not_called()

    @patch("src.agents.run_agent_pipeline")
    @patch("src.agents.get_recent_debates")
    def test_due_check_reuses_debate_under_twelve_hours(
        self,
        get_recent_debates,
        run_agent_pipeline,
    ):
        recent = [{
            "id": "recent-debate",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=11)).isoformat(),
        }]
        get_recent_debates.return_value = recent

        self.assertEqual(run_debate_if_due(), recent[0])
        run_agent_pipeline.assert_not_called()

    @patch("src.agents.run_agent_pipeline", return_value={"id": "new-debate"})
    @patch("src.agents.get_recent_debates")
    def test_due_check_runs_analysis_after_twelve_hours(
        self,
        get_recent_debates,
        run_agent_pipeline,
    ):
        get_recent_debates.return_value = [{
            "id": "old-debate",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat(),
        }]

        self.assertEqual(run_debate_if_due(), {"id": "new-debate"})
        run_agent_pipeline.assert_called_once_with()

    @patch("src.scheduler.BackgroundScheduler")
    def test_scheduler_checks_for_debates_at_nine_and_twenty_one_london(
        self,
        scheduler_factory,
    ):
        from src.scheduler import start_scheduler

        scheduler = scheduler_factory.return_value
        with patch("builtins.print"):
            start_scheduler()
        war_room_job = next(
            call for call in scheduler.add_job.call_args_list
            if call.kwargs.get("id") == "war_room_debate_refresh"
        )

        self.assertEqual(war_room_job.args[1], "cron")
        self.assertEqual(war_room_job.kwargs["hour"], "9,21")
        self.assertEqual(war_room_job.kwargs["minute"], 0)
        self.assertEqual(war_room_job.kwargs["timezone"], "Europe/London")


if __name__ == "__main__":
    unittest.main()
