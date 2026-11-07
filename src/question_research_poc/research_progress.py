"""Pure identity and progress calculations shared by the existing research loops.

Novelty is not truth: these counters never verify evidence or authorize synthesis.
Topic normalization is deliberately conservative; explicit dedupe_key values can
group paraphrases after the caller has reviewed their meaning.
"""
from __future__ import annotations

import hashlib
import unicodedata
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_topic(value: Any) -> str:
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ' '.join(value.split()).rstrip(' ?？!！。')


def canonical_reference(value: Any) -> str:
    text = str(value or '').strip()
    parts = urlsplit(text)
    if parts.scheme.lower() not in {'http', 'https'}:
        return text
    # Host/scheme are insensitive; URL paths and meaningful query values are not.
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith('utm_') and key.lower() not in {'fbclid', 'gclid'}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or '/', urlencode(query), ''))


def evidence_snapshot(sources: list[dict], claims: list[dict], evidence: list[dict]) -> dict[str, set]:
    source_keys = {}
    for item in sources:
        body_hash = item.get('content_sha256') or item.get('extracted_sha256')
        if not body_hash and item.get('content'):
            body_hash = hashlib.sha256(str(item['content']).encode()).hexdigest()
        identity = ('body', str(body_hash)) if body_hash else ('ref', canonical_reference(item.get('canonical_ref') or item.get('url') or item.get('path')))
        if identity[1]:
            source_keys[str(item.get('source_id') or item.get('id'))] = identity
    claim_keys = {str(item.get('claim_id') or item.get('id')): normalize_topic(item.get('text') or item.get('claim')) for item in claims}
    facts = set()
    relations: dict[str, set[str]] = {}
    for item in evidence:
        if item.get('evidence_type') == 'agent_inference':
            continue
        source = source_keys.get(str(item.get('source_id')))
        claim = claim_keys.get(str(item.get('claim_id')))
        text = ' '.join(str(item.get('text') or item.get('quote') or item.get('excerpt') or item.get('quote_or_note') or '').split())
        relation = str(item.get('relation') or item.get('stance') or 'context')
        if not source or not claim or not text:
            continue
        facts.add((claim, source, relation, text))
        relations.setdefault(claim, set()).add(relation)
    conflicts = {claim for claim, values in relations.items() if {'supports', 'contradicts'} <= values}
    return {'sources': set(source_keys.values()), 'evidence': facts, 'conflicts': conflicts}


def progress_delta(before: dict[str, set], after: dict[str, set]) -> dict[str, Any]:
    added = len(after['evidence'] - before['evidence'])
    conflicts_added = len(after['conflicts'] - before['conflicts'])
    conflicts_removed = len(before['conflicts'] - after['conflicts'])
    return {
        'new_unique_sources': len(after['sources'] - before['sources']),
        'new_unique_evidence': added,
        'removed_unique_evidence': len(before['evidence'] - after['evidence']),
        'conflicts_added': conflicts_added,
        'conflicts_removed': conflicts_removed,
        'meaningful_gain': bool(added or conflicts_added or conflicts_removed),
        'interpretation': 'novel_cited_material_or_conflict_change_not_fact_verification',
    }
