"""Presentation helpers for consistent, citation-backed peer comparisons."""
from __future__ import annotations


METRICS = (
    ("revenue", "Revenue"),
    ("gross_margin", "Gross margin"),
    ("operating_cash_flow", "Operating cash flow"),
    ("long_term_debt", "Long-term debt"),
)


def _display(metric: str, value: float) -> str:
    if metric == "gross_margin":
        return f"{value:.1f}%"
    return f"${value / 1_000_000_000:,.2f}B"


def build_comparison_rows(companies: list[dict]) -> tuple[list[dict], list[dict]]:
    """Use the latest available point for each company and metric; keep period/citation metadata."""
    rows, sources = [], []
    # Keep each metric's fiscal year alongside its value because filers use different calendars.
    for company in companies:
        row = {"Ticker": company["ticker"]}
        for key, label in METRICS:
            series = company.get("metrics", {}).get(key, [])
            point = series[-1] if series else None
            row[label] = _display(key, point["value"]) if point else "Unavailable"
            row[f"{label} FY"] = str(point["year"]) if point else "—"
            if point:
                sources.append({"ticker": company["ticker"], "metric": label, "year": point["year"],
                                "filed": point["filed"], "source_tag": point["source_tag"], "url": point["url"]})
        rows.append(row)
    return rows, sources
