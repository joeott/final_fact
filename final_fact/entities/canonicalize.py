"""
Entity canonicalization (Kunda-style fuzzy merging).

Adapted from fact_improve/analysis/entity_canonicalizer.py, but made deterministic for final_fact.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from rapidfuzz import fuzz, process


THRESHOLDS: Dict[str, float] = {
    "PERSON": 0.85,
    "ORGANIZATION": 0.90,
    "PLACE": 0.85,
    "DATE": 1.0,
    "PHONE": 0.95,
    "EMAIL": 0.95,
    "ADDRESS": 0.85,
    "OTHER": 0.90,
}


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def deterministic_canonical_id(project_uuid: str, entity_type: str, canonical_text: str) -> str:
    try:
        ns = uuid.UUID(project_uuid)
    except Exception:
        ns = uuid.uuid5(uuid.NAMESPACE_DNS, project_uuid)
    key = f"entity::{entity_type}::{normalize_text(canonical_text)}"
    return str(uuid.uuid5(ns, key))


@dataclass(frozen=True)
class RawEntity:
    entity_type: str
    text: str
    chunk_uuid: str


@dataclass
class CanonicalEntity:
    canonical_id: str
    project_uuid: str
    entity_type: str
    canonical_text: str
    variants: List[str] = field(default_factory=list)
    mention_count: int = 0
    chunk_uuids: List[str] = field(default_factory=list)


def _exact_clusters(entities: List[RawEntity]) -> List[List[RawEntity]]:
    by_norm: Dict[str, List[RawEntity]] = {}
    for e in entities:
        by_norm.setdefault(normalize_text(e.text), []).append(e)
    return list(by_norm.values())


def _fuzzy_clusters(entities: List[RawEntity], threshold: float) -> List[List[RawEntity]]:
    if len(entities) <= 1:
        return [entities] if entities else []

    remaining = entities[:]
    clusters: List[List[RawEntity]] = []
    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        if remaining:
            matches = process.extract(
                seed.text,
                [e.text for e in remaining],
                scorer=fuzz.token_sort_ratio,
                score_cutoff=threshold * 100,
                limit=None,
            )
            matched = set()
            for _, _, idx in matches:
                if 0 <= idx < len(remaining):
                    cluster.append(remaining[idx])
                    matched.add(idx)
            remaining = [e for i, e in enumerate(remaining) if i not in matched]
        clusters.append(cluster)
    return clusters


def canonicalize(project_uuid: str, raw_entities: List[RawEntity]) -> List[CanonicalEntity]:
    by_type: Dict[str, List[RawEntity]] = {}
    for e in raw_entities:
        et = (e.entity_type or "OTHER").upper()
        by_type.setdefault(et, []).append(e)

    out: List[CanonicalEntity] = []
    for etype, ents in by_type.items():
        thresh = THRESHOLDS.get(etype, 0.85)
        exact = _exact_clusters(ents)
        fuzzy: List[List[RawEntity]] = []
        for c in exact:
            if len(c) == 1:
                fuzzy.append(c)
            else:
                fuzzy.extend(_fuzzy_clusters(c, thresh))

        for cluster in fuzzy:
            # choose most frequent surface form
            counts: Dict[str, int] = {}
            for e in cluster:
                counts[e.text] = counts.get(e.text, 0) + 1
            canonical_text = sorted(counts.items(), key=lambda kv: (-kv[1], len(kv[0])))[0][0]
            cid = deterministic_canonical_id(project_uuid, etype, canonical_text)
            ce = CanonicalEntity(
                canonical_id=cid,
                project_uuid=project_uuid,
                entity_type=etype,
                canonical_text=canonical_text,
                variants=sorted(set(counts.keys())),
                mention_count=len(cluster),
                chunk_uuids=sorted(set(e.chunk_uuid for e in cluster)),
            )
            out.append(ce)
    return out

