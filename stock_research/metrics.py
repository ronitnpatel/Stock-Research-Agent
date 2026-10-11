"""Deterministic selection and arithmetic for annual SEC XBRL facts."""
from __future__ import annotations

TAGS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenues"),
    "gross_profit": ("GrossProfit",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "long_term_debt": ("LongTermDebtCurrent", "LongTermDebtNoncurrent", "LongTermDebtAndFinanceLeaseObligationsCurrent", "LongTermDebtAndFinanceLeaseObligationsNoncurrent"),
}
FORMS = {"10-K", "20-F", "40-F"}


def _annual_observations(facts: dict, tags: tuple[str, ...], cik: int) -> dict[int, dict]:
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    by_year: dict[int, dict] = {}
    for tag in tags:
        definition = usgaap.get(tag)
        if not definition:
            continue
        units = definition.get("units", {})
        observations = units.get("USD", [])
        for obs in observations:
            if obs.get("form") not in FORMS or not obs.get("fy") or not obs.get("filed") or not obs.get("accn"):
                continue
            # Filter out quarterly contexts so trend points represent annual flows, not partial periods.
            start, end = obs.get("start"), obs.get("end", "")
            if start and (int(end[:4]) - int(start[:4]) not in (0, 1) or (int(end[:4]) == int(start[:4]) and (int(end[5:7]) - int(start[5:7])) < 10)):
                continue
            year = int(obs["fy"])
            accn = obs["accn"]
            candidate = {"year": year, "value": float(obs["val"]), "filed": obs["filed"], "form": obs["form"],
                         "source_tag": tag, "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{accn}.txt"}
            if year not in by_year or candidate["filed"] > by_year[year]["filed"]:
                by_year[year] = candidate
    return by_year


def build_metrics(facts: dict, cik: int) -> dict[str, list[dict]]:
    """Return up to five latest annual points; all values and margin arithmetic are code-derived."""
    result: dict[str, list[dict]] = {}
    for metric in ("revenue", "gross_profit", "operating_cash_flow"):
        annual = _annual_observations(facts, TAGS[metric], cik)
        result[metric] = [annual[y] for y in sorted(annual)[-5:]]

    # Balance-sheet debt is point-in-time: combine components only within the same filing accession.
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    debt_rows: dict[tuple[str, str], dict] = {}
    for tag in TAGS["long_term_debt"]:
        for obs in usgaap.get(tag, {}).get("units", {}).get("USD", []):
            if obs.get("form") not in FORMS or not obs.get("fy") or not obs.get("filed") or not obs.get("accn") or obs.get("fp") != "FY":
                continue
            key = (str(obs["fy"]), obs["accn"])
            row = debt_rows.setdefault(key, {"year": int(obs["fy"]), "filed": obs["filed"], "form": obs["form"], "accn": obs["accn"], "components": {}})
            if obs["filed"] >= row["filed"]:
                row["components"][tag] = float(obs["val"])
    debt_by_year: dict[int, dict] = {}
    for row in debt_rows.values():
        if not row["components"]:
            continue
        # Prefer one standardized tag from each class to avoid double-counting alternate concepts.
        current = next((row["components"][tag] for tag in TAGS["long_term_debt"] if "Current" in tag and tag in row["components"]), 0.0)
        noncurrent = next((row["components"][tag] for tag in TAGS["long_term_debt"] if "Noncurrent" in tag and tag in row["components"]), 0.0)
        total = current + noncurrent
        urlid = row["accn"].replace("-", "")
        point = {"year": row["year"], "value": total, "filed": row["filed"], "form": row["form"],
                 "source_tag": " + ".join(row["components"]), "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{urlid}/{row['accn']}.txt"}
        if row["year"] not in debt_by_year or point["filed"] > debt_by_year[row["year"]]["filed"]:
            debt_by_year[row["year"]] = point
    result["long_term_debt"] = [debt_by_year[y] for y in sorted(debt_by_year)[-5:]]

    revenues = {x["year"]: x for x in result["revenue"]}
    profits = {x["year"]: x for x in result["gross_profit"]}
    margins = []
    # Gross margin is the only ratio here; calculate it from matching annual source facts.
    for year in sorted(revenues.keys() & profits.keys())[-5:]:
        if revenues[year]["value"]:
            source = revenues[year]
            margins.append({**source, "value": 100 * profits[year]["value"] / source["value"], "source_tag": f"{profits[year]['source_tag']} / {source['source_tag']} × 100"})
    result["gross_margin"] = margins
    return result
