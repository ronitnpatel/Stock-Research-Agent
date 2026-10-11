"""Small, bounded SEC Company Facts client."""
from __future__ import annotations
import os
import re
import time
from functools import lru_cache
import requests

SEC_ROOT = "https://www.sec.gov"
DATA_ROOT = "https://data.sec.gov"
TIMEOUT = 15


class SECDataError(RuntimeError):
    pass


def _get(url: str) -> dict:
    # SEC requires a descriptive User-Agent; bounded retries avoid hammering the public API.
    headers = {"User-Agent": os.getenv("SEC_USER_AGENT", "OpenBrief research contact@example.com"), "Accept-Encoding": "gzip, deflate"}
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    time.sleep(min(1 + attempt, 2))
                    continue
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            if attempt == 2:
                raise SECDataError("SEC request failed after bounded retries. Check your connection and try later.") from exc
            time.sleep(0.5 * (attempt + 1))
    raise SECDataError("SEC data is temporarily unavailable.")


@lru_cache(maxsize=1)
def _ticker_map() -> dict[str, dict]:
    # This directory changes infrequently, so keep one copy for the app process.
    payload = _get(f"{SEC_ROOT}/files/company_tickers.json")
    return {str(row["ticker"]).upper(): {"cik": int(row["cik_str"]), "name": row["title"]} for row in payload.values()}


def resolve_ticker(ticker: str) -> dict:
    try:
        company = _ticker_map().get(ticker.upper())
    except (KeyError, TypeError, SECDataError) as exc:
        if isinstance(exc, SECDataError):
            raise
        raise SECDataError("SEC ticker directory returned an unexpected response.") from exc
    if not company:
        raise SECDataError(f"Ticker {ticker} was not found in the SEC company ticker directory.")
    return company


@lru_cache(maxsize=16)
def fetch_company_facts(cik: int) -> dict:
    # Keep recent company payloads in memory so peer runs do not repeatedly download them.
    return _get(f"{DATA_ROOT}/api/xbrl/companyfacts/CIK{cik:010d}.json")


@lru_cache(maxsize=32)
def fetch_recent_risk_filings(cik: int, limit: int = 5) -> tuple[dict, ...]:
    """Return a few recent annual, quarterly, and current reports with safe document URLs."""
    payload = _get(f"{DATA_ROOT}/submissions/CIK{cik:010d}.json")
    recent = payload.get("filings", {}).get("recent", {})
    required = ("form", "filingDate", "accessionNumber", "primaryDocument")
    count = min((len(recent.get(key, [])) for key in required), default=0)
    if not count:
        return ()
    rows = []
    # Submissions are delivered as parallel arrays; optional columns may be shorter or absent.
    for index in range(count):
        form, filed, accession, document = (recent[key][index] for key in required)
        description = recent.get("primaryDocDescription", [""] * count)[index]
        items = recent.get("items", [""] * count)[index]
        if form not in {"10-K", "10-Q", "8-K"}:
            continue
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession or ""):
            continue
        # SEC primary-document names are data. Reject any path components before URL construction.
        if not re.fullmatch(r"[A-Za-z0-9._-]+", document or ""):
            continue
        accession_dir = accession.replace("-", "")
        rows.append({"form": form, "filed": filed, "accession": accession, "description": description,
                     "items": items, "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_dir}/{document}"})
        if len(rows) >= max(1, min(limit, 8)):
            break
    return tuple(rows)


@lru_cache(maxsize=16)
def fetch_filing_document(url: str) -> str:
    """Fetch one known SEC filing document with retries and an 8 MiB response cap."""
    if not url.startswith("https://www.sec.gov/Archives/edgar/data/"):
        raise SECDataError("Refusing to retrieve a filing outside the SEC archive.")
    headers = {"User-Agent": os.getenv("SEC_USER_AGENT", "OpenBrief research contact@example.com"),
               "Accept-Encoding": "gzip, deflate"}
    # Stream the response so the size cap is enforced before the full document is held in memory.
    for attempt in range(3):
        try:
            with requests.get(url, headers=headers, timeout=TIMEOUT, stream=True) as response:
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        time.sleep(min(1 + attempt, 2))
                        continue
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > 8 * 1024 * 1024:
                    raise SECDataError("SEC filing document exceeds the 8 MiB retrieval limit.")
                parts, size = [], 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise SECDataError("SEC filing document exceeds the 8 MiB retrieval limit.")
                    parts.append(chunk)
                return b"".join(parts).decode(response.encoding or "utf-8", errors="replace")
        except SECDataError:
            raise
        except requests.RequestException as exc:
            if attempt == 2:
                raise SECDataError("SEC filing document request failed after bounded retries.") from exc
            time.sleep(0.5 * (attempt + 1))
    raise SECDataError("SEC filing document is temporarily unavailable.")
