import json
import hashlib
from pathlib import Path

import pytest

from question_research_poc.bounded_deep_loop import run_bounded_deep_loop
from question_research_poc.bounded_deep_loop import BoundedDeepLoopError
from question_research_poc import topic_research as topic
from question_research_poc.storage import write_json


def topic_input(tmp_path):
    path = tmp_path / 'topic.json'
    path.write_text(json.dumps({'question': 'A topic with no supplied evidence', 'audience': 'readers',
                               'budgets': {'max_depth': 2, 'max_subquestions': 3, 'max_rounds': 2,
                                           'max_sources': 8, 'max_requests': 12, 'max_text_bytes': 20971520,
                                           'request_timeout_seconds': 20, 'network_seconds': 600,
                                           'max_tokens': 14000, 'max_expansions_per_round': 3}}), encoding='utf-8')
    return path


def test_topic_only_starts_existing_receipt_chain_and_requests_acquisition(tmp_path):
    path = topic_input(tmp_path)
    result = run_bounded_deep_loop(path, tmp_path / 'runs', closure_run_id='topic-only-test')
    assert result['execution_status'] == 'awaiting_codex_observation'
    assert result['completed_stages'] == ['intake']
    assert result['resume_from'] == 'source_admission'
    assert result['observation_contract']['allowed_operation'] == 'initial_public_read'
    assert not any(key in json.loads(path.read_text()) for key in ['sources', 'claims', 'evidence', 'subquestions'])


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_stages(tmp_path, monkeypatch, blocked=False):
    """Mock WCF only; these tests are never evidence of public network execution."""
    calls = []
    def fake_read(root, url, round_index, budgets, wcf_root, max_os_threads):
        calls.append(url)
        path = root / 'captures' / f'fake-{len(calls)}.json'
        body = '' if blocked else ('First observation reveals a gap.' if round_index == 1 else 'Followup closes the gap.')
        saved = {'requested_url': url, 'final_url': url, 'status': 'failed' if blocked else 'partial',
                 'transport_ok': not blocked, 'content_ok': False, 'http_status': 200 if not blocked else None,
                 'capture_completeness': {'status': 'partial', 'access': {'status': 'not_observed'}},
                 'extracted_text': body, 'fetched_at': '2026-09-13T01:00:00Z'}
        write_json(path, saved)
        write_json(root / 'acquisition-ledger.json', {'requests': [{'url': x} for x in calls],
                   'bytes_read': len(calls) * 100, 'network_seconds': 0})
        return topic._capture_row(root, path, saved, round_index, False)
    monkeypatch.setattr(topic, '_wcf_read', fake_read)
    inp = topic_input(tmp_path)
    root = tmp_path / 'runs' / 'synthetic'
    def run(obs=None):
        return run_bounded_deep_loop(inp, tmp_path / 'runs', closure_run_id='synthetic',
                                    resume=root.exists(), observation_path=obs)
    def observe(stage, previous, **values):
        path = tmp_path / 'observation.json'
        write_json(path, {'stage': stage, 'basis_artifact_sha256': sha(root / 'artifacts' / previous), **values})
        return path
    run()
    initial = observe('source_admission', '01-intake.json', reads=[{'url': 'https://example.org/a'},
                       {'url': 'https://example.org/a?utm_source=duplicate'}])
    result = run(initial)
    return inp, root, calls, run, observe, result


@pytest.mark.parametrize('mutation,code', [('basis', 'observation_basis_drift'), ('quote', 'observation_quote_missing'),
                                         ('depth', 'topic_budget_invalid'), ('unbound', 'ungrounded_followup')])
def test_grounded_followups_fail_closed(tmp_path, monkeypatch, mutation, code):
    _, root, calls, run, observe, _ = synthetic_stages(tmp_path, monkeypatch)
    first = json.loads((root / 'artifacts/02-source_admission.json').read_text())['captures'][0]
    sub = {'subquestion_id': 'sq', 'text': 'What fills the gap?', 'depth': 2,
           'basis_source_id': first['source_id'], 'basis_quote': 'First observation reveals a gap.'}
    if mutation == 'quote': sub['basis_quote'] = 'Unobserved invented evidence'
    if mutation == 'depth': sub['depth'] = 3
    obs = observe('evidence_analysis', '02-source_admission.json', subquestions=[sub],
                  reads=[{'url': 'https://example.org/b', 'subquestion_id': 'missing' if mutation == 'unbound' else 'sq'}])
    if mutation == 'basis':
        value = json.loads(obs.read_text()); value['basis_artifact_sha256'] = '0' * 64; write_json(obs, value)
    with pytest.raises(BoundedDeepLoopError) as caught: run(obs)
    assert caught.value.code == code
    assert len(calls) == 1


@pytest.mark.parametrize('conflict', [False, True])
def test_synthetic_full_chain_deduplicates_and_reuses_without_reads(tmp_path, monkeypatch, conflict):
    from research_workflow import quality
    original_quality = quality.quality_for_report
    quality_inputs = []
    def observed_quality(report):
        quality_inputs.append(report)
        return original_quality(report)
    monkeypatch.setattr(quality, 'quality_for_report', observed_quality)
    _, root, calls, run, observe, _ = synthetic_stages(tmp_path, monkeypatch)
    first = json.loads((root / 'artifacts/02-source_admission.json').read_text())['captures'][0]
    sub = {'subquestion_id': 'sq', 'text': 'What fills the gap?', 'depth': 2,
           'basis_source_id': first['source_id'], 'basis_quote': 'First observation reveals a gap.',
           'candidate': {'problem': 'Gap', 'angle': 'Test', 'unanswered_questions': ['Real use unknown'],
                         'selection_reason': 'Synthetic evidence linkage'}}
    obs = observe('evidence_analysis', '02-source_admission.json', subquestions=[sub, dict(sub)],
                  reads=[{'url': 'https://example.org/b', 'subquestion_id': 'sq'}])
    assert run(obs)['resume_from'] == 'guarded_synthesis'
    second = json.loads((root / 'artifacts/03-evidence_analysis.json').read_text())
    assert len(second['subquestions']) == 1
    evidence = [{'source_id': first['source_id'], 'text': sub['basis_quote'], 'relation': 'supports'},
                {'source_id': second['captures'][0]['source_id'], 'text': 'Followup closes the gap.',
                 'relation': 'contradicts' if conflict else 'supports'}]
    obs = observe('guarded_synthesis', '03-evidence_analysis.json',
                  claims=[{'subquestion_id': 'sq', 'text': 'Scoped synthetic claim', 'evidence': evidence}])
    completed = run(obs)
    assert len(quality_inputs) == 1
    assert [row['quote_or_paraphrase'] for row in quality_inputs[0]['evidence']] == [row['text'] for row in evidence]
    assert all(row['verdict'] == 'partial' for row in quality_inputs[0]['claims'])
    synthesis = json.loads((root / 'artifacts/04-guarded_synthesis.json').read_text())
    weak = synthesis['arw_quality']['quality_summary']['weak_evidence']
    assert all('url_only' not in row['reasons'] for row in weak)
    assert any('short_text' in row['reasons'] for row in weak)
    assert completed['search_stop_reason'] == ('fact_conflict' if conflict else 'budget_exhausted')
    before = {p: sha(p) for p in root.rglob('*.json')}
    assert run()['reused'] is True
    assert before == {p: sha(p) for p in root.rglob('*.json')}
    assert len(calls) == 2


def test_access_blocked_stops_without_fabricated_candidates(tmp_path, monkeypatch):
    _, root, calls, _, _, result = synthetic_stages(tmp_path, monkeypatch, blocked=True)
    assert result['execution_status'] == 'complete'
    assert result['search_stop_reason'] == 'access_blocked'
    assert json.loads((root / 'artifacts/05-article_brief.json').read_text())['topic_candidates'] == []
    assert len(calls) == 1


@pytest.mark.parametrize('mutation,code', [('capture', 'topic_capture_drift'), ('ledger', 'topic_budget_ledger_drift')])
def test_resume_rejects_changed_acquisition_evidence(tmp_path, monkeypatch, mutation, code):
    _, root, calls, run, _, _ = synthetic_stages(tmp_path, monkeypatch)
    path = root / ('captures/fake-1.json' if mutation == 'capture' else 'acquisition-ledger.json')
    path.write_text('{}')
    with pytest.raises(BoundedDeepLoopError) as caught: run()
    assert caught.value.code == code
    assert len(calls) == 1


def test_unknown_request_outcome_does_not_resend(tmp_path):
    url = 'https://example.org/a'
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    write_json(tmp_path / 'captures' / (key + '.request.json'), {'status': 'reserved'})
    with pytest.raises(BoundedDeepLoopError) as caught:
        topic._wcf_read(tmp_path, url, 1, {}, None, 1)
    assert caught.value.code == 'request_outcome_unknown'
