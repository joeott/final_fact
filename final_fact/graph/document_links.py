"""
Document-to-document linking edges derived from entities.
"""

from __future__ import annotations

from typing import Optional

from .neo4j_client import Neo4jClient


def build_shares_entity_edges(
    *,
    client: Neo4jClient,
    project_uuid: str,
    min_entity_mentions: int = 3,
    limit_entities: int = 5000,
    max_docs_per_entity: int = 50,
    min_shared_entities: int = 2,
) -> int:
    """
    Create (d1)-[:SHARES_ENTITY {count}]->(d2) edges.

    This is project-scoped and uses caps to avoid quadratic blowups:
    - only entities with mention_count >= min_entity_mentions
    - only top `limit_entities` entities by mention_count
    - cap docs considered per entity to `max_docs_per_entity`
    """
    cypher = """
    MATCH (e:CanonicalEntity)
    WHERE e.project_uuid = $project_uuid
      AND e.mention_count >= $min_mentions
    WITH e ORDER BY e.mention_count DESC
    LIMIT $limit_entities

    MATCH (e)-[:MENTIONED_IN]->(:CaseChunk)<-[:HAS_CHUNK]-(d:CaseDocument)
    WHERE d.project_uuid = $project_uuid
    WITH e, collect(DISTINCT d)[0..$max_docs_per_entity] as docs

    UNWIND docs as d1
    UNWIND docs as d2
    WITH d1, d2, e
    WHERE d1.document_uuid < d2.document_uuid

    WITH d1, d2, count(DISTINCT e) as shared
    WHERE shared >= $min_shared

    MERGE (d1)-[r:SHARES_ENTITY]->(d2)
    SET r.count = shared
    RETURN count(r) as edges
    """
    res = client.write(
        cypher,
        {
            "project_uuid": project_uuid,
            "min_mentions": int(min_entity_mentions),
            "limit_entities": int(limit_entities),
            "max_docs_per_entity": int(max_docs_per_entity),
            "min_shared": int(min_shared_entities),
        },
    )
    return int(res[0]["edges"]) if res else 0

