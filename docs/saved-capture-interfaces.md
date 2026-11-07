# Saved-capture and observation interfaces

This increment reuses the existing bounded research receipt chain. It adds the
current working implementation of saved WCF capture admission, stage-bound
observations, source/claim/evidence deduplication and lexical passage location.
The existing offline evidence-brief projection remains available.

Use the `topic` extra for the optional file lock, Chinese dictionary segmentation,
resource observations and the already-public ARW sparse-retrieval code. The ARW
dependency is fixed to a public commit. No model weights, external source bodies,
credentials, services or personal workspaces are bundled.

- `bounded_deep_loop.run_bounded_deep_loop` accepts explicit saved capture indexes
  and stage observations. Missing saved captures cannot fall back to a network read.
- `topic_research` reuses WCF. Live reads require an explicit WCF root and bounded
  resource parameters; none were performed by this acceptance.
- `evidence_autoflow` produces mechanical excerpts, gaps and passage references
  from saved captures. Semantic analysis is not run. Lexical ordering is not
  relevance verification, truth, confidence or clinical evidence grading.
- Passage records bind original Unicode offsets, body/capture hashes and query
  context. CRLF and repeated paragraphs retain distinct original locations.
- Imported sources, interpretations and quotations remain candidate evidence.
  Local hashes and exact excerpts do not establish publisher authenticity, full
  source coverage, current applicability, reuse rights or human fact review.
- Partial imports keep their original reservations and identifiers. A changed
  source, observation or completed output blocks reuse; do not overwrite evidence.

ContentStudio consumes these APIs separately. An unselected research export is
intermediate material; a platform/format choice is never inferred from its shape.
Human fact review, author selection and publication remain outside this command.

The public edition records uncommitted working snapshots and selected CLI/splitter
symbols separately from the original Git baseline. See `CAPTURE_PROVENANCE.json`.

## Test scopes

Install the `test` extra for the public test dependencies. The consumer-backed
autoflow and passage suites additionally require ContentStudio capture modules;
they explicitly skip when that separate optional consumer is unavailable. The
cross-owner acceptance supplies the reviewed consumer and runs those tests.
Base import and installed offline/topic CLI checks do not need ContentStudio.
