"""
analysis.csv ingestion + document similarity edges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..llm.openai_client import OpenAIService
from ..parsing.analysis_csv import AnalysisRow
from ..parsing.normalize_keys import extract_doc_prefix, normalized_title_key, organized_basename
from .neo4j_client import Neo4jClient


@dataclass(frozen=True)
class AnalysisJoinResult:
    updated_documents: int
    matched_rows: int
    unmatched_rows: int
    ambiguous_rows: int
    unmatched_row_examples: List[str]
    ambiguous_row_examples: List[str]


def ingest_analysis_rows(
    *,
    client: Neo4jClient,
    project_uuid: str,
    rows: List[AnalysisRow],
) -> AnalysisJoinResult:
    """
    Two-pass join with explainability:
    - Pass A: doc_prefix (DOC_####) unique match
    - Pass B: normalized_title_key unique match (guarded)
    """
    # Fetch candidate documents in project
    docs = client.write(
        """
        MATCH (d:CaseDocument)
        WHERE d.project_uuid = $project_uuid
        RETURN d.document_uuid as document_uuid,
               d.doc_prefix as doc_prefix,
               d.organized_basename as organized_basename,
               d.normalized_title_key as normalized_title_key,
               d.title as title,
               d.source_file as source_file
        """,
        {"project_uuid": project_uuid},
    )

    # Normalize doc keys (and upsert if missing)
    doc_updates = []
    prefix_map: Dict[str, List[str]] = {}
    key_map: Dict[str, List[str]] = {}
    for d in docs:
        du = d["document_uuid"]
        title = d.get("title") or ""
        source_file = d.get("source_file") or ""

        dp = (d.get("doc_prefix") or "").strip() or extract_doc_prefix(title) or extract_doc_prefix(source_file)
        ob = (d.get("organized_basename") or "").strip() or organized_basename(title) or organized_basename(source_file)
        nk = (d.get("normalized_title_key") or "").strip() or normalized_title_key(title) or normalized_title_key(source_file)

        if dp:
            prefix_map.setdefault(dp, []).append(du)
        if nk:
            key_map.setdefault(nk, []).append(du)

        # store back if missing (auditability)
        if (d.get("doc_prefix") or "") != dp or (d.get("organized_basename") or "") != ob or (d.get("normalized_title_key") or "") != nk:
            doc_updates.append(
                {
                    "document_uuid": du,
                    "doc_prefix": dp,
                    "organized_basename": ob,
                    "normalized_title_key": nk,
                }
            )

    if doc_updates:
        client.write(
            """
            UNWIND $rows AS row
            MATCH (d:CaseDocument {document_uuid: row.document_uuid})
            SET d.doc_prefix = row.doc_prefix,
                d.organized_basename = row.organized_basename,
                d.normalized_title_key = row.normalized_title_key
            """,
            {"rows": doc_updates},
        )

    matched = 0
    ambiguous = 0
    unmatched = 0
    matched_doc_uuids = set()
    updates = []
    unmatched_examples: List[str] = []
    ambiguous_examples: List[str] = []

    for r in rows:
        dp = r.doc_prefix
        nk = r.normalized_title_key
        chosen: Optional[str] = None
        strategy = "none"
        confidence = 0.0

        # Pass A: prefix
        if dp and dp in prefix_map:
            cands = prefix_map[dp]
            if len(cands) == 1:
                chosen = cands[0]
                strategy = "prefix"
                confidence = 1.0
            else:
                strategy = "ambiguous"
        # Pass B: normalized key
        if not chosen and strategy != "ambiguous" and nk and nk in key_map:
            cands = key_map[nk]
            if len(cands) == 1:
                chosen = cands[0]
                strategy = "normalized"
                confidence = 0.7
            else:
                strategy = "ambiguous"

        if strategy == "ambiguous":
            ambiguous += 1
            if len(ambiguous_examples) < 25:
                ambiguous_examples.append(r.organized_doc_number)
            continue
        if not chosen:
            unmatched += 1
            if len(unmatched_examples) < 25:
                unmatched_examples.append(r.organized_doc_number)
            continue

        matched += 1
        matched_doc_uuids.add(chosen)
        updates.append(
            {
                "document_uuid": chosen,
                "file_type": r.file_type,
                "file_description": r.file_description,
                "relevance_analysis": r.relevance_analysis,
                "original_file_path": r.original_file_path,
                "organized_doc_number": r.organized_doc_number,
                "summary_text": (r.file_description + "\n\n" + r.relevance_analysis).strip(),
                "analysis_join_strategy": strategy,
                "analysis_join_confidence": confidence,
            }
        )

    if updates:
        client.write(
            """
            UNWIND $rows AS row
            MATCH (d:CaseDocument {document_uuid: row.document_uuid})
            SET d:Document
            SET d.file_type = row.file_type,
                d.file_description = row.file_description,
                d.relevance_analysis = row.relevance_analysis,
                d.original_file_path = row.original_file_path,
                d.organized_doc_number = row.organized_doc_number,
                d.summary_text = row.summary_text,
                d.analysis_ingested = true,
                d.analysis_join_strategy = row.analysis_join_strategy,
                d.analysis_join_confidence = row.analysis_join_confidence
            """,
            {"rows": updates},
        )

    return AnalysisJoinResult(
        updated_documents=len(matched_doc_uuids),
        matched_rows=matched,
        unmatched_rows=unmatched,
        ambiguous_rows=ambiguous,
        unmatched_row_examples=unmatched_examples,
        ambiguous_row_examples=ambiguous_examples,
    )


def embed_documents(
    *,
    client: Neo4jClient,
    openai: OpenAIService,
    project_uuid: str,
    limit: Optional[int] = None,
) -> int:
    """
    Generate summary embeddings for documents that have summary_text and no summary_embedding.
    """
    fetch = """
    MATCH (d:Document)
    WHERE d.project_uuid = $project_uuid
      AND d.summary_text IS NOT NULL AND d.summary_text <> ''
      AND d.summary_embedding IS NULL
    RETURN d.document_uuid as document_uuid, d.summary_text as summary_text
    """
    if limit:
        fetch += f" LIMIT {int(limit)}"

    rows = client.write(fetch, {"project_uuid": project_uuid})
    if not rows:
        return 0

    texts = [r["summary_text"] for r in rows]
    embs = openai.embed_texts(texts)
    updates = []
    for r, e in zip(rows, embs):
        updates.append({"document_uuid": r["document_uuid"], "embedding": e})

    client.write(
        """
        UNWIND $rows AS row
        MATCH (d:Document {document_uuid: row.document_uuid})
        SET d.summary_embedding = row.embedding,
            d.summary_embedding_model = $model
        """,
        {"rows": updates, "model": openai.cfg.embedding_model},
    )
    return len(updates)


def build_document_similarity_edges(
    *,
    client: Neo4jClient,
    project_uuid: str,
    top_k: int = 10,
    max_edges_per_doc: Optional[int] = None,
    limit_docs: Optional[int] = None,
    min_score: float = 0.75,
    reset: bool = False,
) -> int:
    """
    Create SIMILAR_TO edges between documents using the doc_summary_embeddings index.
    """
    if reset:
        client.write(
            """
            MATCH (d1:Document {project_uuid: $project_uuid})-[r:SIMILAR_TO]->(d2:Document {project_uuid: $project_uuid})
            DELETE r
            """,
            {"project_uuid": project_uuid},
        )

    effective_k = int(max_edges_per_doc) if max_edges_per_doc is not None else int(top_k)

    fetch = """
    MATCH (d:Document)
    WHERE d.project_uuid = $project_uuid
      AND d.summary_embedding IS NOT NULL
    RETURN d.document_uuid as document_uuid, d.summary_embedding as embedding
    """
    if limit_docs:
        fetch += f" LIMIT {int(limit_docs)}"

    docs = client.write(fetch, {"project_uuid": project_uuid})
    if not docs:
        return 0

    created = 0
    for d in docs:
        cypher = """
        MATCH (src:Document {document_uuid: $doc_uuid})
        CALL db.index.vector.queryNodes('doc_summary_embeddings', $top_k, $vector)
        YIELD node, score
        WHERE node.project_uuid = $project_uuid
          AND node.document_uuid <> $doc_uuid
          AND score >= $min_score
        MERGE (src)-[r:SIMILAR_TO]->(node)
        SET r.score = score
        RETURN count(r) as c
        """
        res = client.write(
            cypher,
            {
                "doc_uuid": d["document_uuid"],
                "vector": d["embedding"],
                "top_k": effective_k,
                "project_uuid": project_uuid,
                "min_score": float(min_score),
            },
        )
        if res:
            created += int(res[0].get("c", 0))
    return created

