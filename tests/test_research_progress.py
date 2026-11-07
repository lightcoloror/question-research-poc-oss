"""Offline regressions for evidence-based progress, not fact verification."""
from question_research_poc.research_progress import (
    canonical_reference, evidence_snapshot, normalize_topic, progress_delta,
)


def snapshot(*, suffix="", text="An exact quotation", relation="supports", inferred=False):
    return evidence_snapshot(
        [{"source_id": "s" + suffix, "content_sha256": "same-body"}],
        [{"claim_id": "c" + suffix, "text": "A claim"}],
        [{"source_id": "s" + suffix, "claim_id": "c" + suffix,
          "text": text, "relation": relation,
          "evidence_type": "agent_inference" if inferred else "quote"}],
    )


def test_reissued_identifiers_do_not_create_progress():
    result = progress_delta(snapshot(), snapshot(suffix="-new"))
    assert result["new_unique_evidence"] == 0
    assert result["new_unique_sources"] == 0
    assert not result["meaningful_gain"]


def test_new_exact_evidence_is_progress_not_verification():
    result = progress_delta(snapshot(), snapshot(text="Another exact quotation"))
    assert result["meaningful_gain"]
    assert result["new_unique_evidence"] == 1
    assert result["interpretation"].endswith("not_fact_verification")


def test_agent_inference_does_not_count_as_evidence():
    assert snapshot(inferred=True)["evidence"] == set()


def test_conflict_changes_are_reported_separately():
    before = snapshot()
    after = {**before, "conflicts": {"a claim"}}
    result = progress_delta(before, after)
    assert result["conflicts_added"] == 1
    assert result["meaningful_gain"]
    assert progress_delta(after, before)["conflicts_removed"] == 1


def test_url_normalization_preserves_meaningful_case_and_query():
    assert canonical_reference("https://Example.org/Case?q=Value&utm_source=x#part") == "https://example.org/Case?q=Value"
    assert canonical_reference("https://example.org/Case") != canonical_reference("https://example.org/case")
    assert normalize_topic("  A   Question? ") == "a question"
