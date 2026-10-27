import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
import requests

import main
from src.agents import (
    MetaModelAPIError,
    MetaModelQuotaError,
    _context_prompt,
    _format_strategy_desk_payload,
    _invoke,
    _initial_analysis,
    _meta_model_interaction,
    _parse_agent_turn,
    _record_prediction,
    _summarize_previous_debate,
    _transcript_for_state,
    compile_trading_graph,
    run_debate_if_due,
)


class StrategyDeskLoadingTests(unittest.TestCase):
    @patch("src.agents.time.sleep")
    @patch("src.agents._meta_model_interaction", side_effect=MetaModelAPIError(429, "rate limit"))
    @patch("src.agents._meta_model_api_key", return_value="configured")
    def test_meta_model_quota_failure_does_not_retry(self, _api_key, interaction, sleep):
        with self.assertRaisesRegex(MetaModelQuotaError, "quota or rate limit"):
            _invoke("system", "prompt", "model")

        interaction.assert_called_once()
        sleep.assert_not_called()

    @patch("src.agents.time.sleep")
    @patch(
        "src.agents._meta_model_interaction",
        side_effect=[requests.Timeout("timed out"), "Complete response."],
    )
    @patch("src.agents._meta_model_api_key", return_value="configured")
    def test_invoke_retries_transient_timeout(self, _api_key, interaction, sleep):
        result = _invoke("system", "prompt", "model")

        self.assertEqual(result, "Complete response.")
        self.assertEqual(interaction.call_count, 2)
        sleep.assert_called_once_with(3)

    @patch("src.agents._meta_model_api_key")
    @patch("src.agents.requests.post")
    def test_meta_model_request_is_blocked_by_default(self, post, api_key):
        with self.assertRaisesRegex(RuntimeError, "disabled during development"):
            _meta_model_interaction("system", "prompt", "model", 1200)

        api_key.assert_not_called()
        post.assert_not_called()

    @patch("src.agents.META_MODEL_API_ENABLED", True)
    @patch("src.agents.requests.post")
    @patch("src.agents._meta_model_api_key", return_value="configured")
    def test_meta_model_uses_openai_compatible_responses_request(
        self,
        _api_key,
        post,
    ):
        post.return_value.ok = True
        post.return_value.json.return_value = {
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "Model output"}],
            }]
        }

        result = _meta_model_interaction("system", "prompt", "model", 1200)

        self.assertEqual(result, "Model output")
        post.assert_called_once_with(
            "https://api.meta.ai/v1/responses",
            headers={
                "Authorization": "Bearer configured",
                "Content-Type": "application/json",
            },
            json={
                "model": "model",
                "instructions": "system",
                "input": "prompt",
                "max_output_tokens": 1200,
            },
            timeout=60,
        )

    @patch(
        "src.agents._meta_model_interaction",
        side_effect=[
            MetaModelAPIError(404, "model_not_found"),
            "fallback response",
        ],
    )
    @patch("src.agents._meta_model_api_key", return_value="configured")
    def test_invoke_uses_model_fallback_after_model_not_found(self, _api_key, interaction):
        self.assertEqual(_invoke("system", "prompt", "requested-model"), "fallback response")
        self.assertEqual(
            [call.args[2] for call in interaction.call_args_list],
            ["requested-model", "meta-models/muse-spark-open"],
        )

    @patch("src.agents.META_MODEL_API_ENABLED", True)
    @patch("src.agents.requests.post")
    @patch("src.agents._meta_model_api_key", return_value="sensitive-test-key")
    def test_meta_model_error_redacts_api_key(self, _api_key, post):
        post.return_value.ok = False
        post.return_value.status_code = 401
        post.return_value.json.return_value = {
            "error": {"message": "invalid key sensitive-test-key"}
        }

        with self.assertRaises(MetaModelAPIError) as raised:
            _meta_model_interaction("system", "prompt", "model", 1200)

        self.assertNotIn("sensitive-test-key", str(raised.exception))

    @patch("src.agents._invoke", return_value=json.dumps({
        "analysis": "Complete technical assessment.",
        "direction": "UP",
        "confidence": 71,
    }))
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
            "initial_supply_thesis": "",
            "initial_demand_thesis": "",
        }

        _initial_analysis("technical", state)

        prompt = invoke.call_args.args[1]
        self.assertIn("full supplied commodity basket", prompt)
        self.assertIn("RSI (14)", prompt)
        self.assertIn("live_context", prompt)
        self.assertIn("rather than inventing values", prompt)

    @patch("src.agents._invoke", return_value=json.dumps({
        "analysis": "Evidence-led supply view.",
        "direction": "UP",
        "confidence": 63,
    }))
    def test_supply_analysis_updates_the_reframed_state_field(self, _invoke):
        result = _initial_analysis(
            "supply",
            {
                "market_context": {"price": 80.0},
                "initial_technical": "Technical view",
            },
        )

        self.assertEqual(
            result,
            {
                "initial_supply_thesis": "Evidence-led supply view.",
                "supply_direction": "UP",
            },
        )

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
                "supply_thesis": "Hormuz risks support prices.",
                "demand_thesis": "Weak demand may pressure crude.",
            },
        )
        self.assertIn('"verdict_rationale": "Supply disruptions may tighten the market."', prompt)
        self.assertIn('"price": 84.0', prompt)
        self.assertIn("Treat prior analysis as a hypothesis, not a fact or an anchor", prompt)

    def test_agent_accuracy_scores_are_included_in_prompt_context(self):
        prompt = _context_prompt({
            "market_context": {"price": 84.0},
            "agent_accuracy": [{
                "agent_name": "supply",
                "evaluated_predictions": 20,
                "accuracy": 0.65,
            }],
        })

        self.assertIn('"agent_name": "supply"', prompt)
        self.assertIn('"accuracy": 0.65', prompt)
        self.assertIn("historical accuracy", prompt)

    def test_n8n_response_contract_contains_three_paragraph_broadcast_and_tags(self):
        payload = _format_strategy_desk_payload({
            "id": "run-1",
            "created_at": "2026-10-27T08:00:00+00:00",
            "market_price": 82.4,
            "market_context": {
                "symbol": "BZ=F",
                "price": 82.4,
                "daily_change_pct": -0.5,
                "price_basis": "last_close",
                "price_as_of": "2026-10-27",
                "commodity_basket": {
                    "BZ=F": {
                        "name": "Brent Crude",
                        "status": "available",
                        "price": 82.4,
                        "price_basis": "daily_close",
                        "price_as_of": "2026-10-27",
                        "indicators": {"rsi_14": 48.2},
                    },
                },
                "headlines": [{
                    "title": "Energy supply update: commercial market conditions under review.",
                    "category": "supply",
                }],
            },
            "verdict": {
                "signal": "HOLD",
                "conviction": 55,
                "support": 80.0,
                "resistance": 85.0,
                "rationale": "Evidence is mixed.",
            },
        })

        self.assertEqual(len(payload["broadcast_summary"].split("\n\n")), 3)
        self.assertEqual(payload["brent_price"]["price"], 82.4)
        self.assertEqual(len(payload["commodity_basket_summary"]), 1)
        self.assertEqual(payload["desk_action"]["signal"], "HOLD")
        self.assertEqual(payload["desk_action"]["conviction_pct"], 55)
        self.assertEqual(payload["top_headline"]["category"], "supply")
        self.assertEqual(len(payload["youtube_tags"]), 5)

    @patch("src.agents.supabase")
    def test_forecast_persistence_saves_agent_directions_for_later_scoring(self, supabase_client):
        _record_prediction(
            "run-1",
            {
                "price": 80,
                "commodity_basket": {
                    "BZ=F": {"status": "available", "price": 79.5},
                },
            },
            {"signal": "BUY"},
            {"technical": "UP", "supply": "UP", "demand": "NEUTRAL"},
        )

        saved = supabase_client.table.return_value.insert.call_args.args[0]
        self.assertEqual(saved["analysis_id"], "run-1")
        self.assertEqual(saved["symbol"], "BZ=F")
        self.assertEqual(saved["base_price"], 79.5)
        self.assertEqual(saved["predicted_direction"], "UP")
        self.assertEqual(saved["agent_predictions"]["demand"], "NEUTRAL")

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

    def test_transcript_uses_reframed_agent_names_and_legacy_client_roles(self):
        state = {
            "initial_technical": "Technical view",
            "initial_supply_thesis": "Supply view",
            "initial_demand_thesis": "Demand view",
            "supply_rebuttal_1": "Supply rebuttal one",
            "demand_rebuttal_1": "Demand rebuttal one",
            "supply_rebuttal_2": "Supply rebuttal two",
            "demand_rebuttal_2": "Demand rebuttal two",
        }
        transcript = _transcript_for_state(
            state
        )

        self.assertEqual(
            [turn["agent"] for turn in transcript],
            [
                "Technical Analysis",
                "Supply Thesis",
                "Demand Thesis",
                "Supply Thesis",
                "Demand Thesis",
                "Supply Thesis",
                "Demand Thesis",
            ],
        )
        self.assertEqual(
            [turn["role"] for turn in transcript],
            ["technical", "bullish", "bearish", "bullish", "bearish", "bullish", "bearish"],
        )

    @patch(
        "src.agents._invoke",
        side_effect=[
            *[
                json.dumps({
                    "analysis": f"Agent stage {index}",
                    "direction": "UP" if index % 2 else "DOWN",
                    "confidence": 60,
                })
                for index in range(1, 8)
            ],
            json.dumps(
                {
                    "signal": "HOLD",
                    "conviction": 50,
                    "short_term_trend": "NEUTRAL",
                    "long_term_trend": "NEUTRAL",
                    "support": 79.0,
                    "resistance": 81.0,
                    "rationale": "Balanced evidence.",
                    "risk_factors": [],
                }
            ),
        ],
    )
    @patch("src.agents._gather_market_context", return_value={"price": 80.0})
    def test_refactored_analysis_graph_runs_all_thesis_stages(
        self,
        _gather_market_context,
        invoke,
    ):
        result = compile_trading_graph().invoke(
            {
                "initial_technical": "",
                "initial_supply_thesis": "",
                "initial_demand_thesis": "",
                "verdict": {},
            }
        )

        self.assertEqual(result["initial_supply_thesis"], "Agent stage 2")
        self.assertEqual(result["initial_demand_thesis"], "Agent stage 3")
        self.assertEqual(result["supply_rebuttal_1"], "Agent stage 4")
        self.assertEqual(result["demand_rebuttal_1"], "Agent stage 5")
        self.assertEqual(result["supply_rebuttal_2"], "Agent stage 6")
        self.assertEqual(result["demand_rebuttal_2"], "Agent stage 7")
        self.assertEqual(result["technical_direction"], "UP")
        self.assertEqual(result["supply_direction"], "DOWN")
        self.assertEqual(result["demand_direction"], "UP")
        self.assertEqual(result["verdict"]["signal"], "HOLD")
        self.assertEqual(invoke.call_count, 8)

    def test_strategy_desk_routes_are_documented_with_legacy_aliases(self):
        paths = {route.path for route in main.app.routes}
        documented_paths = set(main.app.openapi()["paths"])

        self.assertIn("/api/strategy-desk/debates", paths)
        self.assertIn("/api/strategy-desk/run", paths)
        self.assertIn("/api/war-room/debates", paths)
        self.assertIn("/api/war-room/run", paths)
        self.assertIn("/api/strategy-desk/debates", documented_paths)
        self.assertIn("/api/strategy-desk/run", documented_paths)
        self.assertNotIn("/api/war-room/debates", documented_paths)
        self.assertNotIn("/api/war-room/run", documented_paths)

    @patch("main.run_debate_if_due")
    @patch("main.get_recent_debates")
    def test_strategy_desk_endpoint_returns_saved_runs_without_running_analysis(
        self,
        get_recent_debates,
        run_debate,
    ):
        saved = [{"id": "saved-debate", "market_price": 80.5}]
        get_recent_debates.return_value = saved

        result = main.get_strategy_desk_debates()

        self.assertEqual(result, saved)
        get_recent_debates.assert_called_once_with()
        run_debate.assert_not_called()

    @patch("main.run_debate_if_due")
    @patch("main.get_recent_debates", side_effect=RuntimeError("Supabase read failed"))
    def test_strategy_desk_endpoint_surfaces_history_read_failure(
        self,
        get_recent_debates,
        run_debate,
    ):
        with self.assertRaises(HTTPException) as raised:
            main.get_strategy_desk_debates()

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "Supabase read failed")
        get_recent_debates.assert_called_once_with()
        run_debate.assert_not_called()

    @patch("src.agents.META_MODEL_API_ENABLED", True)
    @patch("src.agents.run_agent_pipeline")
    @patch("src.agents.get_recent_debates")
    def test_due_check_reuses_analysis_under_twenty_four_hours(
        self,
        get_recent_debates,
        run_agent_pipeline,
    ):
        recent = [{
            "id": "recent-debate",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=11)).isoformat(),
            "market_price": 80.5,
            "market_context": {
                "price": 80.5,
                "price_basis": "last_close",
                "price_as_of": "2026-10-27",
            },
            "verdict": {
                "signal": "HOLD",
                "conviction": 50,
                "support": 79,
                "resistance": 82,
                "rationale": "Balanced data.",
            },
        }]
        get_recent_debates.return_value = recent

        result = run_debate_if_due()
        self.assertEqual(result["id"], recent[0]["id"])
        self.assertEqual(len(result["broadcast_summary"].split("\n\n")), 3)
        run_agent_pipeline.assert_not_called()

    @patch("src.agents.get_recent_debates")
    def test_due_check_is_blocked_without_loading_history_when_disabled(
        self,
        get_recent_debates,
    ):
        with self.assertRaisesRegex(RuntimeError, "debate runs are disabled"):
            run_debate_if_due()

        get_recent_debates.assert_not_called()

    def test_manual_analysis_endpoints_return_503_when_disabled(self):
        for endpoint in (main.trigger_agent_analysis, main.run_strategy_desk_analysis):
            with self.subTest(endpoint=endpoint.__name__):
                with self.assertRaises(HTTPException) as raised:
                    endpoint()
                self.assertEqual(raised.exception.status_code, 503)
                self.assertIn("debate runs are disabled", raised.exception.detail)

    @patch("src.agents.META_MODEL_API_ENABLED", True)
    @patch("src.agents.run_agent_pipeline", return_value={"id": "new-debate"})
    @patch("src.agents.get_recent_debates")
    def test_due_check_runs_analysis_after_twenty_four_hours(
        self,
        get_recent_debates,
        run_agent_pipeline,
    ):
        get_recent_debates.return_value = [{
            "id": "old-debate",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
        }]

        self.assertEqual(run_debate_if_due(), {"id": "new-debate"})
        run_agent_pipeline.assert_called_once_with()

    @patch("src.scheduler.META_MODEL_API_ENABLED", True)
    @patch("src.scheduler.BackgroundScheduler")
    def test_scheduler_runs_strategy_desk_daily_at_eight_london(
        self,
        scheduler_factory,
    ):
        from src.scheduler import start_scheduler

        scheduler = scheduler_factory.return_value
        with patch("builtins.print"):
            start_scheduler()
        strategy_desk_job = next(
            call for call in scheduler.add_job.call_args_list
            if call.kwargs.get("id") == "strategy_desk_daily_analysis"
        )

        self.assertEqual(strategy_desk_job.args[1], "cron")
        self.assertEqual(strategy_desk_job.kwargs["hour"], 8)
        self.assertEqual(strategy_desk_job.kwargs["minute"], 0)
        self.assertEqual(strategy_desk_job.kwargs["timezone"], "Europe/London")

    @patch("src.scheduler.BackgroundScheduler")
    def test_scheduler_does_not_register_strategy_desk_job_when_disabled(
        self,
        scheduler_factory,
    ):
        from src.scheduler import start_scheduler

        scheduler = scheduler_factory.return_value
        with patch("builtins.print"):
            start_scheduler()

        job_ids = {
            call.kwargs.get("id") for call in scheduler.add_job.call_args_list
        }
        self.assertNotIn("strategy_desk_daily_analysis", job_ids)


if __name__ == "__main__":
    unittest.main()
