import copy
import hashlib
import json
from pathlib import Path

import pytest

from question_research_poc.bounded_deep_loop import BoundedDeepLoopError, run_bounded_deep_loop


FIXTURE = Path(__file__).parent / 'fixtures/bounded-deep-loop/synthetic-readiness-question.v1.json'


def run(tmp_path, payload):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    result = run_bounded_deep_loop(path, tmp_path / 'runs', closure_run_id='topic-test-001')
    artifacts = {p.stem.split('-', 1)[1]: json.loads(p.read_text(encoding='utf-8'))
                 for p in (Path(result['run_dir']) / 'artifacts').glob('*.json')}
    return result, artifacts


def test_equivalent_topics_do_not_consume_budget_and_keep_claims(tmp_path):
    payload = json.loads(FIXTURE.read_text(encoding='utf-8'))
    duplicate = copy.deepcopy(payload['subquestions'][0])
    duplicate.update(subquestion_id='alias-topic', text=duplicate['text'].upper() + '  ')
    payload['subquestions'].append(duplicate)
    payload['claims'][0]['subquestion_id'] = 'alias-topic'
    _, artifacts = run(tmp_path, payload)
    assert len(artifacts['intake']['selected_subquestions']) == 3
    assert len(artifacts['intake']['subquestion_aliases']) == 1
    assert payload['claims'][0]['claim_id'] in artifacts['source_admission']['selected_claim_ids']


def test_duplicate_references_preserve_path_case_and_content_aliases(tmp_path):
    from question_research_poc.research_progress import canonical_reference
    assert canonical_reference('https://EXAMPLE.org/Doc?utm_source=x#section') == 'https://example.org/Doc'
    assert canonical_reference('https://example.org/Doc') != canonical_reference('https://example.org/doc')
    payload = json.loads(FIXTURE.read_text(encoding='utf-8'))
    original = payload['sources'][0]
    duplicate = copy.deepcopy(original)
    duplicate.update(source_id='mirror', canonical_ref='https://mirror.example/doc')
    payload['sources'].append(duplicate)
    payload['evidence'].append({**payload['evidence'][0], 'evidence_id': 'mirror-evidence', 'source_id': 'mirror'})
    _, artifacts = run(tmp_path, payload)
    assert any(x['source_id'] == 'mirror' for x in artifacts['source_admission']['duplicate_sources'])
    assert artifacts['evidence_analysis']['evidence_records'][0]['source_id'] == original['source_id']
    assert artifacts['evidence_analysis']['duplicate_evidence'][0]['evidence_id'] == 'mirror-evidence'


def test_growth_ignores_reimport_ids_but_detects_conflict_change():
    from question_research_poc.research_progress import evidence_snapshot, progress_delta
    sources = [{'source_id': 's1', 'canonical_ref': 'https://example.org/a', 'content_sha256': 'abc'}]
    claims = [{'claim_id': 'c1', 'text': 'Search supports indexed text'}]
    evidence = [{'evidence_id': 'e1', 'claim_id': 'c1', 'source_id': 's1', 'text': 'Quote',
                 'relation': 'supports', 'evidence_type': 'source_claim'}]
    before = evidence_snapshot(sources, claims, evidence)
    sources.append({**sources[0], 'source_id': 's2'})
    claims.append({**claims[0], 'claim_id': 'c2'})
    evidence.append({**evidence[0], 'evidence_id': 'e2', 'claim_id': 'c2', 'source_id': 's2'})
    repeated = evidence_snapshot(sources, claims, evidence)
    assert progress_delta(before, repeated)['meaningful_gain'] is False
    evidence.append({**evidence[0], 'evidence_id': 'e3', 'relation': 'contradicts'})
    changed = evidence_snapshot(sources, claims, evidence)
    assert progress_delta(repeated, changed)['conflicts_added'] == 1
    assert progress_delta(changed, repeated)['conflicts_removed'] == 1


def public_input(tmp_path):
    text = 'A saved search stores criteria. Search results update automatically.'
    capture = {'requested_url': 'https://example.org/doc', 'final_url': 'https://example.org/doc',
               'status': 'partial', 'transport_ok': True, 'content_ok': True,
               'fetched_at': '2026-09-12T10:00:00Z', 'extracted_text': text,
               'capture_completeness': {'status': 'partial', 'reason': 'images_not_downloaded'}}
    archive = tmp_path / 'capture.json'
    archive.write_text(json.dumps(capture), encoding='utf-8')
    return {
        'schema': 'question-research-public-archive-input.v1', 'fixture_id': 'public-test',
        'question': 'How to search?', 'audience': 'ordinary readers', 'observed_at': '2026-09-12T10:00:00Z',
        'budgets': {'max_subquestions': 3, 'max_depth': 2, 'max_sources': 8, 'max_tokens': 1000,
                    'max_expansions_per_round': 3, 'max_rounds': 2},
        'rounds_completed': 2,
        'subquestions': [{'subquestion_id': 'sq1', 'text': 'How to search?', 'depth': 1, 'gap_score': 1,
                          'candidate': {'problem': 'Cannot find saved material', 'angle': 'Save criteria',
                                        'unanswered_questions': ['Personal retrieval speed remains untested'],
                                        'selection_reason': 'Direct official feature evidence'}}],
        'sources': [{'source_id': 's1', 'title': 'Documentation', 'canonical_ref': 'https://example.org/doc',
                     'source_type': 'official_documentation', 'quality': 'good', 'review_status': 'candidate',
                     'freshness': 'current', 'content': text, 'content_sha256': hashlib.sha256(text.encode()).hexdigest(),
                     'archive_path': 'capture.json', 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                     'token_cost': 50, 'discovered_round': 1}],
        'claims': [{'claim_id': 'c1', 'subquestion_id': 'sq1', 'text': 'Saved search stores criteria',
                    'claim_origin': 'agent_interpretation_of_source'}],
        'evidence': [{'evidence_id': 'e1', 'claim_id': 'c1', 'source_id': 's1', 'evidence_type': 'source_claim',
                      'status': 'candidate', 'review_status': 'candidate', 'relation': 'supports',
                      'text': 'A saved search stores criteria.', 'discovered_round': 1}]
    }


def test_public_capture_is_cited_without_human_verified_promotion_and_stops_on_stagnation(tmp_path):
    result, artifacts = run(tmp_path, public_input(tmp_path))
    evidence = artifacts['evidence_analysis']['evidence_records'][0]
    assert evidence['usable_as_cited_source'] is True
    assert evidence['usable_as_source_fact'] is False
    assert result['search_stop_reason'] == 'no_new_evidence'
    assert artifacts['article_brief']['source_material'] == 'public_archives'
    candidate = artifacts['article_brief']['topic_candidates'][0]
    assert candidate['claim_ids'] == ['c1']
    assert candidate['source_ids'] == ['s1']
    assert candidate['coverage']['supported_claims'] == 1


@pytest.mark.parametrize('mutation,code', [('quote','public_quote_missing'), ('archive','public_archive_hash_mismatch'),
                                          ('path','public_archive_path_invalid'), ('round','fixture_budget_invalid')])
def test_public_integrity_and_budget_fail_closed(tmp_path, mutation, code):
    payload = public_input(tmp_path)
    if mutation == 'quote': payload['evidence'][0]['text'] = 'A claim not in the source'
    if mutation == 'archive': payload['sources'][0]['archive_sha256'] = '0' * 64
    if mutation == 'path': payload['sources'][0]['archive_path'] = '../outside.json'
    if mutation == 'round': payload['rounds_completed'] = 3
    with pytest.raises(BoundedDeepLoopError) as caught:
        run(tmp_path, payload)
    assert caught.value.code == code


@pytest.mark.parametrize('completeness', ['partial', 'complete_against_saved_dom'])
def test_partial_capture_requires_explicit_excerpt_scope(tmp_path, completeness):
    payload = public_input(tmp_path)
    path = tmp_path / 'capture.json'
    capture = json.loads(path.read_text(encoding='utf-8'))
    capture.update(content_ok=False, http_status=200)
    capture['capture_completeness']['status'] = completeness
    path.write_text(json.dumps(capture), encoding='utf-8')
    payload['sources'][0]['archive_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(BoundedDeepLoopError) as caught:
        run(tmp_path, payload)
    assert caught.value.code == 'public_archive_invalid'
    payload['sources'][0]['capture_scope'] = 'excerpt_only'
    _, artifacts = run(tmp_path, payload)
    source = artifacts['article_brief']['sources'][0]
    assert source['capture_content_ok'] is False
    assert source['capture_scope'] == 'excerpt_only'
    assert json.loads(path.read_text(encoding='utf-8'))['capture_completeness']['status'] == completeness
    evidence = artifacts['evidence_analysis']['evidence_records'][0]
    assert evidence['usable_as_source_fact'] is False


@pytest.mark.parametrize('mutation', ['unknown', 'missing', 'access', 'http', 'transport', 'hash', 'quote'])
def test_saved_dom_excerpt_preserves_rejection_boundaries(tmp_path, mutation):
    payload = public_input(tmp_path)
    path = tmp_path / 'capture.json'
    capture = json.loads(path.read_text(encoding='utf-8'))
    capture.update(content_ok=False, http_status=200)
    capture['capture_completeness']['status'] = 'complete_against_saved_dom'
    payload['sources'][0]['capture_scope'] = 'excerpt_only'
    if mutation == 'unknown': capture['capture_completeness']['status'] = 'unknown'
    if mutation == 'missing': capture['capture_completeness'].pop('status')
    if mutation == 'access': capture['capture_completeness']['access'] = {'status': 'login_required'}
    if mutation == 'http': capture['http_status'] = 403
    if mutation == 'transport': capture['transport_ok'] = False
    path.write_text(json.dumps(capture), encoding='utf-8')
    payload['sources'][0]['archive_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    if mutation == 'hash': payload['sources'][0]['archive_sha256'] = '0' * 64
    if mutation == 'quote': payload['evidence'][0]['text'] = 'Not in captured text'
    with pytest.raises(BoundedDeepLoopError) as caught:
        run(tmp_path, payload)
    expected = {'hash': 'public_archive_hash_mismatch', 'quote': 'public_quote_missing'}
    assert caught.value.code == expected.get(mutation, 'public_archive_invalid')


def test_same_reference_new_content_is_retained_as_variant(tmp_path):
    payload = public_input(tmp_path)
    original = payload['sources'][0]
    capture = json.loads((tmp_path / 'capture.json').read_text(encoding='utf-8'))
    capture['extracted_text'] = 'Search results do not always update automatically.'
    other = tmp_path / 'variant.json'
    other.write_text(json.dumps(capture), encoding='utf-8')
    payload['sources'].append({**original, 'source_id': 's2', 'archive_path': other.name,
                               'archive_sha256': hashlib.sha256(other.read_bytes()).hexdigest(),
                               'content': capture['extracted_text'],
                               'content_sha256': hashlib.sha256(capture['extracted_text'].encode()).hexdigest(),
                               'discovered_round': 2})
    payload['evidence'].append({**payload['evidence'][0], 'evidence_id': 'e2', 'source_id': 's2',
                                'text': capture['extracted_text'], 'relation': 'contradicts', 'discovered_round': 2})
    _, artifacts = run(tmp_path, payload)
    assert len(artifacts['source_admission']['admitted_sources']) == 2
    assert len(artifacts['source_admission']['source_variants']) == 1
    assert artifacts['evidence_analysis']['round_progress'][1]['conflicts_added'] == 1
    assert artifacts['article_brief']['topic_candidates'] == []


def test_qrp_record_shape_detects_evidence_without_count_growth():
    from question_research_poc.research_progress import evidence_snapshot, progress_delta
    sources = [{'id': 's', 'url': 'https://example.org/doc'}]
    claims = [{'id': 'c', 'text': 'Search works'}]
    before = evidence_snapshot(sources, claims, [{'id': 'e', 'claim_id': 'c', 'source_id': 's', 'quote_or_note': 'First finding', 'relation': 'supports'}])
    after = evidence_snapshot(sources, claims, [{'id': 'e', 'claim_id': 'c', 'source_id': 's', 'quote_or_note': 'Changed finding', 'relation': 'contradicts'}])
    assert progress_delta(before, after)['new_unique_evidence'] == 1


def test_online_loop_stops_when_reimports_only_inflate_row_counts(tmp_path, monkeypatch):
    from question_research_poc import research_loop as loop
    from question_research_poc.orchestrator import init_project
    from question_research_poc.storage import append_jsonl
    project = tmp_path / 'synthetic-project'
    init_project(project, 'Synthetic duplicate growth check')
    calls = []

    def import_same_material(index):
        append_jsonl(project / 'sources.jsonl', [{'id': f's{index}', 'url': 'https://example.org/doc'}])
        append_jsonl(project / 'claims.jsonl', [{'id': f'c{index}', 'text': 'Same claim'}])
        append_jsonl(project / 'evidence.jsonl', [{'id': f'e{index}', 'claim_id': f'c{index}',
                                                 'source_id': f's{index}', 'quote_or_note': 'Same cited text', 'relation': 'supports'}])

    import_same_material(0)
    monkeypatch.setattr(loop, 'ai_research_status', lambda *a, **k: {'metadata_available': True, 'live_ok': True, 'available': True})

    def fake_run(*args, **kwargs):
        calls.append(kwargs['query'])
        import_same_material(len(calls))
        return {'ok': True, 'job_id': str(len(calls)), 'run_id': '', 'fallback_used': False}

    monkeypatch.setattr(loop, 'run_ai_research_agent_research', fake_run)
    monkeypatch.setattr(loop, 'analyze_research_gaps', lambda *a, **k: {
        'gaps': [{'id': 'gap', 'status': 'actionable_search'}],
        'actionable_queries': [{'query': f'new query {len(calls)}'}]})
    result = loop.run_research_loop(project, rounds=4, max_queries_per_round=1, no_network=True)
    assert len(calls) == 2
    assert result['stop_reason'] == 'no_new_source_or_evidence'
    assert all(row['growth']['evidence'] == 1 for row in result['rounds'])
    assert all(row['evidence_gain']['new_unique_evidence'] == 0 for row in result['rounds'])
