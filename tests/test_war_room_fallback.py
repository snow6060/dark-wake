import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException

import main
from src.agents import (
    _context_prompt,
    _google_interaction,
    _invoke,
    _initial_analysis,
    _summarize_previous_debate,
    run_debate_if_due,
)


class WarRoomLoadingTests(unittest.TestCase):
    @patch("src.agents.time.sleep")
    @patch(
        "src.agents._google_interaction",
        side_effect=[
            RuntimeError(
                "Google AI interaction was incomplete and provided no continuation token."
            ),
            "Complete response.",
        ],
    )
    @patch("src.agents._google_api_key", return_value="configured")
    def test_invoke_retries_incomplete_response_without_continuation(
        self,
        _api_key,
        google_interaction,
        sleep,
    ):
        result = _invoke("system", "prompt", "model")

        self.assertEqual(result, "Complete response.")
        self.assertEqual(google_interaction.call_count, 2)
        sleep.assert_called_once_with(3)

    @patch("src.agents.genai.Client")
    def test_google_interaction_continues_incomplete_response(self, client_factory):
        client = client_factory.return_value
        partial = type(
            "Interaction",
            (),
            {
                "status": "incomplete",
                "output_text": "A technical analysis ",
                "continuation_token": "continue-token",
            },
        )()
        complete = type(
            "Interaction",
            (),
            {
                "status": "completed",
                "output_text": "with a complete conclusion.",
                "continuation_token": None,
            },
        )()
        client.interactions.create.side_effect = [partial, complete]

        result = _google_interaction("system", "prompt", "model", 1200)

        self.assertEqual(
            result,
            "A technical analysis with a complete conclusion.",
        )
        self.assertEqual(client.interactions.create.call_count, 2)
        client.interactions.create.assert_any_call(
            model="model",
            continuation_token="continue-token",
            generation_config={"max_output_tokens": 1200},
            store=False,
        )
        client.close.assert_called_once_with()

    @patch("src.agents.genai.Client")
    def test_google_interaction_rejects_incomplete_response_without_continuation(
        self,
        client_factory,
    ):
        client = client_factory.return_value
        response = type(
            "Interaction",
            (),
            {
                "status": "incomplete",
                "output_text": "Truncated technical assessment",
                "continuation_token": None,
            },
        )()
        client.interactions.create.return_value = response

        with self.assertRaisesRegex(RuntimeError, "provided no continuation token"):
            _google_interaction("system", "prompt", "model", 1200)

        client.close.assert_called_once_with()

    @patch("src.agents._invoke", return_value="Complete technical assessment.")
    def test_technical_prompt_requires_plain_text_and_supplied_market_values(
        self,
        invoke,
    ):
        state = {
            "market_context": {
                "price": 112.44,
                "daily_change_pct": 0.01,
                "technical_report": "RSI (14): 76.6",
            },
            "previous_debates": [],
            "initial_technical": "",
            "initial_bullish": "",
            "initial_bearish": "",
        }

        _initial_analysis("technical", state)

        prompt = invoke.call_args.args[1]
        self.assertIn("plain text", prompt)
        self.assertIn("live_context.price", prompt)
        self.assertIn("daily change", prompt)
        self.assertIn("two decimal places", prompt)
        self.assertIn("Do not invent values", prompt)

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

    def test_context_includes_compact_prior_analyses_for_each_agent(self):
        previous = {
            "created_at": "2026-10-21T09:00:00+00:00",
            "market_price": 82.5,
            "signal": "BUY",
            "verdict": '{"rationale":"Supply disruptions may tighten the market."}',
            "transcript": json.dumps([
                {
                    "role": "technical",
                    "message": "RSI momentum is positive.",
                },
                {"role": "bullish", "message": "Hormuz risks support prices."},
                {"role": "bearish", "message": "Weak demand may pressure crude."},
            ]),
        }

        summary = _summarize_previous_debate([previous])
        prompt = _context_prompt(
            {
                "market_context": {"price": 84.0},
                "previous_debates": summary,
            }
        )

        self.assertEqual(summary[0]["created_at"], previous["created_at"])
        self.assertEqual(summary[0]["market_price"], 82.5)
        self.assertEqual(summary[0]["signal"], "BUY")
        self.assertEqual(
            summary[0]["agent_analyses"],
            {
                "technical": "RSI momentum is positive.",
                "bullish": "Hormuz risks support prices.",
                "bearish": "Weak demand may pressure crude.",
            },
        )
        self.assertIn('"verdict_rationale": "Supply disruptions may tighten the market."', prompt)
        self.assertIn('"price": 84.0', prompt)
        self.assertIn("Treat prior analysis as a hypothesis, not a fact or an anchor", prompt)

    def test_prior_agent_analysis_is_bounded_for_prompt_size(self):
        previous = {
            "transcript": [
                {
                    "role": role,
                    "message": "market evidence " * 300,
                }
                for role in ("technical", "bullish", "bearish")
            ]
        }

        summary = _summarize_previous_debate([previous])[0]

        self.assertTrue(
            all(
                len(analysis) <= 900
                for analysis in summary["agent_analyses"].values()
            )
        )

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
