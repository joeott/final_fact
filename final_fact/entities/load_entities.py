"""
Load canonical entities and relationships into Neo4j.
"""

from __future__ import annotations

import itertools
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .canonicalize import CanonicalEntity, RawEntity, canonicalize
from ..graph.neo4j_client import Neo4jClient


def fetch_raw_entities_from_chunks(
    *,
    client: Neo4jClient,
    project_uuid: str,
    limit_chunks: Optional[int] = None,
) -> List[RawEntity]:
    cypher = """
    MATCH (c:CaseChunk)
    WHERE c.project_uuid = $project_uuid
      AND c.entities_json IS NOT NULL AND c.entities_json <> ''
    RETURN c.chunk_uuid as chunk_uuid, c.entities_json as entities_json
    """
    if limit_chunks:
        cypher += f" LIMIT {int(limit_chunks)}"

    rows = client.write(cypher, {"project_uuid": project_uuid})
    out: List[RawEntity] = []
    for r in rows:
        chunk_uuid = r["chunk_uuid"]
        try:
            ents = json.loads(r["entities_json"])
        except Exception:
            continue
        for e in ents or []:
            et = (e.get("entity_type") or "OTHER").upper()
            txt = (e.get("text") or "").strip()
            if not txt:
                continue
            out.append(RawEntity(entity_type=et, text=txt, chunk_uuid=chunk_uuid))
    return out


def upsert_canonical_entities(
    *,
    client: Neo4jClient,
    entities: List[CanonicalEntity],
) -> int:
    rows = []
    for e in entities:
        rows.append(
            {
                "canonical_id": e.canonical_id,
                "project_uuid": e.project_uuid,
                "entity_type": e.entity_type,
                "canonical_text": e.canonical_text,
                "variants": e.variants,
                "mention_count": e.mention_count,
            }
        )

    client.write(
        """
        UNWIND $rows AS row
        MERGE (e:CanonicalEntity {canonical_id: row.canonical_id})
        SET e.project_uuid = row.project_uuid,
            e.entity_type = row.entity_type,
            e.canonical_text = row.canonical_text,
            e.variants = row.variants,
            e.mention_count = row.mention_count
        """,
        {"rows": rows},
    )
    return len(rows)


def upsert_mentions(
    *,
    client: Neo4jClient,
    entities: List[CanonicalEntity],
) -> int:
    rows = []
    for e in entities:
        for cu in e.chunk_uuids:
            rows.append({"canonical_id": e.canonical_id, "chunk_uuid": cu})

    client.write(
        """
        UNWIND $rows AS row
        MATCH (e:CanonicalEntity {canonical_id: row.canonical_id})
        MATCH (c:CaseChunk {chunk_uuid: row.chunk_uuid})
        MERGE (e)-[:MENTIONED_IN]->(c)
        """,
        {"rows": rows},
    )
    return len(rows)


def upsert_cooccurrence(
    *,
    client: Neo4jClient,
    project_uuid: str,
    limit_chunks: Optional[int] = None,
) -> int:
    """
    Compute CO_OCCURS_WITH from chunk mentions.

    We compute in Python for controllability and then upsert edges.
    """
    cypher = """
    MATCH (c:CaseChunk)
    WHERE c.project_uuid = $project_uuid
    OPTIONAL MATCH (e:CanonicalEntity)-[:MENTIONED_IN]->(c)
    WITH c, collect(DISTINCT e.canonical_id) as eids
    RETURN c.chunk_uuid as chunk_uuid, eids
    """
    if limit_chunks:
        cypher += f" LIMIT {int(limit_chunks)}"
    rows = client.write(cypher, {"project_uuid": project_uuid})

    pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for r in rows:
        eids = [x for x in (r.get("eids") or []) if x]
        if len(eids) < 2:
            continue
        eids = sorted(set(eids))
        for a, b in itertools.combinations(eids, 2):
            pair_counts[(a, b)] += 1

    updates = [{"a": a, "b": b, "count": cnt} for (a, b), cnt in pair_counts.items()]
    if not updates:
        return 0

    client.write(
        """
        UNWIND $rows AS row
        MATCH (a:CanonicalEntity {canonical_id: row.a})
        MATCH (b:CanonicalEntity {canonical_id: row.b})
        MERGE (a)-[r:CO_OCCURS_WITH]->(b)
        SET r.count = row.count
        """,
        {"rows": updates},
    )
    return len(updates)


def load_entities_pipeline(
    *,
    client: Neo4jClient,
    project_uuid: str,
    limit_chunks: Optional[int] = None,
) -> Dict[str, int]:
    raw = fetch_raw_entities_from_chunks(client=client, project_uuid=project_uuid, limit_chunks=limit_chunks)
    canon = canonicalize(project_uuid, raw)
    n_entities = upsert_canonical_entities(client=client, entities=canon)
    n_mentions = upsert_mentions(client=client, entities=canon)
    n_co = upsert_cooccurrence(client=client, project_uuid=project_uuid, limit_chunks=limit_chunks)
    return {"raw_entities": len(raw), "canonical_entities": n_entities, "mentions": n_mentions, "cooccurs": n_co}

