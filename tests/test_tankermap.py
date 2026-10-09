import unittest
from datetime import datetime, timezone

from src.tankermap import _parse_news_page, _parse_strait_page


class TankerMapPageParserTests(unittest.TestCase):
    def test_parses_public_chokepoint_series_and_latest_vessel_position(self):
        page = """
        <div class="kpi"><div class="kpi-val">2</div>
        <div class="kpi-lbl">Vessels Currently in Zone</div></div>
        <tbody id="vesselZoneTbody">
          <tr><td>SHIP A</td><td>Crude Oil Tanker</td><td>Flag</td>
          <td>0 kn</td><td>Port</td><td>2026-10-09 18:28</td></tr>
          <tr><td>SHIP B</td><td>Oil Products Tanker</td><td>Flag</td>
          <td>1 kn</td><td>Port</td><td>2026-10-09 17:20</td></tr>
        </tbody>
        <template id="analyticsStraitData">{"cpKey":"hormuz","chart":{
          "dates":["2026-10-08","2026-10-09"],"lng":[0,1],
          "crude":[2,0],"product":[1,3],"total":[3,4]
        }}</template>
        """

        records, snapshot = _parse_strait_page(page, "hormuz")

        self.assertEqual([record["vessel_count_total"] for record in records], [3, 4])
        self.assertEqual(records[-1]["vessel_count_crude"], 0)
        self.assertEqual(snapshot["vessels_observed"], 2)
        self.assertEqual(snapshot["tankers_identified"], 2)
        self.assertEqual(
            snapshot["snapshot_at"],
            datetime(2026, 10, 9, 18, 28, tzinfo=timezone.utc).replace(tzinfo=None),
        )

    def test_rejects_mismatched_daily_series(self):
        page = """
        <template id="analyticsStraitData">{"cpKey":"hormuz","chart":{
          "dates":["2026-10-09"],"lng":[],"crude":[0],"product":[0],"total":[0]
        }}</template>
        """

        with self.assertRaisesRegex(ValueError, "mismatched daily transit series"):
            _parse_strait_page(page, "hormuz")

    def test_parses_public_news_headlines_and_publication_dates(self):
        page = """
        <a href="/news/hormuz-update" class="news-card news-card-market">
          <span class="news-tag news-tag-market">market</span>
          <span class="news-date">Sep 04, 06:30 UTC</span>
          <div class="news-card-title">Hormuz transit update</div>
        </a>
        """
        now = datetime(2026, 10, 10, tzinfo=timezone.utc)

        articles = _parse_news_page(page, now)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source"], "TankerMap")
        self.assertEqual(articles[0]["title"], "Hormuz transit update")
        self.assertEqual(
            articles[0]["published_at"],
            "2026-09-04T06:30:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
