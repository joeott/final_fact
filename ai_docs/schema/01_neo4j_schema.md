# Neo4j schema (final_fact)

This schema mirrors the Kunda “final loader” shape and is designed for Markov-style Cypher retrieval.

## Nodes

### `Case`

- `tenant_uuid` (string)
- `project_uuid` (string UUID)
- `case_name` (string)
- `created_at` (datetime)

### `CaseDocument` (also labeled `Document` for compatibility)

- **Identity**: `document_uuid`, `project_uuid`, `tenant_uuid`
- **Source**: `ocr_markdown_path`, `source_file_path`, `source_file`
- **Join keys** (for analysis.csv alignment):
  - `doc_prefix` (e.g., `DOC_0007`)
  - `organized_basename` (string)
  - `normalized_title_key` (string)
- **analysis.csv fields**:
  - `organized_doc_number`
  - `original_file_path`
  - `file_type`
  - `file_description`
  - `relevance_analysis`
  - `summary_text` (derived: description + relevance)
  - `analysis_ingested` (bool)
  - `analysis_join_strategy` (`prefix|normalized|none|ambiguous`)
  - `analysis_join_confidence` (float)
- **Embeddings**: `summary_embedding` (vector), `summary_embedding_model`

### `CaseChunk` (also labeled `Chunk` for compatibility)

- **Identity**: `chunk_uuid`, `document_uuid`, `project_uuid`, `tenant_uuid`
- **Compatibility keys** (required by some existing FACT graph constraints/tooling):
  - `id` (= `chunk_uuid`)
  - `source_file` (string)
- **Content**: `text`, `clean_text`, `page_number`
- **Offsets**: `char_start`, `char_end`, `chunk_index`
- **Provenance**: `source_file_path`, `ocr_markdown_path`
- **Entities (stored safely for Neo4j properties)**:
  - `entities_json` (JSON string of list of `{entity_type,text}`)
  - `entities_flat` (string array like `PERSON::John Smith`)
- **Retrieval**: `neighbor_summary`, `edge_summary`, `traversal_hints`

### `CanonicalEntity`

- `canonical_id` (string UUID)
- `project_uuid` (string UUID)
- `entity_type` (string)
- `canonical_text` (string)
- `variants` (list of strings)
- `mention_count` (int)

## Relationships

- `(Case)-[:HAS_DOCUMENT]->(CaseDocument)`
- `(CaseDocument)-[:HAS_CHUNK]->(CaseChunk)`
- `(CaseChunk)-[:NEXT_CHUNK]->(CaseChunk)`
- `(CanonicalEntity)-[:MENTIONED_IN]->(CaseChunk)`
- `(CanonicalEntity)-[:CO_OCCURS_WITH {count}]->(CanonicalEntity)`
- `(CaseDocument)-[:SIMILAR_TO {score}]->(CaseDocument)`
- `(CaseDocument)-[:SHARES_ENTITY {count}]->(CaseDocument)`

## Indexes / constraints (minimum)

- Uniqueness constraints:
  - `Case.project_uuid`
  - `CaseDocument.document_uuid`
  - `CaseChunk.chunk_uuid`
  - `CanonicalEntity.canonical_id`
- Lookup indexes:
  - `CaseDocument.project_uuid`
  - `CaseChunk.document_uuid`
  - `CaseChunk.project_uuid`
  - `CanonicalEntity.project_uuid`
  - `Chunk.page_number`, `Chunk.chunk_index`
- Fulltext:
  - `chunk_fulltext` on `(Chunk.clean_text, Chunk.text)`
- Vector:
  - `doc_summary_embeddings` on `Document.summary_embedding` (1536D cosine)

