# Stock Research Agent

## Project overview

The Stock Research Agent turns public company filings into a source-linked stock research brief. Its multi-agent AI workflow assigns financial trends, risks, peer comparisons, skeptic review, and final synthesis to specialized agents. Code calculates financial metrics, while evidence IDs help readers trace claims to SEC filings.

Enter a ticker to retrieve SEC Company Facts and show up to five annual observations for revenue, gross margin, operating cash flow, and long-term debt. Each observation links to the SEC filing and identifies its filing date and XBRL tag. Gross margin and debt totals are calculated deterministically. Missing metrics are reported as unavailable.

The app reviews up to five recent 10-K, 10-Q, or 8-K filings. It selects up to three risk/event candidate excerpts per filing using a small keyword list and shows each with its filing date and direct source link. This is an assistive pass, not a comprehensive risk extraction or materiality determination.

Optionally enter up to three peer tickers in the sidebar. The app applies the same SEC XBRL tags and deterministic metric calculations to each company and shows the latest available fiscal-year values with source filings.

## Agent workflow

**Build research brief** runs these agents in order through a bounded LangGraph workflow. A role is skipped when its required evidence is unavailable. If one model request fails, the workflow records the failure and continues to later steps where possible.

1. **Financials agent** reviews calculated revenue, gross margin, operating cash flow, and long-term debt trends. It uses supplied values without recalculating them and notes missing measures.
2. **Risks & events agent** reviews selected excerpts from recent SEC filings for risk themes and possible material events. 
3. **Industry comparison agent** compares the company only with user-selected peer data. It describes observed differences without inferring causes, and is skipped when no peer tickers are selected.
4. **Skeptic agent** checks the specialist notes against the evidence ledger for unsupported claims, conflicting figures, stale evidence, and overconfident wording. It also receives any skipped or failed status notes.
5. **Report agent** combines the evidence and specialist notes into the consolidated brief, with the required report sections and evidence IDs attached to factual claims.

The workflow makes up to five model requests per run. Every evidence item receives a per-run ID: `D#` for calculated SEC metrics, `F#` for filing excerpts, and `P#` for peer metrics. A deterministic citation-presence check flags missing or unknown IDs; it does not prove that a cited source supports a claim. The report view includes an evidence index, specialist notes, skeptic review, workflow trace, latency, and returned token usage.

## Technical details

- **Application:** Python and Streamlit. SEC retrieval and deterministic tables remain available without a model API key.
- **Orchestration:** LangGraph manages the sequential workflow and shared state. Each model request has a 30-second timeout, one bounded SDK retry, and an 800-token completion cap.
- **Model provider:** `stock_research/providers.py` defines the provider interface and currently implements Groq.
- **Evidence handling:** Numeric facts and selected filing excerpts are sent as JSON and treated as untrusted data. The complete filing is not sent. The model has no tools or permission to execute trades.
- **Data limits:** The app shows up to five annual observations and reviews up to five recent filings, selecting up to three candidate excerpts per filing. Peer tickers are user-selected; industry similarity and fiscal-period comparability are not verified. SEC responses are kept in process memory; persistent caching is not implemented.
- **Source:** SEC company facts and filings are retrieved using the [EDGAR API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

Key files:

- `stock_research/filings.py`: bounded SEC requests, ticker resolution, Company Facts, and recent filing retrieval.
- `stock_research/risks.py`: bounded HTML-to-text extraction and candidate passage selection.
- `stock_research/comparison.py`: peer metric formatting and citation metadata.
- `stock_research/workflow_agent.py`: LangGraph workflow, agent roles, evidence ledger, and citation audit.
- `stock_research/metrics.py`: deterministic metric selection and calculations.
- `stock_research/providers.py`: model-provider interface and configured implementation.
- `app.py`: Streamlit interface and partial-workflow handling.

## Checks

Tests use Python's standard `unittest` library and fixed synthetic fixtures, so they are repeatable. They verify annual duration filtering, gross-margin arithmetic, debt addition, filing links, peer formatting, risk passage extraction, coordinator order and skips, failure handling, and citation-ID auditing.
