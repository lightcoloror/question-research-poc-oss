import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

QRP_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('QRP_TEST_WORKSPACE_ROOT', QRP_ROOT.parent)).resolve()
sys.path.insert(0, str(ROOT / 'content-studio-poc/scripts'))
entry = pytest.importorskip('capture_research_candidate', reason='Optional ContentStudio capture consumer is required for this cross-owner suite')
from saved_research_candidate import inventory, sha
from question_research_poc import evidence_autoflow as auto
from question_research_poc import topic_research


def setup(root, theme, *, count=2, mirror=False, budgets=None, empty=False):
    from web_content_fetcher.extractors import extract_content
    root.mkdir(parents=True)
    topic = root / 'topic.json'
    topic.write_text(json.dumps({'question': theme, 'audience': 'Reviewers', 'budgets': budgets or {}}))
    rows = []
    for n in range(count):
        text = (f'{theme} source {0 if mirror else n} records a synthetic procedure. '
                'The saved input must match its recorded hash before work resumes. '
                'This fictional example tests workflow recovery, not a real service. '
                'An independent reviewer must check the scope and applicability before use.')
        body = extract_content('<article><p>' + text + '</p></article>', extractor='builtin').text
        url = f'https://example.org/{theme.lower()}/{n}'
        capture = {'title': theme, 'requested_url': url, 'final_url': url, 'status': 'partial',
                   'transport_ok': True, 'content_ok': False, 'http_status': 200,
                   'fetched_at': '2026-10-07T00:00:00Z', 'extracted_text': '' if empty else body,
                   'capture_completeness': {'status': 'complete_against_saved_dom'}, 'fixture': True}
        path = root / f'capture{n}.json'
        path.write_text(json.dumps(capture))
        rows.append({'url': url, 'path': path.name, 'sha256': sha(path.read_bytes())})
    index = root / 'captures.json'
    index.write_text(json.dumps({'captures': rows}))
    return topic, index, root / 'out'


def run(inputs):
    with patch('socket.socket.connect', side_effect=AssertionError('offline only')):
        return auto.advance_automatically(*inputs, QRP_ROOT, advance=entry.advance)


def test_two_topics_callable_entry_and_review_limits(tmp_path, capsys):
    packets = []
    for theme in ('Search', 'Backups'):
        inputs = setup(tmp_path / theme, theme)
        with patch('socket.socket.connect', side_effect=AssertionError('offline only')):
            code = entry.main(['--topic', str(inputs[0]), '--captures', str(inputs[1]),
                               '--output-dir', str(inputs[2]), '--auto-observations',
                               '--qrp-root', str(QRP_ROOT)])
        result = json.loads(capsys.readouterr().out)
        assert code == 0 and result['status'] == 'candidate_only'
        packet = json.loads(Path(result['review_bundle']).read_text(encoding='utf-8'))
        assert packet['semantic_analysis'] == 'not_run' and not packet['research_complete']
        assert all(s['synthetic'] and s['provenance_kind'] == 'synthetic_fixture' and
                   s['quality'] == 'unknown' and s['freshness'] == 'unknown' for s in packet['sources'])
        assert not packet['model_called'] and packet['unresolved_gaps']
        assert 'Semantic analysis was not run' in Path(result['review_markdown']).read_text(encoding='utf-8')
        assert theme in Path(result['research_output']).read_text(encoding='utf-8')
        assert 'semantic analysis not run' in Path(result['research_output']).read_text(encoding='utf-8')
        deep = json.loads((inputs[2] / 'research/saved-capture-research/artifacts/03-evidence_analysis.json').read_text(encoding='utf-8'))
        assert len(deep['captures']) == 1
        assert deep['codex_observation']['reads'][0]['gap_claim_ids']
        ledger = json.loads((inputs[2] / 'research/saved-capture-research/acquisition-ledger.json').read_text(encoding='utf-8'))
        assert len(ledger['saved_imports']) == 2 and not ledger['requests']
        packets.append(packet)
    assert {e['scoped_id'] for e in packets[0]['evidence']}.isdisjoint(e['scoped_id'] for e in packets[1]['evidence'])
    assert 'Backups' not in json.dumps(packets[0]) and 'Search' not in json.dumps(packets[1])


@pytest.mark.parametrize('options,reason,imports,rounds', [
    ({'count': 1}, 'no_new_evidence', 1, 1),
    ({'mirror': True}, 'no_new_evidence', 2, 2),
    ({'budgets': {'max_sources': 1}}, 'budget_exhausted', 1, 1),
    ({'count': 5}, 'budget_exhausted', 4, 2),
    ({'budgets': {'max_rounds': 1}}, 'budget_exhausted', 1, 1),
    ({'empty': True}, 'insufficient_evidence', 0, 0),
])
def test_stopping_is_explicit_and_incomplete(tmp_path, options, reason, imports, rounds):
    inputs = setup(tmp_path / 'source', 'Limits', **options)
    result = run(inputs)
    packet = json.loads(Path(result['review_bundle']).read_text(encoding='utf-8'))
    assert packet['stop_reason'] == reason and packet['rounds_completed'] == rounds
    assert packet['research_complete'] is False and packet['unresolved_gaps']
    ledger = json.loads((inputs[2] / 'research/saved-capture-research/acquisition-ledger.json').read_text(encoding='utf-8'))
    assert len(ledger.get('saved_imports', [])) == imports


@pytest.mark.parametrize('point', ['followup_import', 'before_consume', 'before_review', 'commit_review'])
def test_interruption_then_resume_without_duplicate_work(tmp_path, point):
    inputs = setup(tmp_path / 'source', 'Recovery')
    if point == 'followup_import':
        original = topic_research._wcf_read
        def fail(*args, **kwargs):
            value = original(*args, **kwargs)
            if args[2] == 2:
                raise RuntimeError('synthetic_interrupt')
            return value
        target = patch.object(topic_research, '_wcf_read', side_effect=fail)
    elif point == 'before_consume':
        import saved_research_candidate as projection
        target = patch.object(projection, 'consume', side_effect=RuntimeError('synthetic_interrupt'))
    elif point == 'before_review':
        target = patch.object(auto, '_review', side_effect=RuntimeError('synthetic_interrupt'))
    else:
        original_replace = Path.replace
        def fail_replace(path, destination):
            if path.name == 'review.md.tmp':
                raise RuntimeError('synthetic_interrupt')
            return original_replace(path, destination)
        target = patch.object(Path, 'replace', fail_replace)
    with target, pytest.raises(RuntimeError, match='synthetic_interrupt'):
        run(inputs)
    base = inputs[2] / 'research/saved-capture-research'
    ledger_before = (base / 'acquisition-ledger.json').read_bytes()
    receipts = inventory(base / 'receipts')
    native = inputs[2] / 'candidate/candidate-state.json'
    project_before = json.loads(native.read_text(encoding='utf-8')).get('project') if native.exists() else None
    result = run(inputs)
    assert (base / 'acquisition-ledger.json').read_bytes() == ledger_before
    assert all(inventory(base / 'receipts')[k] == v for k, v in receipts.items())
    if project_before:
        assert json.loads(native.read_text(encoding='utf-8'))['project'] == project_before
    candidate_before = inventory(inputs[2] / 'candidate')
    again = run(inputs)
    assert again['reused'] and again['candidate_dir'] == result['candidate_dir']
    assert inventory(inputs[2] / 'candidate') == candidate_before
    assert len(list((inputs[2] / 'candidate/attempts').iterdir())) == 1


def test_drift_and_manual_stage_are_rejected(tmp_path):
    inputs = setup(tmp_path / 'source', 'Binding')
    result = entry.advance(*inputs, QRP_ROOT)
    contract = result['research']['observation_contract']
    path = tmp_path / 'manual.json'
    row = json.loads(inputs[1].read_text(encoding='utf-8'))['captures'][0]
    path.write_text(json.dumps({'stage': contract['stage'], 'basis_artifact_sha256': contract['basis_artifact_sha256'],
                                'reads': [{'url': row['url']}]}))
    entry.advance(*inputs, QRP_ROOT, observation=path)
    with pytest.raises(ValueError, match='manual_stage'):
        run(inputs)
    clean = setup(tmp_path / 'clean', 'Drift')
    run(clean)
    # A terminal rerun still checks the persisted review; input drift must fail first.
    clean[0].write_text(clean[0].read_text(encoding='utf-8').replace('Drift', 'Changed'))
    with pytest.raises(ValueError, match='drift'):
        run(clean)


def test_cross_topic_observation_hash_rejected(tmp_path):
    first, second = setup(tmp_path / 'a', 'Alpha'), setup(tmp_path / 'b', 'Beta')
    run(first)
    result = entry.advance(*second, QRP_ROOT)
    assert result['status'] == 'awaiting_observation'
    with pytest.raises(RuntimeError, match='preceding stage bytes'):
        entry.advance(*second, QRP_ROOT, observation=first[2] / 'autoflow/source_admission.json')


def test_unknown_request_never_replayed(tmp_path):
    inputs = setup(tmp_path / 'source', 'Unknown')
    original = topic_research._wcf_read
    def fail(root, url, *args, **kwargs):
        # Reuse the actual implementation once to locate its request marker,
        # then emulate an unknown outcome without erasing the saved capture.
        value = original(root, url, *args, **kwargs)
        marker = next((root / 'captures').glob('*.request.json'))
        marker.write_text(json.dumps({'status': 'request_started_unknown'}))
        raise RuntimeError('synthetic_interrupt')
    with patch.object(topic_research, '_wcf_read', side_effect=fail), pytest.raises(RuntimeError, match='synthetic_interrupt'):
        run(inputs)
    with pytest.raises(RuntimeError, match='unknown|reservation'):
        run(inputs)


def test_unrelated_excerpt_prefix_is_not_a_fallback_answer(tmp_path):
    inputs = setup(tmp_path / 'source', 'Prefix')
    index = json.loads(inputs[1].read_text(encoding='utf-8'))
    for n, row in enumerate(index['captures']):
        path = inputs[1].parent / row['path']
        value = json.loads(path.read_text(encoding='utf-8'))
        value['extracted_text'] = 'Shared synthetic introductory text. ' * 25 + f'Different tail {n}.'
        path.write_text(json.dumps(value))
        row['sha256'] = sha(path.read_bytes())
    inputs[1].write_text(json.dumps(index))
    result = run(inputs)
    assert result['stop_reason'] == 'insufficient_evidence'
    packet = json.loads(Path(result['review_bundle']).read_text(encoding='utf-8'))
    assert packet['followup_captures'] == 0 and not packet['research_complete']
    assert not packet['evidence'] and packet['retrieval_summary']['abstention_reason'] == 'no_relevant_passage'


def test_pending_handoff_drift_and_url_budget(tmp_path):
    inputs = setup(tmp_path / 'source', 'Pending')
    original = entry.advance
    def interrupt(*args, **kwargs):
        if kwargs.get('observation'):
            raise RuntimeError('synthetic_interrupt')
        return original(*args, **kwargs)
    with pytest.raises(RuntimeError, match='synthetic_interrupt'):
        auto.advance_automatically(*inputs, QRP_ROOT, advance=interrupt)
    path = inputs[2] / 'autoflow/source_admission.json'
    value = json.loads(path.read_text(encoding='utf-8'))
    value['reads'][0]['url'] = 'https://example.org/foreign-topic'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='autoflow_artifact_drift'):
        run(inputs)
    with pytest.raises(ValueError, match='1_to_8'):
        run(setup(tmp_path / 'excess', 'Excess', count=9))


@pytest.mark.parametrize('initial', [False, True])
def test_byte_budget_stops_with_review_and_resumes(tmp_path, initial):
    inputs = setup(tmp_path / 'source', 'Bytes')
    index = json.loads(inputs[1].read_text(encoding='utf-8'))
    first_size = (inputs[1].parent / index['captures'][0]['path']).stat().st_size
    topic = json.loads(inputs[0].read_text(encoding='utf-8'))
    topic['budgets']['max_text_bytes'] = 1 if initial else first_size
    inputs[0].write_text(json.dumps(topic))
    result = run(inputs)
    packet = json.loads(Path(result['review_bundle']).read_text(encoding='utf-8'))
    assert packet['stop_reason'] == 'budget_exhausted' and not packet['research_complete']
    assert packet['rounds_completed'] == (0 if initial else 1)
    assert packet['followup_captures'] == 0
    assert run(inputs)['review_bundle'] == result['review_bundle']


@pytest.mark.parametrize('which', [0, 1])
def test_whitespace_body_stops_without_index_error(tmp_path, which):
    inputs = setup(tmp_path / 'source', 'Whitespace')
    index = json.loads(inputs[1].read_text(encoding='utf-8'))
    row = index['captures'][which]
    path = inputs[1].parent / row['path']
    value = json.loads(path.read_text(encoding='utf-8'))
    value['extracted_text'] = '  \n\t  '
    path.write_text(json.dumps(value))
    row['sha256'] = sha(path.read_bytes())
    inputs[1].write_text(json.dumps(index))
    result = run(inputs)
    assert result['stop_reason'] == 'no_new_evidence'
    assert result['status'] == 'candidate_only'
    packet = json.loads(Path(result['review_bundle']).read_text(encoding='utf-8'))
    assert len(packet['sources']) == 1 and packet['followup_captures'] == 0


def test_large_unselected_capture_is_rejected_before_materialization(tmp_path):
    inputs = setup(tmp_path / 'source', 'Large')
    path = inputs[1].parent / 'capture1.json'
    with path.open('wb') as handle:
        handle.truncate(20 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match='capture_file_too_large'):
        run(inputs)
    assert not inputs[2].exists()
