# Runbook: Next steps — install Neo4j MCP + validate loads

This runbook extends `02_next_iteration_scale_and_resume.md` with:
- installing the **official Neo4j MCP server** locally (so Cursor/Claude can run Cypher via MCP tools)
- running the pipeline at scale (resumable)
- validating the post-load graph using the **Neo4j MCP tool** (read-only recommended)

---

## Prereqs

- You have a working Python venv for this repo.
- `/Users/joe/Projects/.env` contains:
  - `OPENAI_API_KEY`
  - `NEO4J_FACT_URI`
  - `NEO4J_FACT_USERNAME`
  - `NEO4J_FACT_PASSWORD`
  - `NEO4J_FACT_DATABASE` (optional; default `neo4j`)

---

## 1) Install the official Neo4j MCP server (macOS)

### Option A (recommended): install `neo4j-mcp` from Neo4j GitHub releases

- Download from: `https://github.com/neo4j/mcp/releases`
- Extract the archive and install the binary on PATH:

```bash
chmod +x neo4j-mcp
sudo mv neo4j-mcp /usr/local/bin/
neo4j-mcp -v
```

### Notes

- The Neo4j MCP server uses these env vars (names differ from this repo’s `.env`):
  - `NEO4J_URI` (maps from `NEO4J_FACT_URI`)
  - `NEO4J_USERNAME` (maps from `NEO4J_FACT_USERNAME`)
  - `NEO4J_PASSWORD` (maps from `NEO4J_FACT_PASSWORD`)
  - `NEO4J_DATABASE` (maps from `NEO4J_FACT_DATABASE`)
  - `NEO4J_READ_ONLY=true` (recommended for validation runs)

---

## 2) Configure Cursor to use Neo4j MCP (project-scoped)

Because Cursor MCP config files typically live under `.cursor/` (which is often ignored by editors/tools),
this repo provides a **no-secrets** wrapper script and a copy/paste config snippet.

### 2a) Use the no-secrets wrapper (recommended)

This wrapper pulls **FACT graph** creds from AWS Secrets Manager at runtime and starts `neo4j-mcp`:
- `scripts/run_neo4j_mcp_fact.sh`

It uses:
- AWS profile: `unify-old` (override with `AWS_PROFILE=...`)
- Secret ID: `legal-fact/neo4j-credentials` (override with `NEO4J_FACT_SECRET_ID=...`)

### 2b) Create the Cursor MCP config (local file)

Create or edit:
- `/Users/joe/Projects/final_fact/.cursor/mcp.json` (project-scoped)
  - If `.cursor/` is ignored in your setup, that’s OK — it’s meant to be local.

Example configuration (read-only, **no Neo4j creds stored**):

```json
{
  "mcpServers": {
    "neo4j-fact": {
      "type": "stdio",
      "command": "/Users/joe/Projects/final_fact/scripts/run_neo4j_mcp_fact.sh",
      "args": [],
      "env": {
        "AWS_PROFILE": "unify-old",
        "AWS_REGION": "us-east-1",
        "NEO4J_FACT_SECRET_ID": "legal-fact/neo4j-credentials",
        "NEO4J_READ_ONLY": "true"
      }
    }
  }
}
```

Then restart Cursor and verify:
- Settings → Tools & MCP
- confirm server `neo4j-fact` is healthy
- in chat, ask: “list MCP tools”

---

## 3) Scale + resume execution (full corpus)

```bash
cd /Users/joe/Projects/final_fact
source venv/bin/activate

# (Optional, recommended once) ensure constraints/indexes exist
python -m final_fact.cli indexes --case-name "Kunda v. Smith (final_fact)"

# Stage everything (resumable)
python -m final_fact.cli ingest --case-name "Kunda v. Smith (final_fact)" --workers 8

# Load everything to Neo4j (resumable)
python -m final_fact.cli load-neo4j --case-name "Kunda v. Smith (final_fact)"

# Attach analysis + report
python -m final_fact.cli ingest-analysis --case-name "Kunda v. Smith (final_fact)"
python -m final_fact.cli analysis-join-report --case-name "Kunda v. Smith (final_fact)" --top-n 100

# Embed docs + similarity (pruned)
python -m final_fact.cli embed-docs --case-name "Kunda v. Smith (final_fact)" --limit 2000
python -m final_fact.cli build-doc-similarity --case-name "Kunda v. Smith (final_fact)" --top-k 10 --min-score 0.75 --reset

# Entities + doc links
python -m final_fact.cli load-entities --case-name "Kunda v. Smith (final_fact)" --limit-chunks 200000
python -m final_fact.cli build-doc-entity-links --case-name "Kunda v. Smith (final_fact)"

# Markov enrichment
python -m final_fact.cli markov-enrich --case-name "Kunda v. Smith (final_fact)" --limit-chunks 200000
```

### Resume semantics

- Staging checkpoint: `output/staging/{project_uuid}/manifest.json`
- Status per doc: `pending|staged|loaded|failed`
- Safe rerun: `ingest` skips `staged/loaded` docs; `load-neo4j` skips `loaded` docs.

### Evidence capture

Each run writes one report to:
- `ai_docs/validation/ingest_runs/ingest_run_YYYYMMDD_HHMMSS.md`
- `ai_docs/validation/ingest_runs/load_neo4j_run_YYYYMMDD_HHMMSS.md`

---

## 4) Post-load validation using Neo4j MCP (read-only)

Once the Neo4j MCP server is configured, use its Cypher tool to run:

### Confirm Case node + document counts

```cypher
MATCH (c:Case {project_uuid: $project_uuid})
OPTIONAL MATCH (c)-[:HAS_DOCUMENT]->(d:CaseDocument)
RETURN c.case_name AS case_name, count(d) AS documents;
```

### Confirm chunk counts and integrity (project-scoped)

```cypher
MATCH (d:CaseDocument {project_uuid: $project_uuid})
OPTIONAL MATCH (d)-[:HAS_CHUNK]->(ch:CaseChunk)
RETURN count(DISTINCT d) AS documents, count(ch) AS chunks;
```

### Spot-check chunk ordering

```cypher
MATCH (d:CaseDocument {project_uuid: $project_uuid})
MATCH (d)-[:HAS_CHUNK]->(c:CaseChunk)
WITH d, c ORDER BY d.document_uuid, c.chunk_index
WITH d, collect(c.chunk_index)[0..20] AS idxs
RETURN d.title AS title, idxs
LIMIT 10;
```

### Failure scan (docs staged but missing in Neo4j)

```cypher
MATCH (d:CaseDocument {project_uuid: $project_uuid})
RETURN count(d) AS documents_loaded;
```

Compare against:
- `output/staging/{project_uuid}/manifest.json` counts and `status=loaded`.

---

## 5) Troubleshooting quick hits

- If `ingest` is slow:
  - reduce `--max-pages-per-doc` for experimentation
  - increase `--workers` gradually
  - increase `--retry` and `--backoff-seconds` for flaky OCR pages
- If `load-neo4j` fails:
  - run `python -m final_fact.cli indexes ...` again (safe)
  - re-run `load-neo4j` (resume will skip already-loaded docs)

