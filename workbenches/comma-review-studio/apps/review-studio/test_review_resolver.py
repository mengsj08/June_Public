#!/usr/bin/env python3
"""SKL-99 deterministic evidence resolver and non-blocking placement tests."""
import json
import os
import re
import unittest

import server


def _resolve(body, raw):
    finding = server._normalize_finding(raw, raw.get("id") or "F001")
    assert finding is not None
    return server._anchor_finding(finding, body, server._rev(body), "paper.md")


def _base_finding(**overrides):
    raw = {
        "id": "F001",
        "section": "",
        "section_id": "",
        "scope_intent": "quote",
        "issue_family": "claim_scope",
        "quote_text": "placeholder",
        "issue": "Controlled issue.",
        "action": "Controlled action.",
        "priority": "P1",
        "decision": "accepted",
        "evidence_requirement": "",
        "rationale": "Synthetic resolver fixture.",
        "context_before": "",
        "context_after": "",
        "evidence_quotes": [],
        "no_quote_required": False,
    }
    raw.update(overrides)
    return raw


def _operation_action(finding):
    return server._initial_run_operations([finding])[0]["action"]


class ReviewResolverTests(unittest.TestCase):
    def test_01_unique_quote_is_quote_exact(self):
        body = "# Results\n\nThe unique efficacy sentence appears once.\n"
        finding = _resolve(body, _base_finding(
            quote_text="The unique efficacy sentence appears once."))
        self.assertEqual(finding["placement"]["scope"], "quote")
        self.assertEqual(finding["placement"]["state"], "quote_exact")
        self.assertEqual(finding["anchor_state"], "ready")
        self.assertEqual(finding["origin"]["actor_type"], "ai")
        self.assertEqual(finding["evidence"][0]["verification_state"], "verified_unique")
        self.assertEqual(finding["source_locator"]["block_index"], 1)

    def test_01b_primary_quote_not_supplemental_evidence_controls_anchor(self):
        body = (
            "# Results\n\n"
            "Primary claim sentence appears here.\n\n"
            "Supplemental table evidence appears there.\n"
        )
        finding = _resolve(body, _base_finding(
            quote_text="Primary claim sentence appears here.",
            evidence_quotes=[{
                "quote_text": "Supplemental table evidence appears there.",
                "context_before": "",
                "context_after": "",
            }],
        ))
        self.assertEqual(finding["placement"]["scope"], "quote")
        self.assertEqual(finding["placement"]["state"], "quote_exact")
        self.assertEqual(finding["source_locator"]["text_index"], body.index("Primary claim"))
        self.assertEqual(body[finding["source_locator"]["text_index"]:
                              finding["source_locator"]["text_index"] + len(finding["quote_text"])],
                         finding["quote_text"])
        self.assertEqual(len(finding["evidence_occurrences"]), 2)

    def test_02_repeated_quote_with_ai_section_but_no_context_is_not_precise(self):
        body = (
            "# Methods\n\nRepeated claim appears here.\n\n"
            "# Results\n\nRepeated claim appears here.\n"
        )
        document_map = server._build_document_map(body, server._rev(body), "paper.md")
        finding = _resolve(body, _base_finding(
            section_id=document_map["sections"][0]["id"],
            quote_text="Repeated claim appears here."))
        self.assertNotEqual(finding["anchor_state"], "ready")
        self.assertEqual(finding["placement"]["scope"], "document")
        self.assertEqual(finding["location_details"]["downgrade_reason"], "ambiguous_candidates_cross_sections")
        self.assertEqual(_operation_action(finding), "create")

    def test_03_repeated_quote_with_exact_context_is_quote_context(self):
        quote = "Shared assay phrase."
        body = (
            "# Methods\n\nFirst setup. Shared assay phrase. First tail.\n\n"
            "Second setup. Shared assay phrase.Second tail.\n"
        )
        finding = _resolve(body, _base_finding(
            quote_text=quote,
            context_before="Second setup. ",
            context_after="Second tail."))
        self.assertEqual(finding["placement"]["scope"], "quote")
        self.assertEqual(finding["placement"]["state"], "quote_context")
        self.assertEqual(finding["evidence"][0]["match_strategy"], "quote_context")
        self.assertEqual(finding["source_locator"]["section_title"], "Methods")

    def test_04_reversible_unicode_normalization_is_unique(self):
        body = '# Results\n\nThe model uses "scaled\u00a0attention" - carefully.\n'
        finding = _resolve(body, _base_finding(
            quote_text='The model uses "scaled attention" - carefully.'))
        self.assertEqual(finding["placement"]["scope"], "quote")
        self.assertEqual(finding["placement"]["state"], "quote_normalized_unique")
        self.assertTrue(finding["evidence"][0]["normalized"])

    def test_05_same_section_equivalent_candidates_fallback_to_section(self):
        body = "# Discussion\n\nRepeated limitation phrase.\n\nRepeated limitation phrase.\n"
        finding = _resolve(body, _base_finding(quote_text="Repeated limitation phrase."))
        self.assertEqual(finding["placement"]["scope"], "section")
        self.assertEqual(finding["placement"]["section_title"], "Discussion")
        self.assertEqual(finding["location_details"]["downgrade_reason"], "all_candidates_same_section")
        self.assertEqual(finding["location_details"]["user_positioning_actions"], 0)
        self.assertEqual(_operation_action(finding), "create")

    def test_06_cross_section_repeated_quote_fallback_to_document(self):
        body = (
            "# Introduction\n\nTemplate phrase repeats.\n\n"
            "# Conclusion\n\nTemplate phrase repeats.\n"
        )
        finding = _resolve(body, _base_finding(
            issue_family="template_repetition",
            quote_text="Template phrase repeats."))
        self.assertEqual(finding["placement"]["scope"], "document")
        self.assertEqual(finding["placement"]["state"], "document_pattern")
        self.assertEqual(len(finding["placement"]["affected_section_ids"]), 2)
        self.assertEqual(finding["evidence_summary"]["verified_occurrence_count"], 2)

    def test_07_missing_quote_enters_evidence_unverified_not_blocked(self):
        body = "# Results\n\nActual result sentence.\n"
        finding = _resolve(body, _base_finding(quote_text="Invented result sentence."))
        operation = server._initial_run_operations([finding])[0]
        self.assertEqual(finding["placement"]["scope"], "evidence_unverified")
        self.assertEqual(finding["evidence"][0]["verification_state"], "unverified_missing")
        self.assertEqual(operation["action"], "keep")
        self.assertEqual(operation["reason"], "evidence_unverified")

    def test_08_explicit_structure_finding_needs_no_quote(self):
        body = "# Introduction\n\nSetup.\n\n# Conclusion\n\nWrap-up.\n"
        finding = _resolve(body, _base_finding(
            scope_intent="document",
            issue_family="structure",
            quote_text="",
            evidence_quotes=[],
            no_quote_required=True))
        self.assertEqual(finding["placement"], {"scope": "document", "state": "no_quote_required"})
        self.assertEqual(finding["evidence"][0]["verification_state"], "no_quote_required")
        self.assertEqual(_operation_action(finding), "create")

    def test_09_fallback_heading_false_positive_wrong_section_count_is_zero(self):
        body = (
            "Abstract\n\n"
            "The abstract sentence is controlled.\n\n"
            "This sentence mentions Introduction but is not a heading.\n\n"
            "1 Introduction\n\n"
            "The introduction sentence is controlled.\n"
        )
        document_map = server._build_document_map(body, server._rev(body), "paper.md")
        titles = [section["title"] for section in document_map["sections"]]
        self.assertEqual(titles, ["Abstract", "1 Introduction"])
        finding = _resolve(body, _base_finding(
            quote_text="The introduction sentence is controlled."))
        wrong_section = int(finding["placement"].get("section_title") != "1 Introduction")
        self.assertEqual(wrong_section, 0)
        self.assertEqual(finding["source_locator"]["section_title"], "1 Introduction")

    def test_real_arxiv_attention_replay_distribution(self):
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "data", "arxiv-1706.03762v7", "converted",
            "attention-is-all-you-need-source.md",
        )
        if not os.path.exists(path):
            self.skipTest("private arXiv replay Markdown is not present")
        with open(path, encoding="utf-8") as handle:
            body = handle.read()
        sentence_candidates = [
            item.strip() for item in re.findall(r"[^.\n]{60,240}\.", body)
            if body.count(item.strip()) == 1 and not item.strip().startswith("|")
        ]
        self.assertTrue(sentence_candidates)
        unique_sentence = sentence_candidates[0]
        repeated_phrase = next(
            phrase for phrase in (
                "self-attention", "multi-head attention", "Multi-Head Attention",
                "scaled dot-product attention", "Scaled Dot-Product Attention",
                "positional encodings", "attention",
            )
            if body.count(phrase) > 1
        )
        normalized_sentence = next(
            item for item in sentence_candidates
            if " " in item and body.count(item.replace(" ", "\u00a0", 1)) == 0
        )
        findings = [
            _resolve(body, _base_finding(id="F-REAL-1", quote_text=unique_sentence)),
            _resolve(body, _base_finding(
                id="F-REAL-2",
                issue_family="template_repetition",
                quote_text=repeated_phrase)),
            _resolve(body, _base_finding(
                id="F-REAL-3",
                quote_text=normalized_sentence.replace(" ", "\u00a0", 1))),
        ]
        distribution = {}
        for finding in findings:
            scope = finding["placement"]["scope"]
            distribution[scope] = distribution.get(scope, 0) + 1
        print("REAL_REPLAY_PLACEMENT_DISTRIBUTION " + json.dumps(
            distribution, ensure_ascii=False, sort_keys=True))
        self.assertGreaterEqual(distribution.get("quote", 0), 2)
        self.assertTrue(distribution.get("document", 0) or distribution.get("section", 0))
        self.assertEqual(sum(distribution.values()), 3)


if __name__ == "__main__":
    unittest.main()
