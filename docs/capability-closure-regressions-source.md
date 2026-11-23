# QRP Gateway Capability Closure Regression Test Source Guide

## 1. Purpose and Scope
This document specifies the regression source contracts for the five test methods in the Question Research POC (QRP) capability closure suite under the Apache-2.0 license. The source declares fail-closed truth-field, receipt-reuse and external-schema assertions. No external schema or runtime is bundled, and the five test functions were not executed.

## 2. Five Test Method Contracts
The five unchanged original test bodies express these expected contracts:
- **Fail-Closed Consumer Status**: `test_closure_represents_unavailable_arw_as_fresh_fail_closed` asserts that unavailable model assistance preserves `contract_ready=True` while strictly setting `runtime_ready`, `fresh_e2e_pass`, `current_online`, and `real_usage_proof` to `False`.
- **Idempotency and Truthfulness**: `test_synthetic_capability_closure_is_idempotent_and_truthful` compares repeated synthetic receipt bytes and flags; this is an intended fixture-specific idempotency check, not proof of all runtime determinism.
- **Receipt Reuse on Resume**: `test_closure_resume_rebuilds_only_the_missing_final_artifact` expects the resume path to reuse saved receipts without starting a new loopback server after the initial fixture run.
- **Negative Invariant Rejection**: `test_closure_semantics_fail_closed_on_online_claim_and_hash_drift` raises `ValueError` when current_online is mutated to True in the synthetic closure or when stage receipt hashes drift.
- **CLI Command Exposure**: `test_cli_exposes_one_stable_closure_command` validates argument parser construction for `gateway-capability-closure` without invoking runtime execution.

## 3. Schema Resolution and Verification Limits
- **Explicit Schema Binding**: Canonical schema path resolution relies exclusively on `CLOSURE_RUN_V1_SCHEMA`. If unset or missing, the helper invokes `pytest.skip`; skipping indicates absent schema prerequisites, not verified closure.
- **Execution Boundaries**: The module imports `research_workflow.model_gateway` at top level, requiring compatible ARW installations for collection. All 5 test methods remain strictly **UNEXECUTED (NOT RUN)**. Owner verified that the final source differs only in the approved schema-path helper, with all other top-level AST and five tests in original order unchanged, and non-executing compile passed. Three independently executed in-memory helper controls passed for explicit-existing, explicit-missing and unset environment values. FakePath/skip substitutes were used; no actual schema file, filesystem probe, pytest suite or external dependency module was executed.

The only helper change removes the developer-home fallback. An unset value or selected non-file still follows the original pytest.skip path; an expected skip control is not a passing capability closure. No canonical schema or snapshot equivalence was established or invented. Full tests can require actual ARW/Gateway contracts and loopback HTTP; the public offline guard remains unchanged and has not been bypassed. Parser assertions do not execute the CLI handler, and synthetic receipt truth fields do not prove real usage, current online state, research evidence or publication permission.
