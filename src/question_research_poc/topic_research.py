"""Codex observation builders for the existing five-stage bounded loop.

This module owns no scheduler, model, crawler, or stage state machine. The caller
uses the existing receipt chain; WCF performs public acquisition and ARW grades
the candidate projection. Observations can only cite previously read captures.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import sys
import time
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .research_progress import canonical_reference, normalize_topic
from .storage import read_json, write_json


def _error(code, detail):
    from .bounded_deep_loop import BoundedDeepLoopError
    raise BoundedDeepLoopError(code, detail)


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def normalize_topic_input(payload, path):
    if not payload.get('question') or not payload.get('audience') or not isinstance(payload.get('budgets'), dict):
        _error('topic_input_invalid', 'topic input requires only question/audience/budgets')
    limits = {'max_depth': 2, 'max_subquestions': 3, 'max_rounds': 2, 'max_sources': 8,
              'max_requests': 12, 'max_text_bytes': 20 * 1024 * 1024, 'request_timeout_seconds': 30,
              'network_seconds': 600, 'max_expansions_per_round': 3, 'max_tokens': 14000}
    budgets = {**limits, **payload['budgets']}
    for key, cap in limits.items():
        value = budgets[key]
        if type(value) is not int or not 1 <= value <= cap:
            _error('topic_budget_invalid', f'{key} must be an integer in 1..{cap}')
    return {**payload, 'budgets': budgets, 'schema': 'question-research-topic-input.v1',
            'fixture_id': 'topic-' + _sha(json.dumps(payload, sort_keys=True).encode())[:16],
            'observed_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}


def _public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443}:
        _error('public_url_required', 'Only credential-free public HTTPS URLs are accepted')
    if parsed.hostname.lower() == 'localhost' or '.' not in parsed.hostname:
        _error('public_url_required', 'Local hosts are excluded')
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return
    if not address.is_global:
        _error('public_url_required', 'Local addresses are excluded')


def validate_captures(root, artifacts):
    ledger_path = root / 'acquisition-ledger.json'
    for artifact in artifacts.values():
        recorded = artifact.get('acquisition')
        if recorded:
            current = read_json(ledger_path) if ledger_path.exists() else {}
            count = len(recorded['requests'])
            if current.get('requests', [])[:count] != recorded['requests'] or current.get('bytes_read', -1) < recorded['bytes_read']:
                _error('topic_budget_ledger_drift', 'Acquisition budget ledger lost completed-stage accounting')
        for row in artifact.get('captures', []):
            path = (root / row['path']).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file() or _sha(path.read_bytes()) != row['sha256']:
                _error('topic_capture_drift', 'A completed stage capture changed or is missing')


def _observation(root, observation_path, stage, previous, operation):
    basis = root / 'artifacts' / previous
    expected = {'stage': stage, 'basis_artifact_sha256': _sha(basis.read_bytes()),
                'allowed_operation': operation, 'basis_artifact': str(basis),
                'boundary': 'Read the completed artifact first. No model memory as evidence; no prefilled sources in initial input.'}
    value = read_json(Path(observation_path)) if observation_path else {}
    if value.get('stage') != stage:
        _error('awaiting_codex_observation', json.dumps(expected))
    if value.get('basis_artifact_sha256') != expected['basis_artifact_sha256']:
        _error('observation_basis_drift', 'Observation does not bind the preceding stage bytes')
    return value


def _ledger(root):
    path = root / 'acquisition-ledger.json'
    return read_json(path) if path.exists() else {'requests': [], 'bytes_read': 0, 'network_seconds': 0.0}


class _LimitedResponse:
    """Resource guard around WCF's existing urllib transport, not a fetcher."""
    def __init__(self, response, ledger, root, limits):
        self.response, self.ledger, self.root, self.limits = response, ledger, root, limits
        self.read_bytes = 0

    def __getattr__(self, name):
        return getattr(self.response, name)

    def __enter__(self):
        self.response.__enter__()
        return self

    def __exit__(self, *args):
        return self.response.__exit__(*args)

    def read(self, size=-1):
        remaining = min(1024 * 1024 - self.read_bytes, self.limits['max_text_bytes'] - self.ledger['bytes_read'])
        if remaining <= 0:
            _error('topic_budget_exhausted', 'Text response byte budget reached')
        data = self.response.read(min(size, remaining + 1) if size >= 0 else remaining + 1)
        self.read_bytes += len(data)
        self.ledger['bytes_read'] += len(data)
        write_json(self.root / 'acquisition-ledger.json', self.ledger)
        if len(data) > remaining:
            _error('topic_budget_exhausted', 'Text response exceeded its 1 MiB cap')
        return data


def _wcf_read(root, url, round_index, budgets, wcf_root, max_os_threads, saved_capture_index=None):
    _public_url(url)
    key = _sha(canonical_reference(url).encode())[:16]
    path = root / 'captures' / (key + '.json')
    reservation = root / 'captures' / (key + '.request.json')
    if saved_capture_index is None and path.exists():
        expected_hash = read_json(reservation).get('result_sha256') if reservation.exists() else None
        if not expected_hash:
            for artifact_path in (root / 'artifacts').glob('*.json'):
                for row in read_json(artifact_path).get('captures', []):
                    if row['path'] == path.relative_to(root).as_posix():
                        expected_hash = row['sha256']
        if not expected_hash or _sha(path.read_bytes()) != expected_hash:
            _error('topic_capture_drift', 'Cached acquisition is not bound to a completed request or stage')
        saved = read_json(path)
        return _capture_row(root, path, saved, round_index, cache_hit=True)
    if saved_capture_index is None and reservation.exists():
        _error('request_outcome_unknown', 'An unfinished request reservation exists; automatic resend is forbidden')
    if saved_capture_index is not None:
        index_path = Path(saved_capture_index).resolve()
        index = read_json(index_path)
        rows = index.get('captures', [])
        matches = [row for row in rows if canonical_reference(row.get('url', '')) == canonical_reference(url)]
        if len(matches) != 1:
            _error('saved_capture_missing', 'Supply exactly one saved WCF capture for the requested URL; no network fallback')
        row = matches[0]
        source = (index_path.parent / row['path']).resolve()
        if not source.is_relative_to(index_path.parent) or not source.is_file():
            _error('saved_capture_path_invalid', 'Saved capture must stay inside the index directory')
        with source.open('rb') as handle:
            raw = handle.read(budgets['max_text_bytes'] + 1)
        ledger = _ledger(root)
        imports = ledger.setdefault('saved_imports', [])
        if _sha(raw) != row.get('sha256'):
            _error('saved_capture_drift', 'Saved capture exceeded budget or changed')
        saved = json.loads(raw)
        if canonical_reference(saved.get('final_url', '')) != canonical_reference(url):
            _error('saved_capture_url_mismatch', 'Requested URL must match saved capture provenance')
        record = {'url': url, 'sha256': row['sha256'], 'bytes': len(raw)}
        previous = [r for r in imports if canonical_reference(r['url']) == canonical_reference(url)]
        if previous and (len(previous) != 1 or previous[0] != record):
            _error('saved_capture_drift', 'Saved import identity changed')
        if not previous:
            if len(imports) >= budgets['max_sources'] or ledger['bytes_read'] + len(raw) > budgets['max_text_bytes']:
                _error('topic_budget_exhausted', 'Saved capture import exceeded source/byte budget')
            imports.append(record)
            ledger['bytes_read'] += len(raw)
            # Reserve once before materialization; replay repairs only missing
            # files from the same hash-bound source, without spending twice.
            write_json(root / 'acquisition-ledger.json', ledger)
        expected_bytes = json.dumps(saved, ensure_ascii=False, indent=2).encode('utf-8')
        if path.exists() and path.read_bytes() != expected_bytes:
            _error('topic_capture_drift', 'Imported capture changed; do not overwrite evidence')
        if reservation.exists():
            prior = read_json(reservation)
            if prior.get('status') != 'imported_saved_capture' or prior.get('source_sha256') != row['sha256']:
                _error('request_outcome_unknown', 'Do not replace a different acquisition reservation')
        if not path.exists():
            write_json(path, saved)
        write_json(reservation, {'url': url, 'round': round_index, 'status': 'imported_saved_capture',
                                'source_sha256': row['sha256'], 'result_sha256': _sha(path.read_bytes()),
                                'network_called': False})
        result = _capture_row(root, path, saved, round_index, cache_hit=True)
        result['acquisition_mode'] = 'saved_capture_import'
        return result
    if not wcf_root or not (Path(wcf_root) / 'web_content_fetcher/core.py').is_file():
        _error('wcf_unavailable', 'Supply the registered WCF package root; no fallback service is started')
    try:
        import psutil
    except ImportError:
        _error('resource_probe_unavailable', 'The topic extra requires psutil for fail-closed resource checks')
    if max_os_threads < 1 or psutil.Process().num_threads() > max_os_threads:
        _error('resource_budget_exceeded', 'OS thread baseline exceeds the explicitly authorized ceiling')
    ledger = _ledger(root)
    if len(list((root / 'captures').glob('*.json'))) // 2 >= budgets['max_sources']:
        _error('topic_budget_exhausted', 'Source budget reached')
    sys.path.insert(0, str(wcf_root))
    from web_content_fetcher.core import FetchRequest, fetch_content
    write_json(reservation, {'url': url, 'round': round_index, 'requested_at': _now(), 'status': 'reserved_no_auto_resend'})
    active = True
    started = time.monotonic()

    def audit(event, args):
        if not active or event != 'urllib.Request':
            return
        request_url = args[0]
        _public_url(request_url)
        if len(ledger['requests']) >= budgets['max_requests'] or ledger['network_seconds'] + time.monotonic() - started >= budgets['network_seconds']:
            _error('topic_budget_exhausted', 'HTTP request/time budget reached')
        ledger['requests'].append({'url': request_url, 'round': round_index, 'started_at': _now()})
        write_json(root / 'acquisition-ledger.json', ledger)

    sys.addaudithook(audit)
    previous_open, previous_timeout = urllib.request.urlopen, socket.getdefaulttimeout()

    def limited_open(*args, **kwargs):
        kwargs['timeout'] = min(float(kwargs.get('timeout') or budgets['request_timeout_seconds']), budgets['request_timeout_seconds'])
        return _LimitedResponse(previous_open(*args, **kwargs), ledger, root, budgets)

    urllib.request.urlopen = limited_open
    socket.setdefaulttimeout(budgets['request_timeout_seconds'])
    try:
        result = fetch_content(FetchRequest(url=url, backend='direct', extractor='builtin',
                               max_bytes=1024 * 1024, timeout_seconds=budgets['request_timeout_seconds'],
                               archive_dir=str(root / 'wcf-archives'), check_robots=True))
        saved = result.to_dict()
    except Exception as exc:
        saved = {'requested_url': url, 'final_url': url, 'status': 'failed', 'transport_ok': False,
                 'content_ok': False, 'extracted_text': '', 'fetched_at': _now(),
                 'errors': [f'{type(exc).__name__}: {exc}']}
    finally:
        active = False
        urllib.request.urlopen = previous_open
        socket.setdefaulttimeout(previous_timeout)
        ledger['network_seconds'] += time.monotonic() - started
        try:
            import psutil
            process = psutil.Process()
            memory = process.memory_info()
            ledger['resource_observation'] = {'pid': process.pid, 'threads': process.num_threads(),
                                              'python_threads': len(threading.enumerate()),
                                              'authorized_max_os_threads': max_os_threads,
                                              'rss_bytes': memory.rss, 'peak_rss_bytes': getattr(memory, 'peak_wset', memory.rss)}
        except ImportError:
            ledger['resource_observation'] = {'status': 'unknown'}
        write_json(root / 'acquisition-ledger.json', ledger)
    write_json(path, saved)
    write_json(reservation, {**read_json(reservation), 'status': 'completed', 'result_sha256': _sha(path.read_bytes())})
    resource = ledger['resource_observation']
    if resource.get('threads', 0) > max_os_threads or resource.get('peak_rss_bytes', 0) > 1024 * 1024 * 1024:
        _error('resource_budget_exceeded', 'Capture saved; stop before any further work because resource ceiling was exceeded')
    return _capture_row(root, path, saved, round_index, cache_hit=False)


def _capture_row(root, path, capture, round_index, cache_hit):
    url = capture.get('final_url') or capture['requested_url']
    return {'source_id': 's-' + _sha(canonical_reference(url).encode())[:12],
            'url': url, 'path': path.relative_to(root).as_posix(), 'sha256': _sha(path.read_bytes()),
            'round': round_index, 'cache_hit': cache_hit, 'read_at': _now(),
            'status': capture['status'], 'content_ok': capture.get('content_ok', False),
            'text_chars': len(capture.get('extracted_text') or '')}


def _read_batch(root, reads, round_index, fixture, wcf_root, max_os_threads, saved_capture_index=None):
    if not isinstance(reads, list) or not 1 <= len(reads) <= fixture['budgets']['max_expansions_per_round']:
        _error('topic_budget_invalid', 'Read batch must fit the expansion budget')
    captures, seen = [], set()
    for row in reads:
        url = row.get('url', '')
        key = canonical_reference(url)
        if key in seen:
            continue
        seen.add(key)
        options = {'saved_capture_index': saved_capture_index} if saved_capture_index is not None else {}
        captures.append(_wcf_read(root, url, round_index, fixture['budgets'], wcf_root, max_os_threads, **options))
    return captures


def _body(root, captures, source_id, quote):
    source = next((row for row in captures if row['source_id'] == source_id), None)
    if not source:
        _error('observation_source_missing', 'Observation source was not acquired in a completed stage')
    capture = read_json(root / source['path'])
    if not isinstance(quote, str) or not quote.strip() or quote not in capture.get('extracted_text', ''):
        _error('observation_quote_missing', 'Observation must quote the acquired source exactly')
    return capture


def _verify_located_passage(root, captures, source_id, quote, saved, passage):
    from .passage_retrieval import verify_passage
    source = next(row for row in captures if row['source_id'] == source_id)
    imports = [row for row in _ledger(root).get('saved_imports', [])
               if canonical_reference(row['url']) == canonical_reference(source['url'])]
    if len(imports) != 1 or passage.get('quote') != quote:
        _error('passage_input_binding_missing', 'Located excerpt requires its exact saved import and quote')
    verify_passage(saved, passage, input_sha256=imports[0]['sha256'], capture=source)


def topic_builders(root, observation_path, wcf_root, *, max_os_threads=1, saved_capture_index=None):
    from . import bounded_deep_loop as core

    def intake(fixture, artifacts):
        return {'schema': 'question-research-topic-intake.v1', 'question': fixture['question'],
                'audience': fixture['audience'], 'budgets': fixture['budgets'], 'input_kind': 'topic_only',
                'subquestions': [], 'sources': [], 'claims': [], 'evidence': [],
                'next_action': 'Codex selects public documentation URLs using only the topic; WCF must read them before evidence or subtopics exist.'}

    def acquire(fixture, artifacts):
        observation = _observation(root, observation_path, 'source_admission', '01-intake.json', 'initial_public_read')
        if (observation.get('automation_context', {}).get('profile') in {'saved-excerpt-observations.v1', 'question-passage-observations.v2'}
                and observation.get('reads') == [] and observation.get('stop_reason') in
                {'budget_exhausted', 'insufficient_evidence', 'no_relevant_passage', 'insufficient_query_terms'}):
            ledger = _ledger(root)
            write_json(root / 'acquisition-ledger.json', ledger)
            return {'schema': 'question-research-topic-acquisition.v1', 'round': 0, 'captures': [],
                    'codex_observation': observation, 'network_called': False, 'acquisition': ledger,
                    'stop_reason': observation['stop_reason']}
        captures = _read_batch(root, observation.get('reads'), 1, fixture, wcf_root, max_os_threads, saved_capture_index)
        return {'schema': 'question-research-topic-acquisition.v1', 'round': 1, 'captures': captures,
                'codex_observation': observation, 'network_called': any(not row['cache_hit'] for row in captures),
                'acquisition': _ledger(root), 'next_action': 'Read saved source bodies; propose evidence-grounded gaps and targeted followup URLs.'}

    def deepen(fixture, artifacts):
        first = artifacts['source_admission']['captures']
        has_text = any((read_json(root / row['path']).get('extracted_text') or '').strip() for row in first)
        if not has_text or fixture['budgets']['max_rounds'] < 2:
            return {'captures': [], 'subquestions': [],
                    'stop_reason': artifacts['source_admission'].get('stop_reason') or
                                   ('access_blocked' if not has_text else 'budget_exhausted')}
        observation = _observation(root, observation_path, 'evidence_analysis', '02-source_admission.json', 'evidence_grounded_followup')
        topics, seen = [], set()
        for topic in observation.get('subquestions', []):
            saved = _body(root, first, topic.get('basis_source_id'), topic.get('basis_quote'))
            if observation.get('automation_context', {}).get('profile') == 'question-passage-observations.v2':
                _verify_located_passage(root, first, topic['basis_source_id'], topic['basis_quote'], saved, topic['basis_passage'])
            if type(topic.get('depth')) is not int or not 1 <= topic['depth'] <= fixture['budgets']['max_depth']:
                _error('topic_budget_invalid', 'Subtopic depth exceeds budget')
            key = normalize_topic(topic.get('text'))
            if key not in seen:
                seen.add(key)
                topics.append(topic)
        if not 1 <= len(topics) <= fixture['budgets']['max_subquestions'] or len({row['subquestion_id'] for row in topics}) != len(topics):
            _error('topic_budget_invalid', 'Unique grounded subtopics must fit budget')
        topic_ids = {row['subquestion_id'] for row in topics}
        reads = observation.get('reads') or []
        if not reads and observation.get('stop_reason') in {'no_new_evidence', 'budget_exhausted'}:
            return {'schema': 'question-research-topic-deepening.v1', 'round': 1, 'captures': [],
                    'subquestions': topics, 'codex_observation': observation, 'network_called': False,
                    'stop_reason': observation['stop_reason'], 'acquisition': _ledger(root)}
        if not reads or any(row.get('subquestion_id') not in topic_ids for row in reads):
            _error('ungrounded_followup', 'Every followup read must bind a newly grounded subtopic')
        captures = _read_batch(root, reads, 2, fixture, wcf_root, max_os_threads, saved_capture_index)
        return {'schema': 'question-research-topic-deepening.v1', 'round': 2, 'captures': captures,
                'subquestions': topics, 'codex_observation': observation,
                'network_called': any(not row['cache_hit'] for row in captures), 'acquisition': _ledger(root)}

    def synthesize(fixture, artifacts):
        first, second = artifacts['source_admission'], artifacts['evidence_analysis']
        if not second.get('subquestions'):
            return {'schema': 'question-research-guarded-synthesis.v1', 'question': fixture['question'],
                    'status': 'blocked_insufficient_evidence', 'statements': [], 'blocking_gates': [second['stop_reason']],
                    'stop_reason': second['stop_reason'], 'finalization_authorized': False, 'human_review_required': True,
                    'topic_brief': {'schema': core.ARTICLE_BRIEF_CONTRACT, 'source_material': 'topic_driven_public_reads',
                                    'topic_candidates': [], 'sections': [], 'review_packet': {'status': 'pending_human_review'},
                                    'search_stop_reason': second['stop_reason'], 'authority': {'publish_authorized': False}}}
        observation = _observation(root, observation_path, 'guarded_synthesis', '03-evidence_analysis.json', 'claims_from_acquired_text')
        profile = observation.get('automation_context', {}).get('profile')
        mechanical = profile in {'saved-excerpt-observations.v1', 'question-passage-observations.v2'}
        located = profile == 'question-passage-observations.v2'
        captures = list({row['source_id']: row for row in [*second['captures'], *first['captures']]}.values())
        if mechanical:
            # Content aliases must retain the earliest acquisition round. A
            # later mirror cannot move first-round evidence into round two.
            captures.sort(key=lambda row: row['round'])
        sources = []
        for row in captures:
            capture = read_json(root / row['path'])
            if not (capture.get('extracted_text') or '').strip():
                continue
            body = capture['extracted_text']
            sources.append({'source_id': row['source_id'], 'title': capture.get('title') or row['url'],
                            'canonical_ref': row['url'], 'source_type': 'saved_document' if mechanical else 'public_documentation',
                            'review_status': 'candidate', 'quality': 'unknown' if mechanical else 'good',
                            'freshness': 'unknown' if mechanical else 'current',
                            'provenance_kind': 'synthetic_fixture' if capture.get('fixture') else 'saved_capture',
                            'synthetic': bool(capture.get('fixture')),
                            'content': body, 'content_sha256': _sha(body.encode()),
                            'archive_path': row['path'], 'archive_sha256': row['sha256'], 'capture_scope': 'excerpt_only',
                            'token_cost': ((sum(len(link['text']) for c in observation.get('claims', []) for link in c.get('evidence', [])
                                                if link['source_id'] == row['source_id']) if located else len(body)) + 2) // 3,
                            'discovered_round': row['round']})
        claims, evidence = [], []
        for index, claim in enumerate(observation.get('claims', []), 1):
            cid = f'c{index}'
            claims.append({'claim_id': cid, 'subquestion_id': claim['subquestion_id'], 'text': claim['text'],
                           'claim_origin': 'deterministic_source_excerpt' if mechanical else 'codex_interpretation_after_public_read'})
            for link in claim.get('evidence', []):
                saved = _body(root, captures, link['source_id'], link['text'])
                if located:
                    _verify_located_passage(root, captures, link['source_id'], link['text'], saved, link['passage'])
                source = next(row for row in sources if row['source_id'] == link['source_id'])
                evidence.append({'evidence_id': f'e{len(evidence)+1}', 'claim_id': cid, 'source_id': link['source_id'],
                                 'text': link['text'], 'relation': link.get('relation', 'supports'), 'evidence_type': 'source_claim',
                                 'status': 'candidate', 'review_status': 'candidate', 'discovered_round': source['discovered_round'],
                                 **({'passage': link['passage']} if located else {})})
        if not 1 <= len(claims) <= 12:
            _error('observation_claim_budget', 'Provide 1..12 source-grounded candidate claims')
        material = {**fixture, 'schema': core.PUBLIC_INPUT_CONTRACT, 'rounds_completed': second.get('round', 2),
                    'subquestions': [{**row, 'gap_score': 1, 'token_cost': 50} for row in second['subquestions']],
                    'sources': sources, 'claims': claims, 'evidence': evidence}
        if mechanical:
            material['automation_context'] = observation['automation_context']
        core._validate_fixture_semantics(material)
        core._validate_public_archives(material, root)
        derived = {}
        for name, builder in [('intake', core._build_intake), ('source_admission', core._build_source_admission), ('evidence_analysis', core._build_evidence_analysis)]:
            derived[name] = builder(material, derived)
        if derived['evidence_analysis']['contradictions']:
            derived['evidence_analysis']['stop_reason'] = 'fact_conflict'
        elif second['captures'] and not any((read_json(root / row['path']).get('extracted_text') or '').strip() for row in second['captures']):
            derived['evidence_analysis']['stop_reason'] = 'access_blocked'
        elif second.get('stop_reason') in {'no_new_evidence', 'budget_exhausted'}:
            derived['evidence_analysis']['stop_reason'] = second['stop_reason']
        derived['guarded_synthesis'] = core._build_guarded_synthesis(material, derived)
        if mechanical:
            synthesis = derived['guarded_synthesis']
            synthesis['automation_context'] = observation['automation_context']
            synthesis['research_complete'] = False
            synthesis['unresolved_gaps'] = observation.get('unresolved_gaps', [])
            synthesis['warnings'].extend(observation['automation_context'].get('limitations', []))
            for statement in synthesis['statements']:
                statement['qualification'] = 'lexical_passage_candidate_semantic_support_not_assessed' if located else 'exact_excerpt_only_semantic_analysis_not_run'
        brief = core._build_article_brief(material, derived)
        brief['source_material'] = 'topic_driven_public_reads'
        brief['subquestions'] = second['subquestions']
        brief['source_independence'] = {'publishers_inferred_from_domains': sorted({urlsplit(row['canonical_ref']).hostname for row in sources}),
                                        'independent_crosscheck': observation.get('independent_crosscheck', 'not_established'),
                                        'same_domain_pages_are_not_independent': True}
        from research_workflow.quality import quality_for_report
        quality = quality_for_report({'claims': [{'id': row['claim_id'], 'text': row['text'], 'verdict': 'partial',
                                                   'evidence_ids': row['evidence_ids']} for row in derived['evidence_analysis']['claims']],
                                      'sources': [{'id': row['source_id'], 'url': row['canonical_ref']} for row in sources],
                                      'evidence': [{'id': row['evidence_id'], 'source_id': row['source_id'],
                                                    'quote_or_paraphrase': row['text']} for row in evidence]})
        return {**derived['guarded_synthesis'], 'topic_brief': brief, 'codex_observation': observation,
                'derived_material': material, 'derived_analysis': derived['evidence_analysis'], 'arw_quality': quality}

    def brief(fixture, artifacts):
        return artifacts['guarded_synthesis']['topic_brief']

    return {'intake': intake, 'source_admission': acquire, 'evidence_analysis': deepen,
            'guarded_synthesis': synthesize, 'article_brief': brief}
