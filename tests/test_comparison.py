import unittest

from stock_research.comparison import build_comparison_rows


class ComparisonTests(unittest.TestCase):
    def test_comparison_formats_latest_values_and_preserves_citations(self):
        point = {"year": 2025, "value": 1_250_000_000, "filed": "2025-11-01", "source_tag": "RevenueTag",
                 "url": "https://www.sec.gov/Archives/edgar/data/1/filing.txt"}
        margin = {**point, "value": 42.25, "source_tag": "GrossProfitTag / RevenueTag × 100"}
        records = [
            {"ticker": "AAA", "metrics": {"revenue": [point], "gross_margin": [margin], "operating_cash_flow": [], "long_term_debt": []}},
            {"ticker": "BBB", "metrics": {"revenue": [{**point, "year": 2024, "value": 500_000_000}], "gross_margin": [], "operating_cash_flow": [], "long_term_debt": []}},
        ]
        rows, sources = build_comparison_rows(records)
        self.assertEqual(rows[0]["Revenue"], "$1.25B")
        self.assertEqual(rows[0]["Revenue FY"], "2025")
        self.assertEqual(rows[0]["Gross margin"], "42.2%")
        self.assertEqual(rows[1]["Gross margin"], "Unavailable")
        self.assertEqual(rows[1]["Gross margin FY"], "—")
        self.assertEqual(sources[0]["url"], point["url"])
        self.assertEqual(sources[0]["filed"], "2025-11-01")


if __name__ == "__main__":
    unittest.main()
