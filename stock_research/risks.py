"""Extract source passages that may merit a risk or material-event review."""
from __future__ import annotations
from html.parser import HTMLParser
import re
from .filings import SECDataError


class _TextExtractor(HTMLParser):
    BLOCKS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td"}
    IGNORED = {"script", "style", "ix:header"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORED:
            self.ignored += 1
        if not self.ignored and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.IGNORED and self.ignored:
            self.ignored -= 1
        if not self.ignored and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        # Discard scripts and style text; filing content remains data, never executable instructions.
        if not self.ignored:
            self.parts.append(data)


RISK_TERMS = (
    "risk factor", "may adversely", "could adversely", "uncertain", "uncertainty", "material weakness",
    "cybersecurity", "cyber attack", "data breach", "litigation", "regulatory", "regulation", "competition",
    "supply chain", "concentration", "liquidity", "indebtedness", "debt covenant", "impairment",
    "foreign currency", "geopolitical", "climate change", "intellectual property", "going concern",
)
EVENT_TERMS = (
    "entered into", "termination", "acquisition", "merger", "restructuring", "ceo", "chief executive",
    "resignation", "appointed", "material definitive agreement", "impairment charge", "settlement",
    "recall", "investigation", "default", "bankruptcy", "cybersecurity incident", "outage",
)


def _paragraphs(document: str) -> list[str]:
    parser = _TextExtractor()
    parser.feed(document[:8 * 1024 * 1024])
    text = "".join(parser.parts)
    paragraphs = []
    for part in text.splitlines():
        clean = re.sub(r"\s+", " ", part).strip()
        if len(clean) >= 100:
            paragraphs.append(clean)
    return paragraphs


def extract_candidate_passages(document: str, form: str, max_passages: int = 3) -> list[dict]:
    """Find up to three risk/event paragraphs; selection is keyword-based, not a completeness claim."""
    terms = RISK_TERMS + (EVENT_TERMS if form == "8-K" else ())
    candidates = []
    seen = set()
    # Keyword hits are candidate evidence for reviewers, not a decision that a risk is material.
    for index, paragraph in enumerate(_paragraphs(document)):
        lowered = paragraph.casefold()
        matches = [term for term in terms if term in lowered]
        if not matches:
            continue
        normalized = re.sub(r"\W", "", lowered)
        if normalized in seen:
            continue
        seen.add(normalized)
        # Cap noisy, unusually long HTML blocks while preserving a compact literal excerpt.
        excerpt = paragraph[:1600].rstrip()
        if len(paragraph) > len(excerpt):
            excerpt = excerpt.rsplit(" ", 1)[0] + "…"
        group = "Material event candidate" if form == "8-K" else "Risk factor candidate"
        candidates.append({"section": group, "text": excerpt, "_score": len(matches), "_order": index})
    candidates.sort(key=lambda item: (-item["_score"], item["_order"]))
    return [{"section": item["section"], "text": item["text"]} for item in candidates[:max(1, min(max_passages, 5))]]


def collect_filing_passages(filings: tuple[dict, ...], fetch_document) -> list[dict]:
    """Fetch selected filing documents and attach citation metadata to candidate passages."""
    results = []
    failures = []
    for filing in filings:
        try:
            document = fetch_document(filing["url"])
        except SECDataError:
            failures.append({"form": filing["form"], "filed": filing["filed"]})
            continue
        passages = extract_candidate_passages(document, filing["form"])
        for index, passage in enumerate(passages, start=1):
            results.append({"id": f"F{len(results) + 1}", "form": filing["form"], "filed": filing["filed"],
                            "filing_title": filing.get("description") or filing["form"], "items": filing.get("items", ""),
                            "url": filing["url"], "passage_number": index, **passage})
    return results, failures
