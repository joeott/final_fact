"""
Load staged JSON artifacts into Neo4j FACT graph.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .neo4j_client import Neo4jClient


@dataclass(frozen=True)
class LoadStats:
    documents_loaded: int
    chunks_loaded: int
    rel_has_document: int
    rel_has_chunk: int
    rel_next_chunk: int
    documents_failed: int
    failures: List[Dict[str, str]]
    documents_loaded_uuids: List[str]


def _read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_project_staging(
    *,
    client: Neo4jClient,
    project_dir: Path,
    tenant_uuid: str,
    project_uuid: str,
    case_name: str,
    limit_docs: Optional[int] = None,
    docs_override: Optional[List[Dict[str, Any]]] = None,
) -> LoadStats:
    """
    Load a staged project directory (output/staging/{project_uuid}) into Neo4j.
    """
    project_dir = Path(project_dir)
    manifest_path = project_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found: {manifest_path}")

    if docs_override is not None:
        docs = docs_override
    else:
        manifest = _read_json(manifest_path)
        docs = manifest.get("documents", [])
    if limit_docs:
        docs = docs[:limit_docs]

    # 1) Case node
    client.write(
        """
        MERGE (c:Case {project_uuid: $project_uuid})
        SET c.tenant_uuid = $tenant_uuid,
            c.case_name = $case_name,
            c.status = 'active',
            c.created_at = coalesce(c.created_at, datetime())
        """,
        {"project_uuid": project_uuid, "tenant_uuid": tenant_uuid, "case_name": case_name},
    )

    doc_loaded = 0
    chunk_loaded = 0
    has_doc_rels = 0
    has_chunk_rels = 0
    next_rels = 0
    failed = 0
    failures: List[Dict[str, str]] = []
    loaded_uuids: List[str] = []

    for d in docs:
        document_uuid = str(d.get("document_uuid", ""))
        if not document_uuid:
            continue

        try:
            doc_dir = project_dir / document_uuid
            meta_path = doc_dir / "document_metadata.json"
            if not meta_path.exists():
                raise FileNotFoundError(f"document_metadata.json missing for {document_uuid}")

            meta = _read_json(meta_path)
            meta.update(
                {
                    "project_uuid": project_uuid,
                    "tenant_uuid": tenant_uuid,
                    "case_name": case_name,
                    "document_uuid": document_uuid,
                }
            )

            # 2) Document node (dual label)
            client.write(
                """
                MERGE (d:CaseDocument {document_uuid: $document_uuid})
                SET d:Document
                SET d += $props
                """,
                {"document_uuid": document_uuid, "props": meta},
            )

            # link to Case
            client.write(
                """
                MATCH (c:Case {project_uuid: $project_uuid})
                MATCH (d:CaseDocument {document_uuid: $document_uuid})
                MERGE (c)-[:HAS_DOCUMENT]->(d)
                """,
                {"project_uuid": project_uuid, "document_uuid": document_uuid},
            )

            # 3) Chunk nodes
            chunks_dir = doc_dir / "chunks"
            if not chunks_dir.exists():
                raise FileNotFoundError(f"chunks/ missing for {document_uuid}")

            chunk_files = sorted(chunks_dir.glob("*.json"))
            chunk_rows: List[Dict[str, Any]] = []
            for cf in chunk_files:
                cdata = _read_json(cf)
                cdata.update(
                    {
                        "project_uuid": project_uuid,
                        "tenant_uuid": tenant_uuid,
                        "document_uuid": document_uuid,
                    }
                )
                chunk_rows.append(cdata)

            if chunk_rows:
                # Batch upsert chunks
                client.write(
                    """
                    UNWIND $rows AS row
                    MERGE (c:CaseChunk {chunk_uuid: row.chunk_uuid})
                    SET c:Chunk
                    SET c += row
                    """,
                    {"rows": chunk_rows},
                )

                # HAS_CHUNK relationship
                client.write(
                    """
                    MATCH (d:CaseDocument {document_uuid: $document_uuid})
                    MATCH (c:CaseChunk {document_uuid: $document_uuid})
                    MERGE (d)-[:HAS_CHUNK]->(c)
                    """,
                    {"document_uuid": document_uuid},
                )

                # NEXT_CHUNK by chunk_index
                client.write(
                    """
                    MATCH (c:CaseChunk {document_uuid: $document_uuid})
                    WITH c ORDER BY c.chunk_index
                    WITH collect(c) as chunks
                    UNWIND range(0, size(chunks)-2) as i
                    WITH chunks[i] as cur, chunks[i+1] as nxt
                    MERGE (cur)-[:NEXT_CHUNK]->(nxt)
                    """,
                    {"document_uuid": document_uuid},
                )

            # Success: update counters only at the end so partial docs don't inflate stats.
            doc_loaded += 1
            loaded_uuids.append(document_uuid)
            has_doc_rels += 1
            chunk_loaded += len(chunk_rows)
            has_chunk_rels += len(chunk_rows)
            next_rels += max(0, len(chunk_rows) - 1)
        except Exception as e:
            failed += 1
            failures.append({"document_uuid": document_uuid, "error": str(e)})
            continue

    return LoadStats(
        documents_loaded=doc_loaded,
        chunks_loaded=chunk_loaded,
        rel_has_document=has_doc_rels,
        rel_has_chunk=has_chunk_rels,
        rel_next_chunk=next_rels,
        documents_failed=failed,
        failures=failures,
        documents_loaded_uuids=loaded_uuids,
    )

