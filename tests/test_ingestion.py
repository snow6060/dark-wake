import unittest
import time
from unittest.mock import MagicMock, patch

from src.ingestion import (
    RSS_FEEDS,
    _fetch_rss_feed,
    _prune_rss_headlines,
    _rss_entry_created_at,
    sanitize_energy_news,
)


class RssFeedFetchTests(unittest.TestCase):
    def test_eia_feed_uses_longer_timeout_for_slow_response(self):
        feed_info = next(feed for feed in RSS_FEEDS if feed["name"] == "EIA Today in Energy")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"""
            <rss version="2.0"><channel>
              <item><title>Energy update</title><link>https://example.com/item</link></item>
            </channel></rss>
        """

        with patch("src.ingestion.urllib.request.urlopen", return_value=response) as urlopen:
            parsed_feed = _fetch_rss_feed(feed_info, {"User-Agent": "test"})

        self.assertEqual(len(parsed_feed.entries), 1)
        self.assertEqual(parsed_feed.entries[0].title, "Energy update")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)

    def test_default_feed_timeout_is_unchanged(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"<rss><channel /></rss>"

        with patch("src.ingestion.urllib.request.urlopen", return_value=response) as urlopen:
            _fetch_rss_feed(
                {"name": "Other feed", "url": "https://example.com/feed"},
                {"User-Agent": "test"},
            )

        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)

    @patch("src.ingestion.supabase")
    def test_prunes_all_rows_beyond_newest_50(self, supabase_client):
        query = supabase_client.table.return_value
        query.select.return_value = query
        query.order.return_value = query
        query.range.return_value = query
        query.execute.side_effect = [
            MagicMock(data=[{"id": 51}, {"id": 52}]),
            MagicMock(data=[]),
        ]
        query.delete.return_value.in_.return_value.execute.return_value = MagicMock(
            data=[{"id": 51}, {"id": 52}]
        )

        deleted_count = _prune_rss_headlines()

        self.assertEqual(deleted_count, 2)
        query.select.assert_called_once_with("id")
        query.order.assert_called_once_with("created_at", desc=True)
        query.range.assert_called_once_with(50, 1049)
        query.delete.return_value.in_.assert_called_once_with("id", [51, 52])

    def test_uses_rss_publication_time_for_headline_ordering(self):
        entry = {"published_parsed": time.gmtime(1792656000)}

        self.assertEqual(
            _rss_entry_created_at(entry),
            "2026-10-22T08:00:00+00:00",
        )

    def test_sanitizer_reframes_conflict_headline_as_commercial_energy_update(self):
        headline, category = sanitize_energy_news(
            "War conflict threatens tanker shipping routes and crude supply"
        )

        self.assertEqual(category, "shipping_routes")
        self.assertEqual(
            headline,
            "Energy shipping route update: commercial market conditions under review.",
        )
        self.assertNotRegex(
            headline.lower(),
            r"\b(war|conflict|threatens|tanker|crude)\b",
        )

    def test_sanitizer_preserves_non_sensitive_commercial_energy_headlines(self):
        headline, category = sanitize_energy_news(
            "Oil inventories rise as refinery demand softens"
        )

        self.assertEqual(headline, "Oil inventories rise as refinery demand softens")
        self.assertEqual(category, "inventories")

    def test_sanitizer_reframes_geographic_conflict_reference(self):
        headline, category = sanitize_energy_news(
            "Middle East tensions raise crude shipping costs"
        )

        self.assertEqual(category, "shipping_routes")
        self.assertNotRegex(headline.lower(), r"\b(middle east|tensions|crude)\b")

    def test_news_endpoint_requests_newest_rows_before_limiting(self):
        import main

        client = MagicMock()
        query = client.table.return_value
        query.select.return_value = query
        query.order.return_value = query
        query.limit.return_value.execute.return_value.data = [
            {"id": 1, "created_at": "2026-10-22T00:00:00+00:00"}
        ]

        with (
            patch("main.supabase", client),
            patch("main.get_tankermap_news", return_value=[]),
        ):
            headlines = main.get_news_feed()

        self.assertEqual(headlines[0]["id"], 1)
        query.order.assert_called_once_with("created_at", desc=True)
        query.limit.assert_called_once_with(50)


if __name__ == "__main__":
    unittest.main()
