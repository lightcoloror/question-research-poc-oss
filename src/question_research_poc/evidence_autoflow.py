"""Mechanical observations for the existing saved-capture receipt chain.

No model, search provider, crawler, or alternative stage scheduler lives here.
The explicit inventory supplies candidate URLs; ARW supplies gap suggestions.
Extracts are review material, never inferred answers to the user's question.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from filelock import FileLock

from .research_progress import canonical_reference
from .storage import read_json, write_json
from .topic_research import normalize_topic_input
from .passage_retrieval import PROFILE, locate, verify_passage

LIMITATIONS = [
    'Semantic analysis was not run; no model was called.',
    'These are mechanically selected exact excerpts, not verified conclusions.',
    'QRP segments and ARW BM25 select bounded question-matched passages; scores are lexical order, not confidence.',
    'Only selected exact context windows are presented; omitted context, negation and contradictions require review.',
    'Lexical overlap does not establish semantic relevance, answer sufficiency or independent support.',
    'Saved captures may be partial or synthetic; no live acquisition or freshness verification occurred.',
]


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _stable(path, value):
    """A resumed handoff must have exactly the same content."""
    if path.exists():
        if read_json(path) != value:
            raise ValueError('autoflow_artifact_drift')
    else:
        write_json(path, value)


def _excerpts(run, captures, retrieval):
    result = []
    for row in captures:
        path = (run / row['path']).resolve()
        if not path.is_relative_to(run.resolve()) or _sha(path.read_bytes()) != row['sha256']:
            raise ValueError('autoflow_capture_drift')
        saved = read_json(path)
        for passage in retrieval['passages']:
            if passage['source_id'] != row['source_id']:
                continue
            verify_passage(saved, passage)
            result.append({**row, 'quote': passage['quote'], 'synthetic': bool(saved.get('fixture')),
                           'passage': {**passage, 'capture_sha256': row['sha256'], 'capture_path': row['path']}})
    return result


def _gaps(excerpts):
    from research_workflow.quality import quality_for_report, deepen_claim_suggestions
    report = {'claims': [], 'sources': [], 'evidence': [], 'claim_citations': []}
    for row in excerpts:
        cid = 'excerpt-' + row['passage']['passage_id']
        eid = 'quote-' + row['passage']['passage_id']
        report['claims'].append({'id': cid, 'text': row['quote'], 'verdict': 'partial',
                                 'confidence': 0, 'evidence_ids': [eid]})
        report['sources'].append({'id': row['source_id'], 'url': row['url']})
        report['evidence'].append({'id': eid, 'source_id': row['source_id'],
                                  'quote_or_paraphrase': row['quote']})
        report['claim_citations'].append({'claim_id': cid, 'evidence_ids': [eid],
                                          'source_ids': [row['source_id']], 'citations': [row['url']]})
    quality = quality_for_report(report)
    return {'arw_quality': quality,
            'unresolved_gaps': deepen_claim_suggestions(report, quality, max_queries=2)}


def _observation(contract, fixture, rows, run, retrieval):
    stage = contract['stage']
    value = {'stage': stage, 'basis_artifact_sha256': contract['basis_artifact_sha256'],
             'automation_context': {'profile': PROFILE, 'semantic_analysis': 'not_run',
                                    'model_called': False, 'limitations': LIMITATIONS},
             'retrieval_summary': {k: retrieval[k] for k in ('query', 'method', 'score_meaning',
                 'scan_budget_exhausted', 'abstention_reason')}}
    ranked_rows = []
    for passage in retrieval['passages']:
        row = next(r for r in rows if canonical_reference(r['url']) == canonical_reference(passage['url']))
        if row not in ranked_rows:
            ranked_rows.append(row)
    if stage == 'source_admission':
        if not ranked_rows:
            value.update(reads=[], stop_reason='budget_exhausted' if retrieval['abstention_reason'] == 'budget_exhausted'
                         else 'insufficient_evidence')
            return value
        fits = ranked_rows[0]['input_bytes'] <= fixture['budgets']['max_text_bytes']
        value['reads'] = [{'url': ranked_rows[0]['url']}] if fits else []
        if not fits:
            value['stop_reason'] = 'budget_exhausted'
        return value
    initial = read_json(run / 'artifacts/02-source_admission.json')
    excerpts = _excerpts(run, initial['captures'], retrieval)
    if stage == 'evidence_analysis':
        basis = excerpts[0]
        sid = 'gap-' + _sha((fixture['question'] + basis['passage']['passage_id']).encode())[:12]
        value['subquestions'] = [{'subquestion_id': sid,
            'text': fixture['question'], 'depth': 1, 'query_scope': 'original_question_no_semantic_decomposition',
            'basis_source_id': basis['source_id'], 'basis_quote': basis['quote'], 'basis_passage': basis['passage']}]
        value.update(_gaps(excerpts))
        seen = {canonical_reference(r['url']) for r in initial['captures']}
        remaining = [r for r in ranked_rows if canonical_reference(r['url']) not in seen]
        budget = fixture['budgets']
        capacity = min(budget['max_sources'] - len(seen), budget['max_expansions_per_round'])
        available_bytes = budget['max_text_bytes'] - initial['acquisition']['bytes_read']
        selected, byte_limited = [], False
        if retrieval['scan_budget_exhausted']:
            capacity = 0
        for row in remaining[:max(0, capacity)]:
            if row['input_bytes'] > available_bytes:
                byte_limited = True
                break
            selected.append(row)
            available_bytes -= row['input_bytes']
        value['reads'] = [{'url': r['url'], 'subquestion_id': sid,
                           'gap_claim_ids': [g['claim_id'] for g in value['unresolved_gaps']]}
                          for r in selected]
        value['selection_method'] = 'question_passage_BM25_then_stable_source_id_not_semantic_support'
        if not selected:
            value['stop_reason'] = 'budget_exhausted' if capacity <= 0 or byte_limited else 'no_new_evidence'
        return value
    if stage != 'guarded_synthesis':
        raise ValueError('unsupported_autoflow_stage')
    deep = read_json(run / 'artifacts/03-evidence_analysis.json')
    excerpts += _excerpts(run, deep['captures'], retrieval)
    sid = deep['subquestions'][0]['subquestion_id']
    claims = {}
    for row in excerpts:
        quote = row['quote']
        # Mirrors share a claim; QRP's existing content/evidence deduplication
        # decides progress instead of treating new URLs as independent support.
        claim = claims.setdefault(quote, {'subquestion_id': sid,
            'text': 'Unverified exact excerpt (semantic analysis not run): ' + quote,
            'evidence': []})
        claim['evidence'].append({'source_id': row['source_id'], 'text': quote, 'passage': row['passage']})
    value['claims'] = list(claims.values())
    value.update(_gaps(excerpts))
    value['independent_crosscheck'] = 'not_established'
    return value


def _review(output, fixture, binding, result):
    run = output / 'research/saved-capture-research'
    synthesis = read_json(run / 'artifacts/04-guarded_synthesis.json')
    initial = read_json(run / 'artifacts/02-source_admission.json')
    deep = read_json(run / 'artifacts/03-evidence_analysis.json')
    observation = synthesis.get('codex_observation', {})
    gaps = observation.get('unresolved_gaps') or deep.get('codex_observation', {}).get('unresolved_gaps', [])
    artifacts = {p.relative_to(run).as_posix(): _sha(p.read_bytes())
                 for p in sorted((run / 'artifacts').glob('*.json'))}
    material = synthesis.get('derived_material', {})
    packet = {'schema': 'question-research-autoflow-review.v1', 'profile': PROFILE,
              'question': fixture['question'], 'binding': binding, 'research_complete': False,
              'semantic_analysis': 'not_run', 'model_called': False, 'publish_authorized': False,
              'retrieval_kind': 'lexical_candidate', 'semantic_support': 'not_assessed',
              'stop_reason': synthesis['stop_reason'], 'limitations': LIMITATIONS,
              'unresolved_gaps': gaps or [{'missing_evidence_reason': 'No usable grounded evidence for synthesis.'}],
              'rounds_completed': material.get('rounds_completed', 1 if initial['captures'] else 0),
              'sources': [{'source_id': s['source_id'], 'provenance_kind': s.get('provenance_kind', 'unknown'),
                           'synthetic': s.get('synthetic', False), 'quality': s['quality'],
                           'freshness': s['freshness'], 'archive_path': s['archive_path'],
                           'archive_sha256': s['archive_sha256']} for s in material.get('sources', [])],
              'followup_captures': len(deep['captures']),
              'stop_scope': 'bounded inventory and mechanical evidence progress; unresolved gaps remain',
              'candidate_dir': result.get('candidate_dir'), 'research_output': result.get('research_output'),
              'stage_hashes': artifacts,
              'evidence': [{'local_id': e['evidence_id'],
                            'scoped_id': binding['topic_sha256'] + ':' + e['evidence_id'],
                            'source_id': e['source_id'], 'text': e['text'], 'passage': e.get('passage')}
                           for e in material.get('evidence', [])]}
    folder = output / 'autoflow'
    packet['retrieval_index'] = str(folder / 'retrieval-index.json')
    packet['retrieval_summary'] = observation.get('retrieval_summary') or initial.get('codex_observation', {}).get('retrieval_summary')
    _stable(folder / 'review.json', packet)
    text = '\n'.join(['# Evidence review: ' + fixture['question'], '',
        'Research incomplete. Stop reason: ' + packet['stop_reason'], '',
        *['- ' + item for item in LIMITATIONS], '',
        'Candidate: ' + (str(result.get('candidate_dir')) if result.get('candidate_dir') else 'not produced'), '',
        'Unresolved gaps:', *['- ' + g['missing_evidence_reason'] for g in packet['unresolved_gaps']], '',
        'Exact passage locations (Unicode codepoints, end exclusive):',
        *[f"- {e['scoped_id']}: {e['passage']['paragraph_id']} [{e['passage']['start']}, {e['passage']['end']}); body {e['passage']['body_sha256']}"
          for e in packet['evidence'] if e['passage']], '',
        'Evidence identifiers are scoped by topic SHA256 in review.json.', ''])
    review = folder / 'review.md'
    if review.exists() and review.read_text(encoding='utf-8') != text:
        raise ValueError('autoflow_review_drift')
    if not review.exists():
        temporary = review.with_name(review.name + '.tmp')
        temporary.write_text(text, encoding='utf-8')
        temporary.replace(review)
    return {**result, 'review_bundle': str(folder / 'review.json'), 'review_markdown': str(review),
            'research_complete': False, 'semantic_analysis': 'not_run', 'stop_reason': packet['stop_reason']}


def advance_automatically(topic, captures, output, qrp_root, *, advance):
    """Drive at most three handoffs through the existing Content/QRP entry.

    The callback owns locking, hash checks, stage receipts, acquisition and
    candidate recovery. No observations are supplied by the caller in this mode.
    """
    topic, captures, output, qrp_root = [Path(p).resolve() for p in (topic, captures, output, qrp_root)]
    if topic.stat().st_size > 65536 or captures.stat().st_size > 65536:
        raise ValueError('autoflow_input_json_too_large')
    fixture = normalize_topic_input(read_json(topic), topic)
    rows = read_json(captures).get('captures', [])
    if not 1 <= len(rows) <= 8:
        raise ValueError('autoflow_inventory_requires_1_to_8_captures')
    # Duplicate canonical URLs are ambiguous in the existing saved-import entry.
    if len({canonical_reference(r['url']) for r in rows}) != len(rows):
        raise ValueError('autoflow_duplicate_inventory_url')
    for row in rows:
        path = (captures.parent / row['path']).resolve()
        if not path.is_relative_to(captures.parent) or not path.is_file():
            raise ValueError('autoflow_capture_path_invalid')
        row['input_bytes'] = path.stat().st_size
        if row['input_bytes'] > 20 * 1024 * 1024:
            raise ValueError('autoflow_capture_file_too_large')
    binding = {'profile': PROFILE, 'topic_sha256': _sha(topic.read_bytes()),
               'captures_sha256': _sha(captures.read_bytes())}
    # Sibling lock avoids altering the existing entry's empty-directory contract.
    output.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(output.with_name(output.name + '.autoflow.lock')), timeout=0):
        folder = output / 'autoflow'
        run = output / 'research/saved-capture-research'
        if (folder / 'binding.json').exists() and read_json(folder / 'binding.json').get('profile') != PROFILE:
            raise ValueError('autoflow_profile_changed_use_new_output_v2')
        # Do not relabel manually authored interpretations as mechanical work.
        for name in ('02-source_admission.json', '03-evidence_analysis.json', '04-guarded_synthesis.json'):
            artifact = run / 'artifacts' / name
            if artifact.exists():
                observed = read_json(artifact).get('codex_observation')
                if observed and observed.get('automation_context', {}).get('profile') != PROFILE:
                    raise ValueError('autoflow_manual_stage_requires_new_output')
        if folder.exists():
            _stable(folder / 'binding.json', binding)
        result = advance(topic, captures, output, qrp_root)
        folder.mkdir(exist_ok=True)
        _stable(folder / 'binding.json', binding)
        retrieval = locate(captures, rows, fixture['question'])
        _stable(folder / 'retrieval-index.json', retrieval)
        for _ in range(3):
            if result['status'] != 'awaiting_observation':
                break
            contract = result['research']['observation_contract']
            value = _observation(contract, fixture, rows, run, retrieval)
            path = folder / (contract['stage'] + '.json')
            _stable(path, value)
            result = advance(topic, captures, output, qrp_root, observation=path)
        if result['status'] == 'awaiting_observation':
            raise ValueError('autoflow_handoff_budget_exhausted')
        return _review(output, fixture, binding, result)
