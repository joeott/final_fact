"""
Compute Markov-style local context fields for chunks.

Fields written on :CaseChunk nodes:
- neighbor_summary (JSON string)
- edge_summary (JSON string)
- traversal_hints (JSON string)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .neo4j_client import Neo4jClient


def _compact_neighbor(node_type: str, node_id: str, label: str, relevance: float, rel: str) -> Dict[str, Any]:
    return {
        "t": node_type,
        "id": (node_id or "")[:12],
        "l": (label or "")[:30],
        "r": round(float(relevance), 2),
        "rel": (rel or "")[:12],
    }


def enrich_markov_context(
    *,
    client: Neo4jClient,
    project_uuid: str,
    limit_chunks: Optional[int] = None,
    max_entities: int = 6,
) -> int:
    """
    Populate markov fields for chunks.
    """
    fetch = """
    MATCH (c:CaseChunk)
    WHERE c.project_uuid = $project_uuid
    OPTIONAL MATCH (d:CaseDocument)-[:HAS_CHUNK]->(c)
    OPTIONAL MATCH (c)-[:NEXT_CHUNK]->(nxt:CaseChunk)
    OPTIONAL MATCH (prv:CaseChunk)-[:NEXT_CHUNK]->(c)
    OPTIONAL MATCH (e:CanonicalEntity)-[:MENTIONED_IN]->(c)
    WITH c, d, nxt, prv, collect(DISTINCT e)[0..$max_entities] as entities
    RETURN
      c.chunk_uuid as chunk_uuid,
      d.document_uuid as document_uuid,
      d.title as doc_title,
      nxt.chunk_uuid as next_chunk_uuid,
      prv.chunk_uuid as prev_chunk_uuid,
      [x IN entities | {canonical_id: x.canonical_id, canonical_text: x.canonical_text, entity_type: x.entity_type, mention_count: x.mention_count}] as ents
    """
    if limit_chunks:
        fetch += f" LIMIT {int(limit_chunks)}"

    rows = client.write(fetch, {"project_uuid": project_uuid, "max_entities": int(max_entities)})
    if not rows:
        return 0

    updates = []
    for r in rows:
        neighbors: List[Dict[str, Any]] = []

        if r.get("document_uuid"):
            neighbors.append(
                _compact_neighbor("doc", r["document_uuid"], r.get("doc_title") or "", 0.9, "HAS_CHUNK")
            )
        if r.get("prev_chunk_uuid"):
            neighbors.append(_compact_neighbor("chunk", r["prev_chunk_uuid"], "prev", 0.6, "PREV"))
        if r.get("next_chunk_uuid"):
            neighbors.append(_compact_neighbor("chunk", r["next_chunk_uuid"], "next", 0.6, "NEXT"))

        for e in r.get("ents") or []:
            neighbors.append(
                _compact_neighbor(
                    "entity",
                    e.get("canonical_id") or "",
                    e.get("canonical_text") or "",
                    min(1.0, 0.3 + float(e.get("mention_count") or 0) / 50.0),
                    "MENTIONED_IN",
                )
            )

        edge_summary = [
            {"type": "NEXT_CHUNK", "n": int(bool(r.get("next_chunk_uuid")) + bool(r.get("prev_chunk_uuid")))},
            {"type": "MENTIONED_IN", "n": len(r.get("ents") or [])},
        ]

        hints = []
        # Hint: follow top entity if exists
        if r.get("ents"):
            top = sorted(r["ents"], key=lambda x: x.get("mention_count", 0), reverse=True)[0]
            hints.append(
                {
                    "type": "explore_entity",
                    "desc": f"Explore entity {str(top.get('canonical_text',''))[:30]}",
                    "id": str(top.get("canonical_id", ""))[:12],
                }
            )
        # Hint: continue reading
        if r.get("next_chunk_uuid"):
            hints.append({"type": "continue", "desc": "Continue to next chunk", "id": r["next_chunk_uuid"][:12]})

        updates.append(
            {
                "chunk_uuid": r["chunk_uuid"],
                "neighbor_summary": json.dumps(neighbors[:8], ensure_ascii=False),
                "edge_summary": json.dumps(edge_summary, ensure_ascii=False),
                "traversal_hints": json.dumps(hints[:3], ensure_ascii=False),
            }
        )

    client.write(
        """
        UNWIND $rows AS row
        MATCH (c:CaseChunk {chunk_uuid: row.chunk_uuid})
        SET c.neighbor_summary = row.neighbor_summary,
            c.edge_summary = row.edge_summary,
            c.traversal_hints = row.traversal_hints,
            c.context_enriched = true,
            c.markov_version = '1.0'
        """,
        {"rows": updates},
    )
    return len(updates)

