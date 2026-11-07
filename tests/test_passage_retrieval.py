"""Exact provenance and conservative lexical selection over synthetic documents."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from question_research_poc import passage_retrieval as passage
from question_research_poc import topic_research
from question_research_poc.web_fetch_bridge import _split_chunks, _split_chunk_spans
from test_evidence_autoflow import run, setup, inventory


def corpus(root, bodies, *, full=()):
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, body in enumerate(bodies):
        url = f'https://example.org/synthetic/{n}'
        saved = {'title': f'Synthetic {n}', 'requested_url': url, 'final_url': url,
                 'status': 'ok' if n in full else 'partial', 'content_ok': n in full,
                 'transport_ok': True, 'http_status': 200, 'fetched_at': '2026-10-07T00:00:00Z',
                 'capture_completeness': {'status': 'full' if n in full else 'partial'},
                 'extracted_text': body, 'fixture': True, 'fact_verified': False}
        path = root / f'{n}.json'
        path.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
        rows.append({'url': url, 'path': path.name, 'sha256': passage.digest(path.read_bytes())})
    index = root / 'captures.json'
    index.write_text(json.dumps({'captures': rows}), encoding='utf-8')
    return index, rows


def inputs(root, question, bodies):
    index, rows = corpus(root, bodies)
    topic = root / 'topic.json'
    topic.write_text(json.dumps({'question': question, 'audience': 'Reviewers', 'budgets': {}},
                               ensure_ascii=False), encoding='utf-8')
    return (topic, index, root / 'out'), rows


def evidence_inventory(output):
    # The Content entry updates workflow-state.json with the last invocation's
    # reuse status; research receipts, candidates and review bytes are immutable.
    return {name: inventory(output / name) for name in ('research', 'candidate', 'autoflow')}


def test_late_answer_chinese_and_mixed_tokens_not_inventory_order(tmp_path):
    preamble = ('背景介绍。' * 180) + '\r\n'
    index, rows = corpus(tmp_path, ['花园介绍与开放时间。', preamble + '图书馆使用 QR 扫码完成图书归还，离线记录需要稍后同步。'])
    result = passage.locate(index, rows, '图书馆如何通过QR扫码归还图书？')
    assert result['passages'] and result['passages'][0]['start'] > 600
    assert result == passage.locate(index, list(reversed(rows)), result['query'])
    best = result['passages'][0]
    assert best['url'] == rows[1]['url'] and 'QR' in best['quote']
    assert best['status'] == 'lexical_candidate' and result['semantic_analysis'] == 'not_run'


def test_original_unicode_crlf_and_repeated_occurrences(tmp_path):
    quote = '🚲 Bicycle return stations accept checked equipment.'
    body = '  '+quote+' \r\n\r\n\t'+quote+'\t\r\n'
    index, rows = corpus(tmp_path, [body])
    result = passage.locate(index, rows, 'bicycle return')
    selected = result['passages']
    assert len(selected) == 2 and len({p['paragraph_id'] for p in selected}) == 2
    assert [p['start'] for p in selected] == [2, body.rindex(quote)]
    for p in selected:
        assert body[p['start']:p['end']] == quote
        assert p['end_exclusive'] and p['offset_unit'] == 'python_unicode_codepoint'
        assert passage.verify_passage(json.loads((tmp_path / '0.json').read_text(encoding='utf-8')), p,
                                      input_sha256=rows[0]['sha256'])


def test_legacy_splitter_content_compatible():
    body = '  first\r\n\r\n'+('x ' * 350)+'\r last\t'
    expected = []
    for raw in body.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        paragraph = raw.strip()
        if not paragraph:
            continue
        expected.extend([paragraph] if len(paragraph) <= 280 else
                        [paragraph[i:i+280].strip() for i in range(0, len(paragraph), 240)])
    assert _split_chunks(body) == expected
    assert all(body[p['start']:p['end']].strip() for p in _split_chunk_spans(body))


@pytest.mark.parametrize('query,body,reason', [
    ('telescope mirror coating', 'Garden compost uses dry leaves.', 'no_relevant_passage'),
    ('telescope mirror coating durability', 'A telescope appears in the catalogue.', 'insufficient_evidence'),
    ('如何什么是否', '望远镜涂层需要复核。', 'insufficient_query_terms'),
])
def test_abstention_has_no_first_source_fallback(tmp_path, query, body, reason):
    index, rows = corpus(tmp_path, [body])
    result = passage.locate(index, rows, query)
    assert result['passages'] == [] and result['abstention_reason'] == reason


def test_keyword_overlap_does_not_claim_semantic_support_or_resolve_polarity(tmp_path):
    index, rows = corpus(tmp_path, ['The telescope mirror coating is not waterproof.\n'
                                  'The telescope mirror coating is waterproof.'])
    result = passage.locate(index, rows, 'telescope mirror coating')
    assert len(result['passages']) == 2
    assert {p['polarity_terms_present'] for p in result['passages']} == {True, False}
    assert all(p['polarity_assessment'] == 'not_run' for p in result['passages'])
    assert result['semantic_analysis'] == 'not_run'


def test_context_halo_and_truncated_paragraph_bounds(tmp_path):
    body = 'x' * 205 + ' not waterproof mirror coating ' + 'x' * 500
    index, rows = corpus(tmp_path, [body])
    result = passage.locate(index, rows, 'waterproof mirror coating')
    assert any('not' in p['quote'] for p in result['passages'])
    assert all(p['context_truncated'] for p in result['passages'])
    with patch.object(passage, 'MAX_BODY_CHARS', 300):
        limited = passage.locate(index, rows, 'waterproof mirror coating')
    assert limited['scan_budget_exhausted']
    assert all(p['paragraph_end'] == len(body) and p['end'] <= 300 and p['context_right_truncated']
               for p in limited['passages'])


def test_partial_full_separate_and_budget_exhaustion(tmp_path):
    index, rows = corpus(tmp_path, ['Mirror coating synthetic test A.', 'Mirror coating synthetic test B.'], full=(1,))
    result = passage.locate(index, rows, 'mirror coating')
    assert {p['completeness'] for p in result['passages']} == {'partial', 'full'}
    assert all(not p['fact_verified'] for p in result['passages'])
    with patch.object(passage, 'MAX_CORPUS_BYTES', 1):
        limited = passage.locate(index, rows, 'mirror coating')
    assert limited['abstention_reason'] == 'budget_exhausted' and not limited['passages']
    assert all(s['scan_status'] == 'unscanned_budget' for s in limited['sources'])


@pytest.mark.parametrize('field,value', [('start', 1), ('body_sha256', 'bad'),
    ('input_capture_sha256', 'bad'), ('source_id', 'foreign'), ('url', 'https://example.org/foreign'),
    ('paragraph_id', 'wrong'), ('passage_id', 'wrong'), ('offset_unit', 'utf16'), ('paragraph_end', 2)])
def test_changed_provenance_fails_closed(tmp_path, field, value):
    index, rows = corpus(tmp_path, ['Mirror coating synthetic test.'])
    p = passage.locate(index, rows, 'mirror coating')['passages'][0]
    saved = json.loads((tmp_path / '0.json').read_text(encoding='utf-8'))
    p[field] = value
    with pytest.raises(ValueError, match='drift'):
        passage.verify_passage(saved, p, input_sha256=rows[0]['sha256'])


def test_input_capture_changes_before_scan_rejected(tmp_path):
    index, rows = corpus(tmp_path, ['Mirror coating synthetic test.'])
    (tmp_path / '0.json').write_text('{}')
    with pytest.raises(ValueError, match='passage_input_drift'):
        passage.locate(index, rows, 'mirror coating')


def test_end_to_end_offsets_no_semantic_promotion_and_resume(tmp_path):
    preamble = ('Unrelated introduction. ' * 40) + '\n'
    args, rows = inputs(tmp_path, 'library book returns',
                        [preamble + 'Library book returns use the desk in synthetic example A.',
                         preamble + 'Library book returns use the slot in synthetic example B.'])
    result = run(args)
    packet = json.loads(Path(result['review_bundle']).read_text(encoding='utf-8'))
    base = args[2] / 'research/saved-capture-research'
    for e in packet['evidence']:
        p = e['passage']
        original = json.loads((tmp_path / p['input_path']).read_text(encoding='utf-8'))
        archived = json.loads((base / p['capture_path']).read_text(encoding='utf-8'))
        assert p['start'] > 600 and e['text'] == p['quote']
        assert passage.verify_passage(original, p, input_sha256=passage.digest((tmp_path / p['input_path']).read_bytes()))
        assert passage.verify_passage(archived, p)
        assert p['capture_sha256'] == passage.digest((base / p['capture_path']).read_bytes())
    synthesis = json.loads((base / 'artifacts/04-guarded_synthesis.json').read_text(encoding='utf-8'))
    assert synthesis['derived_analysis']['claims']
    assert all(c['evidence_status'] == 'retrieval_candidate' for c in synthesis['derived_analysis']['claims'])
    assert all(not e['usable_as_source_fact'] and not e['usable_as_cited_source']
               for e in synthesis['derived_analysis']['evidence_records'])
    before = evidence_inventory(args[2])
    assert run(args)['reused']
    assert evidence_inventory(args[2]) == before


def test_old_profile_requires_new_output_without_mutation(tmp_path):
    args = setup(tmp_path / 'versioned', 'Version')
    run(args)
    binding_path = args[2] / 'autoflow/binding.json'
    value = json.loads(binding_path.read_text(encoding='utf-8'))
    value['profile'] = 'saved-excerpt-observations.v1'
    binding_path.write_text(json.dumps(value))
    before = inventory(args[2])
    with pytest.raises(ValueError, match='profile_changed_use_new_output_v2'):
        run(args)
    assert before == inventory(args[2])


@pytest.mark.parametrize('field', ['capture_sha256', 'input_capture_sha256', 'quote'])
def test_stage_passage_tamper_rejected_even_when_body_contains_quote(tmp_path, field):
    args = setup(tmp_path / 'tamper', 'Mirror')
    run(args)
    base = args[2] / 'research/saved-capture-research'
    acquired = json.loads((base / 'artifacts/02-source_admission.json').read_text(encoding='utf-8'))['captures']
    observed = json.loads((args[2] / 'autoflow/evidence_analysis.json').read_text(encoding='utf-8'))['subquestions'][0]
    p = observed['basis_passage']
    saved = json.loads((base / acquired[0]['path']).read_text(encoding='utf-8'))
    p[field] = 'tampered'
    with pytest.raises((RuntimeError, ValueError), match='drift|exact saved import'):
        topic_research._verify_located_passage(base, acquired, acquired[0]['source_id'],
                                              observed['basis_quote'], saved, p)


def test_end_to_end_weak_overlap_abstains_and_resumes(tmp_path):
    args, _ = inputs(tmp_path, 'telescope mirror coating durability', ['A telescope is in a catalogue.'])
    result = run(args)
    packet = json.loads(Path(result['review_bundle']).read_text(encoding='utf-8'))
    assert result['status'] == 'needs_evidence_review' and result['stop_reason'] == 'insufficient_evidence'
    assert packet['retrieval_summary']['abstention_reason'] == 'insufficient_evidence'
    assert not packet['evidence'] and packet['rounds_completed'] == 0
    before = evidence_inventory(args[2])
    run(args)
    assert evidence_inventory(args[2]) == before


def test_same_keyword_different_topics_remain_lexical_only(tmp_path):
    index, rows = corpus(tmp_path, ['Library return policies cover overdue books.',
                                 'Bicycle return policies cover equipment damage.'])
    library = passage.locate(index, rows, 'library return policies')
    bicycle = passage.locate(index, rows, 'bicycle return policies')
    assert library['passages'][0]['url'] == rows[0]['url']
    assert bicycle['passages'][0]['url'] == rows[1]['url']
    # Shared generic terms can still match the other topic: do not label these
    # semantic answers or use lexical rank to assert that they resolve a gap.
    assert all(p['status'] == 'lexical_candidate' for r in (library, bicycle) for p in r['passages'])
    assert all(r['semantic_analysis'] == 'not_run' for r in (library, bicycle))
