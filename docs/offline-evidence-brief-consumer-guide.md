# Offline evidence-to-brief pack

Updated: 2026-08-31 00:36:05 +08:00 | Codex (GPT-5)

## Purpose

`run-offline-evidence-brief` is a thin, deterministic projection over QRP's
existing bounded deep loop. It does not search, fetch, call a model, start a
service, approve evidence, or publish content.

## Stable command

```powershell
research-poc run-offline-evidence-brief `
  --fixture tests\fixtures\bounded-deep-loop\deidentified-public-insurance-archive.v1.json `
  --output-root .runtime\offline-evidence-brief
```

Pass an explicit `--closure-run-id` when another tool needs a stable run
identity. Use `--resume` after a partial core or projection run.

## Artifact chain

The core run retains its five hash-linked stage receipts. A completed run then
writes these candidate-only projections under `deliverables/`:

| Artifact | Contract role |
| --- | --- |
| `research-plan.v1.json` | Bounded subquestions, budgets, and deferred work. |
| `evidence-bundle.v1.json` | Canonical `research-output.v1`; direct `evidence-bundle.v1` facade. |
| `claim-graph.v1.json` | Candidate claim/evidence edges; no graph promotion. |
| `gap-review.v1.json` | Unknowns, contradictions, integrity blockers, and stop reason. |
| `content-brief.v1.json` | Article-tagged `content-brief.v1` candidate, always draft-only. |
| `review-packet.v1.json` | Manual `review-packet.v1` handoff with no execution authority. |

`projection-receipt.v1.json` binds every artifact hash to the input SHA-256,
core manifest SHA-256, and core receipt-chain SHA-256. The root
`offline-evidence-brief.v1.json` is the pack manifest and recovery entry.

## Acceptance semantics

- A successful command proves a fresh local fixture E2E only.
- `evidence-bundle.v1.json` is valid `research-output.v1`, but its aggregate
  review state is `candidate` and its guarded final answer is `blocked`.
- Reviewed synthetic `source_fact` rows may retain their atomic verified status;
  this does not make the claim, bundle, answer, content brief, or review packet
  verified.
- ARW may validate the evidence-bundle reference. A blocked ARW receipt is the
  expected result while candidate evidence, unknowns, or contradictions remain.
- `content-brief.v1` contains only statements admitted by the bounded loop's
  reviewed source-fact rule. Unknowns and contradictions stay in the review
  packet and never become prose facts.
- `fresh_e2e_pass` never implies `real_usage_proof` or `current_online`.

## Fail-closed recovery

- Core stage receipts are recovered by the existing bounded deep loop.
- Partial projection output requires `--resume`.
- Existing projection bytes must equal the deterministic expected payload.
- Receipt, artifact, input, archive hash, citation, or path drift blocks the
  run rather than being silently regenerated.
- Source archive paths must be bounded relative references. Absolute paths and
  `..` traversal are rejected.
- Unversioned legacy fixtures are interpreted as v1 without a semantic upgrade;
  unsupported explicit versions are rejected.

## Offline fixtures

- `synthetic-readiness-question.v1.json`: bounded selection, duplicate source,
  source claim, agent inference, contradiction, and unknown.
- `synthetic-insufficient-evidence.v1.json`: no decision-grade source fact.
- `deidentified-public-insurance-archive.v1.json`: wholly synthetic/deidentified
  public-insurance education material using WCF `evidence_archive` hash/path
  field semantics. It is not real insurance advice or real-world evidence.

## Read-only ARW verification

From the ARW repository, validate the generated bundle without importing state:

```powershell
python -B -m research_workflow.cli evidence-bundle-verify `
  <run>\deliverables\evidence-bundle.v1.json `
  --schema ..\question-research-poc\schemas\research-output.v1.schema.json `
  --receipt <local-receipt.json> `
  --expected-bundle-sha256 <sha256-from-projection-receipt>
```

The expected candidate result is `status=blocked`,
`research_truth_effect=none`, `evidence_status_change=none`, and
`candidate_promoted=false`.
