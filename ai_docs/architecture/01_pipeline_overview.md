# Pipeline overview (markdown → chunks → Neo4j)

## High-level flow

```text
OCR markdown (*.md)
  → parse page markers (“Page X of Y”)
  → OpenAI chunk+entities (page-aware)
  → staging JSON (local)
  → Neo4j load (Case/CaseDocument/CaseChunk + NEXT_CHUNK)
  → analysis.csv ingest (document-level fields + join diagnostics)
  → document summary embeddings + SIMILAR_TO
  → canonical entities (CanonicalEntity + MENTIONED_IN + CO_OCCURS_WITH)
  → document links via entities (SHARES_ENTITY)
  → Markov enrichment (neighbor_summary/edge_summary/traversal_hints)
```

## Key invariants (Kunda-derived)

- **Case isolation**: everything is scoped by `project_uuid` on nodes.
- **Sequential reading**: `NEXT_CHUNK` between consecutive chunks in a document.
- **Deterministic chunk IDs**: `chunk_uuid = uuid5(document_uuid, "start:end")` (same input text → same chunk UUID).
- **Markov retrieval**: chunk nodes carry bounded local context to enable next-query decisions from a single result.

## Join strategy (analysis.csv → documents)

- Prefer **exact `DOC_####` prefix join** when unique.
- Fallback to **guarded normalized-title join** (only if it yields a unique match).
- Persist join metadata on `CaseDocument`:
  - `analysis_join_strategy`, `analysis_join_confidence`, `analysis_ingested`
- Emit an auditable report to `ai_docs/validation/analysis_join/`.

