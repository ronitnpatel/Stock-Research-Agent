import unittest
from stock_research.workflow_agent import ResearchCoordinator, audit_report_citations, build_evidence


def base_context(with_risk=True, with_peer=True):
    point = {"year": 2025, "value": 100.0, "filed": "2025-03-01", "form": "10-K",
             "source_tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
             "url": "https://www.sec.gov/Archives/edgar/data/1/filing.txt"}
    risk = {"id": "F1", "form": "10-K", "filed": "2025-03-01", "section": "Risk factor candidate",
            "url": "https://www.sec.gov/Archives/edgar/data/1/risk.htm", "text": "Competition may adversely affect revenue."}
    peer = {"ticker": "BBB", "metrics": {"revenue": [{**point, "year": 2024, "value": 80.0}]}}
    return {"ticker": "AAA", "company": "Example Corp", "metrics": {"revenue": [point]},
            "risk_passages": [risk] if with_risk else [], "peers": [{"ticker": "AAA", "metrics": {"revenue": [point]}}] + ([peer] if with_peer else [])}


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []
        self.last_usage = {"total_tokens": 12}

    def complete(self, prompt):
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def valid_report():
    return """## Facts
- [D1] Revenue was 100. [D1]
## Analysis
- [D1] The recorded amount is a historical observation.
## Risks & events
- [F1] Competition is identified as a candidate risk.
## Industry comparison
- [P1] The selected peer reported a lower value in a different fiscal year.
## Skeptic review
- [P1] Peer fiscal years differ.
## Open questions
- What explains the peer's different reporting period?
## Limitations
- [F1] The excerpt selection is not comprehensive.
This tool does not provide personalized investment advice or execute trades."""


class WorkflowTests(unittest.TestCase):
    def test_coordinator_runs_specialists_skeptic_and_report_in_order(self):
        provider = FakeProvider([
            "- [D1] Revenue was 100.",
            "- [F1] Competition is a candidate risk.",
            "- [P1] Peer revenue was 80.",
            "- [D1] No contradiction found in the supplied financial point.",
            valid_report(),
        ])
        result = ResearchCoordinator(provider).run(base_context())
        self.assertEqual(len(provider.prompts), 5)
        self.assertIn("Financials agent", provider.prompts[0])
        self.assertIn("Risks & events agent", provider.prompts[1])
        self.assertIn("Industry comparison agent", provider.prompts[2])
        self.assertIn("Skeptic agent", provider.prompts[3])
        self.assertIn("Report agent", provider.prompts[4])
        self.assertEqual([step.status for step in result.steps], ["complete"] * 5)
        self.assertEqual(result.report, valid_report())
        self.assertEqual(result.citation_warnings, [])

    def test_agents_without_data_are_skipped_without_model_calls(self):
        context = base_context(with_risk=False, with_peer=False)
        provider = FakeProvider(["- [D1] Financial summary.", "- [D1] Skeptic note.", valid_report()])
        result = ResearchCoordinator(provider).run(context)
        self.assertEqual(len(provider.prompts), 3)
        self.assertEqual(result.steps[1].status, "skipped")
        self.assertEqual(result.steps[2].status, "skipped")
        self.assertEqual(result.steps[2].agent, "Industry comparison agent")

    def test_provider_failure_is_recorded_and_later_agents_continue(self):
        provider = FakeProvider([RuntimeError("private detail should not leak"), "- [F1] Risk note.",
                                 "- [P1] Peer note.", "- [F1] Skeptic note.", valid_report()])
        result = ResearchCoordinator(provider).run(base_context())
        self.assertEqual(result.steps[0].status, "failed")
        self.assertNotIn("private detail", result.steps[0].note)
        self.assertEqual(result.report, valid_report())

    def test_evidence_ids_are_stable_and_unknown_or_missing_report_ids_are_flagged(self):
        evidence = build_evidence(base_context())
        self.assertIn("D1", [item["id"] for item in evidence])
        self.assertIn("F1", [item["id"] for item in evidence])
        self.assertIn("P1", [item["id"] for item in evidence])
        warnings = audit_report_citations("## Facts\n- [Z9] Unsupported.\n- No evidence supplied.", evidence)
        self.assertTrue(any("unknown ID" in warning for warning in warnings))
        self.assertTrue(any("no evidence ID" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
