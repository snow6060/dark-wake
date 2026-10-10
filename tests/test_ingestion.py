import unittest
from unittest.mock import MagicMock, patch

from src.ingestion import RSS_FEEDS, _fetch_rss_feed


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


if __name__ == "__main__":
    unittest.main()
