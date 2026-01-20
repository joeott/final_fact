"""
Neo4j schema: constraints and indexes for final_fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .neo4j_client import Neo4jClient


VECTOR_DIM = 1536


def apply_constraints_and_indexes(client: Neo4jClient) -> None:
    """
    Create constraints and indexes.

    Notes:
    - We label documents as both :CaseDocument and :Document
    - We label chunks as both :CaseChunk and :Chunk
    """
    stmts: List[str] = [
        # --- Constraints ---
        "CREATE CONSTRAINT case_project_uuid_unique IF NOT EXISTS FOR (c:Case) REQUIRE c.project_uuid IS UNIQUE",
        "CREATE CONSTRAINT doc_uuid_unique IF NOT EXISTS FOR (d:CaseDocument) REQUIRE d.document_uuid IS UNIQUE",
        "CREATE CONSTRAINT chunk_uuid_unique IF NOT EXISTS FOR (c:CaseChunk) REQUIRE c.chunk_uuid IS UNIQUE",
        "CREATE CONSTRAINT canonical_entity_id_unique IF NOT EXISTS FOR (e:CanonicalEntity) REQUIRE e.canonical_id IS UNIQUE",
        # --- Lookup indexes ---
        "CREATE INDEX idx_doc_project_uuid IF NOT EXISTS FOR (d:CaseDocument) ON (d.project_uuid)",
        "CREATE INDEX idx_chunk_project_uuid IF NOT EXISTS FOR (c:CaseChunk) ON (c.project_uuid)",
        "CREATE INDEX idx_chunk_doc_uuid IF NOT EXISTS FOR (c:CaseChunk) ON (c.document_uuid)",
        "CREATE INDEX idx_chunk_page IF NOT EXISTS FOR (c:CaseChunk) ON (c.page_number)",
        "CREATE INDEX idx_chunk_index IF NOT EXISTS FOR (c:CaseChunk) ON (c.chunk_index)",
        "CREATE INDEX idx_entity_project IF NOT EXISTS FOR (e:CanonicalEntity) ON (e.project_uuid)",
        # --- Fulltext (compat label :Chunk) ---
        "CREATE FULLTEXT INDEX chunk_fulltext IF NOT EXISTS FOR (c:Chunk) ON EACH [c.clean_text, c.text]",
        # --- Vector indexes ---
        (
            "CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS "
            "FOR (c:Chunk) ON (c.embedding) "
            "OPTIONS {indexConfig: {`vector.dimensions`: $dim, `vector.similarity_function`: 'cosine'}}"
        ),
        (
            "CREATE VECTOR INDEX doc_summary_embeddings IF NOT EXISTS "
            "FOR (d:Document) ON (d.summary_embedding) "
            "OPTIONS {indexConfig: {`vector.dimensions`: $dim, `vector.similarity_function`: 'cosine'}}"
        ),
    ]

    for stmt in stmts:
        try:
            if "VECTOR INDEX" in stmt:
                client.write(stmt, {"dim": VECTOR_DIM})
            else:
                client.write(stmt)
        except Exception:
            # Index/constraint may already exist or may not be supported (older Neo4j).
            # We keep going; verification steps later will surface missing infra.
            continue

