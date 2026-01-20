# final_fact — Kunda-style ingestion + retrieval (scaffold)

## Goal

Build a professional, case-isolated ingestion pipeline that:

- Ingests OCR markdown from `input/organized/ocr/*.md`
- Preserves **page numbers** (e.g., `Page 1 of 6`)
- Uses a fast OpenAI model to chunk each page and extract entities
- Emits structured JSON to local staging (`output/staging/`)
- Loads to Neo4j FACT graph with Kunda-style schema + retrieval fields
- Ingests `input/organized/analysis/analysis.csv` and adds document similarity edges
- Adds Markov-style retrieval hints (`neighbor_summary`, `edge_summary`, `traversal_hints`)

## Inputs

- **OCR markdown**: `/Users/joe/Projects/final_fact/input/organized/ocr/*.md`
- **Analysis CSV**: `/Users/joe/Projects/final_fact/input/organized/analysis/analysis.csv`

## Outputs

- **Staging artifacts**: `/Users/joe/Projects/final_fact/output/staging/{project_uuid}/...`
- **Neo4j**: existing FACT graph (`NEO4J_FACT_*` from `/Users/joe/Projects/.env`)

## Next: how to run

See:

- `ai_docs/runbooks/01_local_run.md`
- `ai_docs/architecture/01_pipeline_overview.md`
- `ai_docs/schema/01_neo4j_schema.md`

