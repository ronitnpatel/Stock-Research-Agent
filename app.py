"""SEC-backed company research brief with deterministic financial metrics."""
from __future__ import annotations
import os
from datetime import date
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from stock_research.filings import (SECDataError, fetch_company_facts, fetch_filing_document,
                                    fetch_recent_risk_filings, resolve_ticker)
from stock_research.comparison import build_comparison_rows
from stock_research.metrics import build_metrics
from stock_research.providers import (configured_model_name, create_configured_provider,
                                      provider_key_configured)
from stock_research.risks import collect_filing_passages
from stock_research.workflow_agent import ResearchCoordinator, WorkflowResult

# Resolve settings beside this file so launch location does not change configuration lookup.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
st.set_page_config(page_title="OpenBrief · Stock Research", page_icon="◈", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background: #f6f7f4; }
.hero { padding: 1.3rem 0 1rem; border-bottom: 1px solid #dce2d9; margin-bottom: 1.4rem; }
.eyebrow { color: #46795f; font-family: 'DM Mono', monospace; font-size: .78rem; letter-spacing: .12em; }
.hero h1 { font-size: 2.3rem; letter-spacing: -.05em; margin: .35rem 0; color: #17271f; }
.hero p { color: #536158; max-width: 680px; }
.disclaimer { background: #edf2eb; border-left: 3px solid #46795f; padding: .8rem 1rem; color: #33443a; font-size: .9rem; }
</style>
<div class="hero"><div class="eyebrow">OPENBRIEF · PUBLIC FILINGS RESEARCH</div>
<h1>A clearer view of the business.</h1>
<p>Evidence-linked company research grounded in SEC filings, with calculations you can inspect.</p></div>
<div class="disclaimer">This tool does not provide personalized investment advice, make buy/sell recommendations, or execute trades. Verify important information against the linked filings.</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.subheader("Research settings")
    st.caption("Public SEC data is available without a paid data API. An SEC User-Agent is required.")
    st.text_input("Ticker", value="AAPL", key="ticker", max_chars=10)
    st.text_input("Peer tickers (optional)", value="", key="peer_tickers", max_chars=40,
                  help="Enter up to 3 comma-separated tickers for the same business or industry.")
    run = st.button("Build research brief", type="primary", use_container_width=True)
    st.divider()
    st.caption("Language model")
    st.write("AI report provider · account and API key required")
    st.caption(f"Model: `{configured_model_name()}`")
    st.caption("Provider key: configured" if provider_key_configured() else "Provider key: not detected")
    if not provider_key_configured():
        st.caption("After editing `.env`, restart Streamlit to reload settings.")
    st.caption("The coordinator makes up to 5 sequential model requests per run; skipped agents use no request. Check provider account limits and costs. No automatic provider switching.")

if run:
    ticker = st.session_state.ticker.strip().upper()
    if not ticker or not ticker.isalnum():
        st.error("Enter a valid ticker using letters and numbers.")
        st.stop()
    if not os.getenv("SEC_USER_AGENT"):
        st.error("Set SEC_USER_AGENT in your environment or .env file. Use a descriptive app name and contact email.")
        st.stop()
    # Validate user-supplied symbols before making any optional peer-data requests.
    peer_tickers = [value.strip().upper() for value in st.session_state.peer_tickers.split(",") if value.strip()]
    if len(peer_tickers) > 3 or any(not value.isalnum() for value in peer_tickers):
        st.error("Enter up to 3 peer tickers using letters and numbers, separated by commas.")
        st.stop()
    peer_tickers = list(dict.fromkeys(value for value in peer_tickers if value != ticker))
    has_provider_key = provider_key_configured()
    # Collect public filing evidence first; the report workflow receives only this bounded context.
    with st.status(f"Retrieving SEC facts for {ticker}…", expanded=True) as status:
        try:
            company = resolve_ticker(ticker)
            st.write(f"Found {company['name']} · CIK {company['cik']:010d}")
            facts = fetch_company_facts(company["cik"])
            metrics = build_metrics(facts, company["cik"])
            status.update(label="SEC facts ready", state="complete")
        except SECDataError as exc:
            status.update(label="SEC data unavailable", state="error")
            st.error(str(exc))
            st.stop()

    risk_passages, filing_failures = [], []
    with st.status("Reviewing recent SEC filing passages…", expanded=True) as status:
        try:
            recent_filings = fetch_recent_risk_filings(company["cik"])
            st.write(f"Found {len(recent_filings)} recent 10-K, 10-Q, or 8-K filings.")
            risk_passages, filing_failures = collect_filing_passages(recent_filings, fetch_filing_document)
            status.update(label="Filing passage review ready", state="complete")
        except SECDataError as exc:
            status.update(label="Recent filing review unavailable", state="error")
            st.warning(str(exc))

    st.header(f"{company['name']} · {ticker}")
    st.caption("Source: SEC Company Facts API · Fiscal-year observations below · Amounts in USD")
    cols = st.columns(4)
    for col, key, label, fmt in zip(cols, ("revenue", "gross_margin", "operating_cash_flow", "long_term_debt"),
                                    ("Revenue", "Gross margin", "Operating cash flow", "Long-term debt"),
                                    ("money", "percent", "money", "money")):
        series = metrics.get(key, [])
        if series:
            value = series[-1]["value"]
            display = f"${value / 1e9:,.1f}B" if fmt == "money" else f"{value:.1f}%"
            col.metric(label, display, help=f"FY {series[-1]['year']} · SEC filing linked below")
        else:
            col.metric(label, "Unavailable")

    st.subheader("Calculated financial trends")
    for key, label in (("revenue", "Revenue (USD)"), ("gross_margin", "Gross margin (%)"),
                       ("operating_cash_flow", "Operating cash flow (USD)"), ("long_term_debt", "Long-term debt (USD)")):
        series = metrics.get(key, [])
        if series:
            with st.expander(label):
                for item in series:
                    amount = f"${item['value']:,.0f}" if key != "gross_margin" else f"{item['value']:.1f}%"
                    st.markdown(f"**FY {item['year']}** — {amount} · [{item['form']} filed {item['filed']}]({item['url']}) · {item['source_tag']}")
        else:
            st.info(f"{label}: SEC did not return a usable annual observation.")

    st.subheader("Peer comparison")
    st.caption("User-selected comparators; the app does not verify industry similarity. Same SEC XBRL definitions and code-based calculations; fiscal years and filing dates can differ.")
    peer_records = [{"ticker": ticker, "name": company["name"], "metrics": metrics}]
    peer_errors = []
    if peer_tickers:
        with st.status("Retrieving peer company facts…", expanded=False) as status:
            # Process a small peer list sequentially to limit SEC request frequency.
            for peer_ticker in peer_tickers:
                try:
                    peer = resolve_ticker(peer_ticker)
                    peer_facts = fetch_company_facts(peer["cik"])
                    peer_records.append({"ticker": peer_ticker, "name": peer["name"],
                                         "metrics": build_metrics(peer_facts, peer["cik"])})
                except SECDataError as exc:
                    peer_errors.append((peer_ticker, str(exc)))
            status.update(label="Peer data ready", state="complete")

    workflow_result: WorkflowResult | None = None
    workflow_error = False
    if has_provider_key:
        with st.status("Coordinator starting bounded research workflow…", expanded=True) as status:
            def on_agent_step(step):
                suffix = f" · {step.total_tokens} tokens" if step.total_tokens is not None else ""
                st.write(f"{step.agent}: {step.status}{suffix}")

            try:
                provider = create_configured_provider()
                workflow_result = ResearchCoordinator(provider, on_step=on_agent_step).run(
                    {"ticker": ticker, "company": company["name"], "metrics": metrics,
                     "risk_passages": risk_passages, "peers": peer_records, "as_of": date.today().isoformat()})
                status.update(label="Research workflow finished", state="complete")
            except Exception:
                workflow_error = True
                status.update(label="Could not start the research workflow", state="error")
                st.error("Could not initialize the configured model provider. Check the key and model settings.")
    if peer_errors:
        for failed_ticker, error in peer_errors:
            st.warning(f"{failed_ticker}: {error}")
    if len(peer_records) == 1:
        st.info("Add one to three peer tickers in the sidebar to compare them with the selected company.")
    comparison_rows, comparison_sources = build_comparison_rows(peer_records)
    st.dataframe(comparison_rows, hide_index=True, use_container_width=True)
    if comparison_sources:
        with st.expander("Metric sources and fiscal periods"):
            for source in comparison_sources:
                st.markdown(f"**{source['ticker']} · {source['metric']} FY {source['year']}** — 10-K/20-F/40-F filed {source['filed']} · `{source['source_tag']}` · [SEC filing]({source['url']})")

    st.subheader("Consolidated research brief")
    if workflow_result and workflow_result.report:
        st.markdown(workflow_result.report)
        if workflow_result.citation_warnings:
            st.warning("Citation check found formatting issues. Review the evidence index before relying on claims.")
            with st.expander("Citation check details"):
                for warning in workflow_result.citation_warnings:
                    st.write(f"- {warning}")
        with st.expander("Evidence index — report citation IDs"):
            for item in workflow_result.evidence:
                if item["kind"] == "SEC calculated metric":
                    detail = f"{item['ticker']} · {item['metric']} FY {item['year']} · {item['value']:,.2f} · {item['form']} filed {item['filed']} · {item['source_tag']}"
                elif item["kind"] == "SEC filing excerpt":
                    detail = f"{item['ticker']} · {item['form']} filed {item['filed']} · {item['section']}"
                else:
                    detail = f"{item['ticker']} · {item['metric']} FY {item['year']} · {item['value']:,.2f} · {item['form']} filed {item['filed']} · {item['source_tag']}"
                st.markdown(f"**[{item['id']}]** {detail} · [SEC source]({item['url']})")
        with st.expander("Specialist notes and skeptic review"):
            for agent, note in workflow_result.specialist_notes.items():
                st.markdown(f"**{agent}**")
                st.markdown(note)
        with st.expander("Workflow trace and usage"):
            total_tokens = sum(step.total_tokens or 0 for step in workflow_result.steps)
            elapsed = sum(step.elapsed_seconds for step in workflow_result.steps)
            reported_calls = sum(step.status in {"complete", "failed"} for step in workflow_result.steps)
            st.caption(f"{reported_calls} model requests · {total_tokens:,} reported tokens · {elapsed:.1f}s cumulative agent time")
            for step in workflow_result.steps:
                usage = f" · {step.total_tokens} tokens" if step.total_tokens is not None else " · usage unavailable"
                duration = f" · {step.elapsed_seconds:.1f}s" if step.elapsed_seconds else ""
                note = f" — {step.note}" if step.note else ""
                st.write(f"**{step.agent}:** {step.status}{duration}{usage}{note}")
        st.caption("Citation checks verify known evidence IDs are present; they do not prove that a cited passage supports its claim. Review the linked sources.")
    elif workflow_result:
        st.error("The coordinator ran, but the Report agent did not return a consolidated brief. Expand the workflow status above to see the failed step and retry after checking provider access.")
    elif workflow_error:
        st.warning("The research workflow could not start. Check the provider key and model configuration, then run the brief again.")
    else:
        st.warning("Add the provider API key in `.env` to enable the specialist workflow and consolidated report. SEC metrics, peer comparisons, and filing passages remain available without the model.")

    st.subheader("Risks & events review")
    st.caption("Keyword-selected candidate excerpts from recent SEC filings; this is not a complete materiality or legal review.")
    if filing_failures:
        st.warning(f"Could not retrieve {len(filing_failures)} filing document(s); remaining filings are still shown.")
    if not risk_passages:
        st.info("No candidate excerpts were extracted from the selected recent filings. This does not mean the company has no material risks or events.")
    else:
        for passage in risk_passages:
            label = f"[{passage['id']}] {passage['section']} · {passage['form']} filed {passage['filed']}"
            with st.expander(label):
                if passage.get("items"):
                    st.caption(f"SEC filing item(s): {passage['items']}")
                st.write(f"**{passage['filing_title']}**")
                st.markdown(f"> {passage['text']}")
                st.markdown(f"[Open source filing]({passage['url']})")
        if not has_provider_key:
            st.caption("Set the provider API key in `.env` to enable the coordinated agents and consolidated report. The cited filing excerpts remain available without the model.")
else:
    st.markdown("### Start with a ticker")
    st.write("Enter a ticker to retrieve annual SEC company facts, calculate key figures deterministically, and build a coordinated report with source-linked specialist reviews.")
    st.markdown("**Current scope:** SEC financials, risk/event excerpts, user-selected peer comparison, and an optional coordinated specialist workflow with skeptic review and a consolidated report.")
