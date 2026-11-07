"""Bounded provenance adapter over QRP chunks and ARW BM25, never a fact check."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from .research_progress import canonical_reference
from .web_fetch_bridge import _split_chunk_spans

PROFILE = 'question-passage-observations.v2'
MAX_CORPUS_BYTES = 8 * 1024 * 1024
MAX_BODY_CHARS = 131072
MAX_CHUNKS_PER_SOURCE = 512
MAX_PER_SOURCE = 2
EXTRA_STOPWORDS = {'how', 'what', 'which', 'why', 'when', 'where', 'does', 'do', 'did',
                  'would', 'could', 'should', 'please', 'about', '如何', '什么', '哪些',
                  '为何', '为什么', '怎样', '是否', '多少', '请问', '进行', '一个', '的', '了'}
_segmenter = None


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _terms(text):
    from research_workflow.factcheck import _tokens
    global _segmenter
    if re.search(r'[\u4e00-\u9fff]', text):
        if _segmenter is None:
            try:
                import jieba
            except ImportError as exc:
                raise ValueError('chinese_dictionary_tokenizer_unavailable') from exc
            jieba.setLogLevel(logging.ERROR)
            _segmenter = jieba.Tokenizer()
        # Installed dictionary segmentation only; the HMM/model fallback is off.
        text = ' '.join(_segmenter.cut(text, HMM=False))
    return [term for term in _tokens(text) if term not in EXTRA_STOPWORDS]


def _scope(saved):
    declared = saved.get('capture_completeness', {}).get('status', 'unknown')
    if saved.get('status') == 'partial' or not saved.get('content_ok'):
        return 'partial', declared
    return ('full' if declared in {'full', 'complete'} else 'unknown'), declared


def locate(index_path, rows, question):
    """Return only bounded matches/diagnostics; full bodies never enter prompts.

    Inventory bytes are an explicit offline corpus, not new acquisition. Source
    import budgets remain enforced by the existing QRP acquisition ledger.
    """
    from research_workflow.models import Evidence
    from research_workflow.sparse_retrieval import retrieve_evidence_bm25
    query_terms = sorted(set(_terms(question)))
    result = {'profile': PROFILE, 'query': question, 'query_terms': query_terms,
              'method': 'QRP_280_240_chunks+ARW_BM25', 'semantic_analysis': 'not_run',
              'score_meaning': 'lexical_order_only_not_confidence_or_support',
              'abstention_scope': 'lexical_threshold_only_not_semantic_irrelevance',
              'sources': [], 'passages': [], 'scan_budget_exhausted': False,
              'bounds': {'corpus_bytes': MAX_CORPUS_BYTES, 'body_chars': MAX_BODY_CHARS,
                         'chunks_per_source': MAX_CHUNKS_PER_SOURCE, 'passages_per_source': MAX_PER_SOURCE}}
    if not query_terms or len(query_terms) > 32:
        return {**result, 'abstention_reason': 'insufficient_query_terms'}
    candidates, by_id, used = [], {}, 0
    for row in sorted(rows, key=lambda r: canonical_reference(r['url'])):
        path = (index_path.parent / row['path']).resolve()
        if not path.is_relative_to(index_path.parent.resolve()):
            raise ValueError('passage_input_outside_inventory')
        size = path.stat().st_size
        source_id = 's-' + digest(canonical_reference(row['url']).encode())[:12]
        info = {'source_id': source_id, 'url': row['url'], 'input_path': row['path'],
                'input_capture_sha256': row['sha256'], 'input_bytes': size}
        if used + size > MAX_CORPUS_BYTES:
            result['sources'].append({**info, 'scan_status': 'unscanned_budget'})
            result['scan_budget_exhausted'] = True
            continue
        raw = path.read_bytes()
        if digest(raw) != row['sha256']:
            raise ValueError('passage_input_drift')
        used += size
        saved = json.loads(raw)
        if canonical_reference(saved.get('final_url', '')) != canonical_reference(row['url']):
            raise ValueError('passage_url_mismatch')
        body = saved.get('extracted_text') or ''
        if not isinstance(body, str):
            raise ValueError('passage_body_must_be_text')
        scope, declared = _scope(saved)
        body_sha = digest(body.encode('utf-8'))
        spans = list(_split_chunk_spans(body, limit=MAX_CHUNKS_PER_SOURCE + 1))
        limited = len(body) > MAX_BODY_CHARS or len(spans) > MAX_CHUNKS_PER_SOURCE
        result['scan_budget_exhausted'] |= limited
        scanned_spans = [span for span in spans[:MAX_CHUNKS_PER_SOURCE] if span['start'] < MAX_BODY_CHARS]
        info.update(body_sha256=body_sha, body_chars=len(body), completeness=scope,
                    declared_completeness=declared, capture_status=saved.get('status'),
                    synthetic=bool(saved.get('fixture')), fact_verified=False,
                    scan_status='partial_budget' if limited else 'scanned',
                    scanned_windows=len(scanned_spans),
                    scan_end_offset=max((min(s['paragraph_end'], s['end'] + 80, MAX_BODY_CHARS)
                                         for s in scanned_spans), default=0))
        result['sources'].append(info)
        for span in scanned_spans:
            # Show an exact context halo so a negation just before the matched
            # window is not silently discarded. Incomplete context is explicit.
            start = max(span['paragraph_start'], span['start'] - 80)
            end = min(span['paragraph_end'], span['end'] + 80, MAX_BODY_CHARS)
            quote = body[start:end]
            identity = f"{source_id}:{row['sha256']}:{body_sha}:{start}:{end}"
            pid = 'passage-' + digest(identity.encode())[:20]
            paragraph_id = 'paragraph-' + digest(f"{body_sha}:{span['paragraph_start']}:{span['paragraph_end']}".encode())[:20]
            tokens = _terms(quote)
            matched = sorted(set(query_terms).intersection(tokens))
            coverage = len(matched) / len(query_terms)
            record = {**info, 'passage_id': pid, 'paragraph_id': paragraph_id,
                'start': start, 'end': end, 'offset_unit': 'python_unicode_codepoint', 'end_exclusive': True,
                'paragraph_start': span['paragraph_start'], 'paragraph_end': span['paragraph_end'],
                'quote': quote, 'matched_terms': matched, 'query_term_coverage': round(coverage, 4),
                'context_truncated': start > span['paragraph_start'] or end < span['paragraph_end'],
                'context_left_truncated': start > span['paragraph_start'],
                'context_right_truncated': end < span['paragraph_end'],
                'polarity_terms_present': bool(re.search(r'\b(?:not|no|never|without|cannot)\b|不|未|无|没有', quote, re.I)),
                'polarity_assessment': 'not_run', 'status': 'lexical_candidate'}
            by_id[pid] = record
            candidates.append(Evidence(source_id=source_id, id=pid,
                quote_or_paraphrase=' '.join(tokens), extraction_method='dictionary_tokens_for_ranking_only'))
    # BM25 magnitudes depend on corpus size/frequency. Require positive overlap
    # here, then use distinct-query coverage below as the explicit lexical gate.
    matches = retrieve_evidence_bm25(' '.join(query_terms), candidates, limit=len(candidates), min_score=1e-12)
    ranked = sorted(matches, key=lambda m: (-m.score, m.evidence.source_id,
                                           by_id[m.evidence.id]['start'], by_id[m.evidence.id]['end']))
    selected = []
    for match in ranked:
        row = by_id[match.evidence.id]
        if len(row['matched_terms']) < min(2, len(query_terms)) or row['query_term_coverage'] < 0.5:
            continue
        same_source = [p for p in selected if p['source_id'] == row['source_id']]
        if len(same_source) >= MAX_PER_SOURCE or any(
                p['paragraph_id'] == row['paragraph_id'] and max(p['start'], row['start']) < min(p['end'], row['end'])
                for p in same_source):
            continue
        selected.append({**row, 'score': match.score})
    result['passages'] = selected
    result['scanned_input_bytes'] = used
    result['abstention_reason'] = ('budget_exhausted' if result['scan_budget_exhausted'] else
                                   'insufficient_evidence' if ranked else 'no_relevant_passage') if not selected else None
    return result


def verify_passage(saved, passage, *, input_sha256=None, capture=None):
    body = saved.get('extracted_text') or ''
    start, end = passage.get('start'), passage.get('end')
    url = canonical_reference(saved.get('final_url', ''))
    source_id = 's-' + digest(url.encode())[:12]
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(body)
            or digest(body.encode('utf-8')) != passage.get('body_sha256')
            or body[start:end] != passage.get('quote')
            or source_id != passage.get('source_id')
            or url != canonical_reference(passage.get('url', ''))
            or (input_sha256 is not None and input_sha256 != passage.get('input_capture_sha256'))):
        raise ValueError('passage_position_or_version_drift')
    if capture is not None and (capture['source_id'] != passage.get('source_id')
            or capture['sha256'] != passage.get('capture_sha256')
            or capture['path'] != passage.get('capture_path')):
        raise ValueError('passage_capture_binding_drift')
    paragraph_start, paragraph_end = passage.get('paragraph_start'), passage.get('paragraph_end')
    identity = f"{source_id}:{passage.get('input_capture_sha256')}:{passage['body_sha256']}:{start}:{end}"
    paragraph_identity = f"{passage['body_sha256']}:{paragraph_start}:{paragraph_end}"
    if (type(paragraph_start) is not int or type(paragraph_end) is not int
            or not 0 <= paragraph_start <= start < end <= paragraph_end <= len(body)
            or passage.get('passage_id') != 'passage-' + digest(identity.encode())[:20]
            or passage.get('paragraph_id') != 'paragraph-' + digest(paragraph_identity.encode())[:20]
            or passage.get('offset_unit') != 'python_unicode_codepoint' or passage.get('end_exclusive') is not True):
        raise ValueError('passage_identity_or_paragraph_drift')
    return True
