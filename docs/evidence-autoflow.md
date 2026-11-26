# Saved evidence auto observations

The existing Content entry can supply mechanical observations to QRP's
existing five-stage receipt chain. This removes manual JSON handoffs for a
saved-evidence review run. ARW still owns evidence quality/gap suggestions,
WCF owns extraction, and Content owns candidate projection and recovery.

From the workspace root:

```powershell
python -B -X utf8 content-studio-poc/scripts/capture_research_candidate.py --topic topic.json --captures captures.json --output-dir new-output --auto-observations
```

Use the existing topic/capture contracts documented in
`content-studio-poc/docs/capture-research-candidate.md`. This opt-in mode requires
1-8 inventoried saved captures. Topic budgets remain capped by the existing QRP
normalizer: at most two rounds, eight sources and three reads per round.
The automatic strategy reads one initial source and up to three follow-up
sources, subject to the smaller configured budget. It does not search or fetch
additional URLs. No observations or prepared claims are required as input.
Topic/index JSON files are capped at 64 KiB, and each inventoried capture at
20 MiB before validation; capture hashes are streamed. Initial and cumulative
capture-byte budget exhaustion terminate with an incomplete review bundle.

Profile `question-passage-observations.v2` uses QRP's existing 280-character
windows (240-character stride) and ARW BM25 to rank passages against the topic
question. Sources follow their best matching passage, with stable source ID and
offset tie-breaks. Ranking uses normalized tokens; quotations are exact original
Unicode slices. English uses ARW tokenization; Chinese uses installed jieba
dictionary segmentation with HMM disabled. Missing jieba fails explicitly;
this entry does not install or download it.

At most 8 MiB of capture bytes, 131072 body characters and 512 windows per source
are scanned. Each source contributes at most two nonoverlapping windows,
extended by up to 80 characters on each side within the same paragraph.
Paragraph ID, original `[start,end)` Unicode codepoint offsets, input capture
hash, body hash, imported capture hash and exact quotation travel together.
Repeated paragraphs retain distinct positions. Full/partial/unknown capture
completeness and left/right window truncation are separate fields. Neither a
complete capture nor a negation token's presence/absence proves a fact.

The lexical gate requires at least min(2, query-term count) distinct terms and
at least 50% query coverage; zero or over 32 terms abstains. BM25 only orders
candidates; its value is not confidence. Same-keyword topics, synonyms,
negation, contradictions and conditions outside a window need review.
No matches or weak overlap returns top-level `insufficient_evidence` plus a
specific `retrieval_summary.abstention_reason`; exhausted bounds return
`budget_exhausted`. There is no first-source fallback. These reasons describe
bounded lexical search, not a semantic judgment that a source is irrelevant.

ARW receives selected quotations as partial, zero-confidence review claims.
Its gap IDs bind follow-up imports to the original question without claiming
semantic decomposition. All gaps remain open. Evidence analysis labels matches
`retrieval_candidate`, with semantic support unassessed. Model-dependent
semantic analysis is `not_run`, and `model_called` is false.
Machine-readable source quality/freshness stay `unknown`; the synthetic marker
and saved-capture provenance survive in the review bundle. A separate
`usable_as_unverified_excerpt` flag means only that the exact quotation exists
in the recorded body. It does not set `usable_as_cited_source` or source fact.

The result includes `review_bundle` and `review_markdown` beside the existing
candidate paths. `research_complete` is always false for this mechanical mode;
CLI exit 0 means a candidate was produced, not that research is complete.
No qualifying initial passage or a one-round limit produces a review bundle with no
candidate (exit 2). No unverified text becomes a source fact or publication.

Stopping records distinguish an exhausted source/round budget, an inventory
with no remaining URL, and no mechanical evidence gain after a follow-up.
`followup_captures` records whether additional acquisition actually ran.
QRP compares full body hashes, so identical introductory prefixes do not
establish full-document duplication. Mirrored full bodies retain the earliest
acquisition round and cannot inflate evidence progress.

Resume the identical command and output directory. Original topic/index/capture
hashes, observation basis hashes, stage receipts and candidate hashes remain
binding. Interrupted saved imports consume their budget only once; completed
native imports/exports and candidates are reused. A failure after candidate
creation can resume to finish the review bundle. Changed inputs require a new
output directory. V1 `saved-excerpt-observations.v1` outputs are immutable:
use a new directory for v2; in-place migration is rejected before stage resume.
A previously completed manual observation stage is rejected
in auto mode to avoid relabeling historical semantic work as unexecuted.
Unknown acquisition outcomes remain blocked; the adapter never falls back to
network or automatically replays them.

This reuses the existing scheduler and Content argument routing. V2 edits only
research-owned modules; the default manual mode and its original contracts
remain available. Dependencies are supplied by the
existing Content/QRP/ARW environment. No dependencies are installed by this entry.

Verification: `tests/test_passage_retrieval.py`, `tests/test_evidence_autoflow.py`
plus the existing topic-driven, capture-entry and saved-candidate tests.
Synthetic exercises verify flow, provenance and recovery, not factual quality or
real user adoption.
