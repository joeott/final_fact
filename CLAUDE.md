# CLAUDE.md - final_fact Legal Document Ingestion Pipeline

**Legal case document processing with page-aware chunking and Neo4j knowledge graph**

**Updated**: 2026-01-20 | **Status**: Production-ready for deposition preparation

---

## Quick Reference

### Project Purpose

**final_fact** is a professional, case-isolated document ingestion pipeline that processes legal case documents (depositions, exhibits, pleadings) through OCR, page-aware chunking, entity extraction, and loads them into a Neo4j knowledge graph for legal research and case preparation.

**Key Differentiators**:
- **Case isolation**: Every project gets deterministic UUIDs - no cross-contamination
- **Page markers preserved**: `Page X of Y` format maintained through entire pipeline
- **Exhibit name preservation**: File names (exhibit identities) are preserved on every chunk
- **Kunda-style schema**: Sequential reading with `NEXT_CHUNK` relationships
- **Markov retrieval**: Chunks carry local context for next-query decision-making

### Core Technologies

- **OCR**: Google Vertex AI Mistral (Pixtral-12b) via rawPredict
- **Chunking**: OpenAI GPT-4o-mini (page-aware, 500-2000 char chunks with entity extraction)
- **Database**: Neo4j Aura FACT Graph (`6d98f1e5`)
- **Language**: Python 3.13+
- **Key Libraries**: neo4j, openai, google-auth, pydantic, rapidfuzz

---

## Architecture Overview

### Pipeline Flow

```
PDF Documents
  ↓
[1] OCR → Markdown with page markers ("Page X of Y")
  ↓
[2] Page-aware chunking + entity extraction (OpenAI)
  ↓
[3] Local staging JSON (deterministic UUIDs)
  ↓
[4] Neo4j load (Case/CaseDocument/CaseChunk + NEXT_CHUNK)
  ↓
[5] Analysis CSV integration (document-level metadata join)
  ↓
[6] Document similarity (embeddings + SIMILAR_TO edges)
  ↓
[7] Entity canonicalization (CanonicalEntity + MENTIONED_IN)
  ↓
[8] Document entity links (SHARES_ENTITY)
  ↓
[9] Markov enrichment (neighbor_summary, edge_summary, traversal_hints)
```

### Key Invariants

1. **Case isolation**: Everything scoped by `project_uuid` (deterministic from case name)
2. **Sequential reading**: `NEXT_CHUNK` relationships between consecutive chunks
3. **Deterministic IDs**: Same input text → same chunk UUIDs (idempotent)
4. **Exhibit identity**: File name preserved as `exhibit_name` on every chunk
5. **Page awareness**: Every chunk knows its page number and full-text offset

---

## Project Structure

```
final_fact/
├── CLAUDE.md                    # This file
├── requirements.txt             # Python dependencies
├── input/                       # Case documents (organized by case)
│   ├── Jostes_depo/            # Current: Jostes deposition (18 exhibits)
│   │   ├── *.pdf               # Source PDFs (depositions, exhibits)
│   │   └── organized/
│   │       └── ocr/            # OCR markdown outputs (page-marked)
│   └── kunda/                  # Kunda v. Smith case (1,987+ documents)
│       ├── *.pdf
│       ├── ocr/                # OCR outputs
│       └── analysis/           # Document analysis CSVs
│           └── analysis.csv    # Document metadata + summaries
├── output/
│   └── staging/                # Local staging JSON (by project_uuid)
│       └── {project_uuid}/
│           ├── manifest.json   # Document status tracking
│           └── {document_uuid}/
│               ├── document_metadata.json
│               └── chunks/
│                   └── {chunk_uuid}.json
├── final_fact/                 # Python package
│   ├── cli.py                  # CLI entrypoint (all commands)
│   ├── config.py               # Settings + deterministic UUID generation
│   ├── ocr/                    # OCR modules
│   │   └── vertex_mistral.py   # Vertex AI Mistral OCR
│   ├── parsing/                # Markdown parsing
│   │   ├── page_markers.py     # Page marker extraction
│   │   ├── analysis_csv.py     # Analysis CSV parsing
│   │   └── normalize_keys.py   # Document key normalization
│   ├── llm/                    # LLM integrations
│   │   ├── openai_client.py    # OpenAI API wrapper
│   │   └── chunk_and_entities.py  # Page chunking + entity extraction
│   ├── io/                     # I/O utilities
│   │   └── staging.py          # Local staging store + manifest
│   ├── graph/                  # Neo4j operations
│   │   ├── neo4j_client.py     # Neo4j connection + utilities
│   │   ├── indexes.py          # Index/constraint creation
│   │   ├── loader.py           # Bulk UNWIND loader
│   │   ├── similarity.py       # Document embeddings + similarity edges
│   │   ├── document_links.py   # SHARES_ENTITY relationships
│   │   └── markov_enrichment.py  # Retrieval hint generation
│   ├── entities/               # Entity processing
│   │   └── load_entities.py    # Entity canonicalization + graph load
│   └── validation/             # Run reports
│       ├── ocr_run_report.py   # OCR validation reports
│       ├── ingest_run_report.py  # Ingest validation reports
│       └── (generated reports in ai_docs/validation/)
└── ai_docs/                    # Documentation + validation
    ├── 00_START_HERE.md        # Quick start guide
    ├── architecture/           # System design
    │   └── 01_pipeline_overview.md
    ├── runbooks/               # Operational guides
    │   ├── 01_local_run.md     # Local execution guide
    │   ├── 02_next_iteration_scale_and_resume.md
    │   └── 03_next_steps_mcp_validation.md
    ├── schema/                 # Neo4j schema documentation
    │   └── 01_neo4j_schema.md
    └── validation/             # Validation reports (auto-generated)
        ├── ocr_runs/           # OCR run reports
        ├── ingest_runs/        # Ingest run reports
        ├── load_runs/          # Neo4j load reports
        └── analysis_join/      # Analysis CSV join reports
```

---

## Setup & Configuration

### Environment Setup

```bash
cd /Users/joe/Projects/final_fact
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Credentials Configuration

**Required in `/Users/joe/Projects/.env`** (centralized credentials):

```bash
# OpenAI (chunking + embeddings)
OPENAI_API_KEY=sk-...

# Neo4j FACT Graph (case documents)
NEO4J_FACT_URI=neo4j+s://6d98f1e5.databases.neo4j.io
NEO4J_FACT_USERNAME=neo4j
NEO4J_FACT_PASSWORD=...
```

### Google Vertex AI Authentication

**For OCR (Mistral Pixtral-12b)**:

```bash
# 1) Login with your Google account
gcloud auth login

# 2) Enable Application Default Credentials (required for Vertex rawPredict)
gcloud auth application-default login

# 3) Set active project
gcloud config set project document-processor-v3

# 4) Verify ADC works
gcloud auth application-default print-access-token >/dev/null && echo "✓ ADC OK"
```

**Important**: The OCR module requests the `cloud-platform` scope explicitly to avoid 403 errors.

---

## CLI Commands

### Command Reference

All commands are invoked via: `python -m final_fact.cli <command> [args]`

| Command | Purpose | Key Options |
|---------|---------|-------------|
| **ocr** | OCR PDFs to markdown | `--case-name`, `--input-base-dir`, `--workers`, `--request-delay-seconds` |
| **ingest** | Chunk markdown + stage JSON | `--case-name`, `--input-base-dir`, `--limit-docs`, `--resume`, `--max-pages-per-doc` |
| **indexes** | Create Neo4j constraints/indexes | `--case-name`, `--input-base-dir` |
| **load-neo4j** | Load staging JSON to Neo4j | `--case-name`, `--input-base-dir` |
| **ingest-analysis** | Load analysis.csv metadata | `--case-name`, `--input-base-dir` |
| **analysis-join-report** | Generate join validation report | `--case-name`, `--input-base-dir` |
| **embed-docs** | Generate document summary embeddings | `--case-name`, `--limit` |
| **build-doc-similarity** | Create SIMILAR_TO edges | `--case-name`, `--top-k`, `--min-score`, `--reset` |
| **load-entities** | Canonicalize + load entities | `--case-name`, `--limit-chunks` |
| **build-doc-entity-links** | Create SHARES_ENTITY edges | `--case-name` |
| **markov-enrich** | Add retrieval hints to chunks | `--case-name`, `--limit-chunks` |

### Common Workflows

#### 1. Process New Deposition Exhibits (Recommended)

**Step 1: OCR the PDFs**
```bash
cd /Users/joe/Projects/final_fact
source venv/bin/activate

# OCR all PDFs in input/Jostes_depo/*.pdf
python -m final_fact.cli ocr \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo \
  --workers 1 \
  --request-delay-seconds 5
```

This writes:
- OCR markdown: `input/Jostes_depo/organized/ocr/*.md`
- Validation report: `ai_docs/validation/ocr_runs/ocr_run_*.md`

**Step 2: Chunk and stage (with resume capability)**
```bash
# Process all exhibits with checkpoint/resume
python -m final_fact.cli ingest \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo \
  --resume
```

This writes:
- Staging JSON: `output/staging/{project_uuid}/{document_uuid}/...`
- Manifest: `output/staging/{project_uuid}/manifest.json`
- Validation report: `ai_docs/validation/ingest_runs/ingest_run_*.md`

**Step 3: Load to Neo4j**
```bash
# Create indexes/constraints (one-time per case)
python -m final_fact.cli indexes \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo

# Load all staged documents
python -m final_fact.cli load-neo4j \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo
```

This writes:
- Neo4j nodes: `Case`, `CaseDocument`, `CaseChunk`
- Neo4j relationships: `HAS_DOCUMENT`, `HAS_CHUNK`, `NEXT_CHUNK`
- Validation report: `ai_docs/validation/load_runs/load_run_*.md`

**Step 4: Enhancement (optional but recommended)**
```bash
# Load entities (Person, Organization, Place, Date, etc.)
python -m final_fact.cli load-entities \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo

# Create document entity links (SHARES_ENTITY)
python -m final_fact.cli build-doc-entity-links \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo

# Add Markov retrieval hints
python -m final_fact.cli markov-enrich \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo
```

#### 2. Process Large Case with Batching

```bash
# Ingest in batches of 10 documents
python -m final_fact.cli ingest \
  --case-name "Kunda v. Smith (final_fact)" \
  --limit-docs 10 \
  --resume

# Continue from where you left off
python -m final_fact.cli ingest \
  --case-name "Kunda v. Smith (final_fact)" \
  --start-at 10 \
  --limit-docs 10 \
  --resume
```

#### 3. Test Small Sample First

```bash
# Test with first 2 documents, max 5 pages each
python -m final_fact.cli ingest \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo \
  --limit-docs 2 \
  --max-pages-per-doc 5
```

---

## Current Status: Jostes Deposition Ingestion

### Project Context

**Case**: Jostes deposition preparation
**Project UUID**: `bdbded17-4690-5f8a-a6fb-538755da6e88` (deterministic from "Jostes_depo")
**Location**: `/Users/joe/Projects/final_fact/input/Jostes_depo/`

### Ingestion Status (as of 2026-01-20)

**Total exhibits**: 18 PDFs
**OCR complete**: ✅ All 18 exhibits (markdown with page markers)
**Chunking/staging**: 🟡 11 of 18 staged (149 chunks)
**Neo4j load**: ❌ Not started yet

**Pending exhibits** (7 remaining):
1. Exhibit 17 - Complaint.md
2. Exhibit 2 - acuity responses to wombat rfp.md
3. Exhibit 4 - Claim Log.md
4. Exhibit 6 - Initial Report Newman.md
5. Exhibit 7 - Initial Report, Reserves.md
6. Exhibit 8 - Email re No Coverage for Fire Suppression System.md
7. Exhibit 9 - Email chain March re updated repair costs.md

### Next Steps

1. **Complete ingest** for 7 pending exhibits
2. **Run indexes** (one-time setup)
3. **Load to Neo4j** (all 18 exhibits with chunks)
4. **Run enhancement** (entities, doc links, markov)
5. **Verify in Neo4j** that `exhibit_name` is present on all chunks

---

## Key Features

### 1. Exhibit Name Preservation

**Critical requirement**: The file name (exhibit identifier) must be preserved on every chunk for deposition preparation.

**Implementation**:
```python
# In cli.py:_stage_one()
exhibit_name = md_path.stem  # e.g., "Exhibit 1 - acuity answers to wombat interrogs"

chunk_data = {
    "exhibit_name": exhibit_name,  # ← Preserved on every chunk
    "chunk_uuid": chunk_uuid,
    "page_number": p.page_number,
    "text": pc.text,
    # ... other fields
}
```

**Neo4j verification** (after load):
```cypher
// Verify all chunks have exhibit_name for Jostes case
MATCH (c:CaseChunk {project_uuid: "bdbded17-4690-5f8a-a6fb-538755da6e88"})
WHERE c.exhibit_name IS NULL
RETURN count(c) as chunks_missing_exhibit_name

// Expected: 0
```

### 2. Page-Aware Chunking

- Markdown files contain explicit page markers: `Page 1 of 6`, `Page 2 of 6`, etc.
- Parser (`split_markdown_into_pages()`) extracts page-bounded text segments
- OpenAI chunks **each page independently** with page context
- Every chunk records:
  - `page_number` (source page)
  - `page_start`, `page_end` (offsets within page)
  - `full_start`, `full_end` (offsets in full document text)

### 3. Case Isolation (Deterministic UUIDs)

```python
# All UUIDs are deterministic from inputs (no randomness)
tenant_uuid = uuid5(NAMESPACE_DNS, "ott.law")
project_uuid = uuid5(tenant_uuid, case_name)  # e.g., "Jostes_depo"
document_uuid = uuid5(project_uuid, doc_key)  # e.g., "Exhibit 1 - acuity..."
chunk_uuid = uuid5(document_uuid, f"{full_start}:{full_end}")

# Same case name + file name → same UUIDs every time (idempotent)
```

### 4. Resume Capability

The `--resume` flag enables checkpoint/restart:

```bash
python -m final_fact.cli ingest \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo \
  --resume
```

- Checks `manifest.json` for already-staged documents
- Skips documents with `status="staged"` or `status="loaded"`
- Continues from where it left off (safe to Ctrl+C and restart)

### 5. Validation Reports

Every major operation generates a validation report in `ai_docs/validation/`:

**OCR reports** (`ai_docs/validation/ocr_runs/ocr_run_*.md`):
- Files processed, errors, timing
- Retry/backoff statistics
- Page marker verification

**Ingest reports** (`ai_docs/validation/ingest_runs/ingest_run_*.md`):
- Documents scanned, staged, skipped
- Chunk counts, page counts
- Errors and retry statistics

**Load reports** (`ai_docs/validation/load_runs/load_run_*.md`):
- Neo4j node/relationship counts
- Load timing, errors
- Verification queries

---

## Neo4j Schema

### Core Nodes

**Case** (one per project):
```cypher
(:Case {
  project_uuid: "bdbded17-4690-5f8a-a6fb-538755da6e88",
  case_name: "Jostes_depo",
  tenant_uuid: "..."
})
```

**CaseDocument** (also labeled `Document`):
```cypher
(:CaseDocument:Document {
  document_uuid: "ae79fec3-bdd3-5605-ac10-4fef28ebdea6",
  project_uuid: "bdbded17-4690-5f8a-a6fb-538755da6e88",
  title: "Exhibit 1 - acuity answers to wombat interrogs.md",
  source_file: "Exhibit 1 - acuity answers to wombat interrogs",
  exhibit_name: "Exhibit 1 - acuity answers to wombat interrogs",  // ← preserved
  page_count: 17,
  chunk_count: 49
})
```

**CaseChunk** (also labeled `Chunk`):
```cypher
(:CaseChunk:Chunk {
  chunk_uuid: "c1234567-...",
  document_uuid: "ae79fec3-...",
  project_uuid: "bdbded17-4690-5f8a-a6fb-538755da6e88",
  exhibit_name: "Exhibit 1 - acuity answers to wombat interrogs",  // ← preserved
  page_number: 1,
  chunk_index: 0,
  text: "...",
  full_start: 0,
  full_end: 1247,
  // Markov retrieval fields (added during enrichment):
  neighbor_summary: "...",
  edge_summary: "...",
  traversal_hints: "..."
})
```

### Core Relationships

```cypher
(case:Case)-[:HAS_DOCUMENT]->(doc:CaseDocument)
(doc:CaseDocument)-[:HAS_CHUNK]->(chunk:CaseChunk)
(chunk1:CaseChunk)-[:NEXT_CHUNK]->(chunk2:CaseChunk)  // Sequential reading

// After enhancement:
(chunk:CaseChunk)-[:MENTIONED_IN]->(entity:CanonicalEntity)
(doc1:CaseDocument)-[:SHARES_ENTITY {count: 5}]->(doc2:CaseDocument)
(doc1:CaseDocument)-[:SIMILAR_TO {score: 0.87}]->(doc2:CaseDocument)
```

### Indexes & Constraints

```cypher
// Uniqueness constraints (created by `indexes` command)
CREATE CONSTRAINT case_project_uuid IF NOT EXISTS
  FOR (c:Case) REQUIRE c.project_uuid IS UNIQUE;

CREATE CONSTRAINT doc_document_uuid IF NOT EXISTS
  FOR (d:CaseDocument) REQUIRE d.document_uuid IS UNIQUE;

CREATE CONSTRAINT chunk_chunk_uuid IF NOT EXISTS
  FOR (c:CaseChunk) REQUIRE c.chunk_uuid IS UNIQUE;

// Lookup indexes
CREATE INDEX case_project_idx IF NOT EXISTS
  FOR (c:Case) ON (c.project_uuid);

CREATE INDEX doc_project_idx IF NOT EXISTS
  FOR (d:CaseDocument) ON (d.project_uuid);

CREATE INDEX chunk_project_idx IF NOT EXISTS
  FOR (c:CaseChunk) ON (c.project_uuid);

CREATE INDEX chunk_doc_idx IF NOT EXISTS
  FOR (c:CaseChunk) ON (c.document_uuid);
```

---

## Common Cypher Queries

### 1. Verify Exhibit Name Preservation

```cypher
// Check all chunks have exhibit_name for Jostes case
MATCH (c:CaseChunk {project_uuid: "bdbded17-4690-5f8a-a6fb-538755da6e88"})
WHERE c.exhibit_name IS NULL
RETURN count(c) as chunks_missing_exhibit_name;
// Expected: 0
```

### 2. Case Summary

```cypher
// Summary for Jostes deposition
MATCH (case:Case {project_uuid: "bdbded17-4690-5f8a-a6fb-538755da6e88"})
OPTIONAL MATCH (case)-[:HAS_DOCUMENT]->(doc:CaseDocument)
OPTIONAL MATCH (doc)-[:HAS_CHUNK]->(chunk:CaseChunk)
RETURN
  case.case_name as case_name,
  count(DISTINCT doc) as document_count,
  count(DISTINCT chunk) as chunk_count,
  sum(doc.page_count) as total_pages;
```

### 3. Find Chunks by Exhibit

```cypher
// Find all chunks from a specific exhibit
MATCH (c:CaseChunk {
  project_uuid: "bdbded17-4690-5f8a-a6fb-538755da6e88",
  exhibit_name: "Exhibit 1 - acuity answers to wombat interrogs"
})
RETURN c.chunk_index, c.page_number, c.text
ORDER BY c.chunk_index
LIMIT 10;
```

### 4. Sequential Reading (NEXT_CHUNK)

```cypher
// Follow sequential chunks in a document
MATCH path = (start:CaseChunk {document_uuid: "ae79fec3-bdd3-5605-ac10-4fef28ebdea6"})
             -[:NEXT_CHUNK*0..5]->(end:CaseChunk)
WHERE start.chunk_index = 0
RETURN [node in nodes(path) | node.text] as sequential_chunks;
```

### 5. Document Entity Links

```cypher
// Find documents that share entities (after enhancement)
MATCH (d1:CaseDocument {project_uuid: "bdbded17-4690-5f8a-a6fb-538755da6e88"})
     -[r:SHARES_ENTITY]->(d2:CaseDocument)
WHERE r.count >= 3
RETURN d1.exhibit_name, d2.exhibit_name, r.count as shared_entities
ORDER BY r.count DESC
LIMIT 20;
```

---

## Troubleshooting

### OCR Issues

**Problem**: `403 Forbidden` when calling Vertex AI
**Solution**: Ensure ADC is configured with `cloud-platform` scope:
```bash
gcloud auth application-default login
gcloud auth application-default print-access-token >/dev/null && echo "✓ ADC OK"
```

**Problem**: `429 Too Many Requests` (quota exceeded)
**Solution**: Reduce workers and add delay:
```bash
python -m final_fact.cli ocr \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo \
  --workers 1 \
  --request-delay-seconds 5
```

### Ingest Issues

**Problem**: `Command failed to spawn: Aborted`
**Solution**: Run with smaller scope or use `--resume`:
```bash
# Bounded batch
python -m final_fact.cli ingest \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo \
  --limit-docs 5 \
  --resume
```

**Problem**: OpenAI rate limiting (429 errors)
**Solution**: Increase retry/backoff:
```bash
python -m final_fact.cli ingest \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo \
  --retry 5 \
  --backoff-seconds 2
```

### Neo4j Connection Issues

**Problem**: `ServiceUnavailable: Failed to establish connection`
**Solution**: Verify credentials in `/Users/joe/Projects/.env`:
```bash
# Test connection
python3 -c "from neo4j import GraphDatabase; \
driver = GraphDatabase.driver('neo4j+s://6d98f1e5.databases.neo4j.io', \
auth=('neo4j', 'PASSWORD')); \
driver.verify_connectivity(); \
print('✓ Connected')"
```

---

## Best Practices

### 1. Case Isolation

- **DO**: Use unique, descriptive case names (e.g., "Jostes_depo", "Kunda v. Smith")
- **DO**: Use `--input-base-dir` for case-scoped pipelines
- **DON'T**: Mix multiple cases in the same `input/` directory without subdirectories

### 2. Batching & Resume

- **DO**: Use `--resume` for all production runs (safe checkpoint/restart)
- **DO**: Start with small batches (`--limit-docs 5`) to test
- **DO**: Use `--max-pages-per-doc` for quick tests
- **DON'T**: Run large batches without `--resume` (no recovery from failures)

### 3. OCR Performance

- **DO**: Use `--workers 1` and `--request-delay-seconds 5` to avoid quota limits
- **DO**: Check `ai_docs/validation/ocr_runs/` for error reports
- **DON'T**: Run OCR on already-processed files (check `input/{case}/organized/ocr/` first)

### 4. Documentation

- **DO**: Create context notes after completing work in `ai_docs/`
- **DO**: Review validation reports in `ai_docs/validation/` after each run
- **DO**: Update this CLAUDE.md when changing architecture

### 5. Neo4j Verification

- **DO**: Run verification queries after `load-neo4j` to confirm data integrity
- **DO**: Check `exhibit_name` preservation for deposition cases
- **DON'T**: Skip the `indexes` command (performance will suffer)

---

## Performance Expectations

### OCR (Vertex AI Mistral)

- **Speed**: ~25 pages/second (single worker)
- **Cost**: ~$0.0015 per page
- **Typical doc**: 100-page document = ~4 seconds, ~$0.15
- **Quota limit**: 60 requests/minute (use `--request-delay-seconds 5`)

### Ingest (OpenAI GPT-4o-mini)

- **Speed**: ~2-5 pages/second (depends on page length + API latency)
- **Cost**: ~$0.01 per 1000 chunks
- **Typical doc**: 17-page exhibit = ~1-2 minutes (49 chunks)
- **Rate limit**: 500 RPM (tier 1), use `--retry 5 --backoff-seconds 2`

### Neo4j Load

- **Speed**: ~1000 chunks/second (bulk UNWIND)
- **Typical case**: 18 exhibits, 149 chunks = <1 second
- **Large case**: 1,987 documents, 50,000 chunks = ~50 seconds

---

## Related Projects

This project is part of the ott.law legal AI platform ecosystem:

- **frontend/** - Web UI with MCP orchestration (SvelteKit + FastAPI)
- **fact_improve/** - Historical case document pipeline (Mistral OCR → Neo4j)
- **kg_loader/** - Treatise knowledge graph (PDF → S3 → Neo4j KG)
- **unify/** - Dropbox→S3→RDS document corpus platform (Refine Admin UI)

See `/Users/joe/Projects/CLAUDE.md` for ecosystem overview.

---

## Quick Start (TL;DR)

```bash
# 1. Setup
cd /Users/joe/Projects/final_fact
source venv/bin/activate

# 2. Configure Google ADC
gcloud auth application-default login

# 3. Run full pipeline (Jostes deposition)
python -m final_fact.cli ocr --case-name "Jostes_depo" --input-base-dir input/Jostes_depo
python -m final_fact.cli ingest --case-name "Jostes_depo" --input-base-dir input/Jostes_depo --resume
python -m final_fact.cli indexes --case-name "Jostes_depo" --input-base-dir input/Jostes_depo
python -m final_fact.cli load-neo4j --case-name "Jostes_depo" --input-base-dir input/Jostes_depo

# 4. Enhancement (optional)
python -m final_fact.cli load-entities --case-name "Jostes_depo" --input-base-dir input/Jostes_depo
python -m final_fact.cli build-doc-entity-links --case-name "Jostes_depo" --input-base-dir input/Jostes_depo
python -m final_fact.cli markov-enrich --case-name "Jostes_depo" --input-base-dir input/Jostes_depo

# 5. Verify in Neo4j
# (Use Cypher queries from "Common Cypher Queries" section)
```

---

## Version History

- **2026-01-20**: Initial CLAUDE.md created during Jostes deposition ingestion
- **2026-01-20**: Documented exhibit name preservation requirement and implementation
- **2026-01-20**: Added comprehensive CLI reference and troubleshooting guide

---

**Character Count**: ~20,000 (well under 30k limit)
**Focus**: Pipeline architecture, CLI commands, Jostes deposition status, best practices
**Omitted**: Internal implementation details (see source code comments)

For operational guides, see `ai_docs/runbooks/01_local_run.md`.
