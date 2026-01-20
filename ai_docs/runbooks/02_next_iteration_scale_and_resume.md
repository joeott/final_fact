# Runbook: Next iteration — scale + resumability (1,400+ docs)

This runbook describes the **next iteration plan** after the current analysis-join improvements: making ingestion **fast, resumable, and safe** for the full corpus.

## Objectives

- Process **all** `input/organized/ocr/*.md` with predictable throughput.
- Make runs **resumable** (crash-safe; restart without losing progress).
- Add **retry/backoff** and per-document error capture.
- Add **idempotent** behavior (safe re-run: does not duplicate docs/chunks).
- Produce a **run report** (counts, errors, durations) under `ai_docs/validation/`.

## Proposed changes (implementation outline)

### 1) Staging resumability

Treat `output/staging/{project_uuid}/manifest.json` as a checkpoint.

Add per-document status tracking in the manifest:
- `status`: `pending|staged|loaded|failed`
- `error` (string, if failed)
- `chunk_count`, `page_count_detected`
- `started_at`, `completed_at`

### 2) Concurrency + batching controls

Add CLI flags:
- `--workers` (thread pool size)
- `--limit-docs` / `--start-at` / `--only-prefix DOC_####`
- `--max-pages-per-doc` (keep)
- `--retry N` and `--backoff-seconds`

### 3) Neo4j loading as a separate resumable step

Keep a two-phase approach:
- `ingest` (stage JSON)
- `load-neo4j` (read staging + upsert)

Add a `--resume` mode to `load-neo4j` that skips docs already marked loaded.

### 4) Validation evidence capture

Write a single report per run to:

- `ai_docs/validation/ingest_runs/ingest_run_YYYYMMDD_HHMMSS.md`

Include:
- number of markdown files scanned
- staged docs/chunks
- loaded docs/chunks
- failures (top N)
- timing and per-stage rates

## Suggested execution sequence for full corpus

```bash
cd /Users/joe/Projects/final_fact
source venv/bin/activate

# Stage everything (resumable)
# NOTE: this assumes the next-iteration changes land (so “all docs” is supported).
python -m final_fact.cli ingest --case-name "Kunda v. Smith (final_fact)"

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

## Notes / constraints

- This iteration should keep schema **minimal** and avoid adding compatibility properties unless a constraint/index requires them.
- We will preserve deterministic UUID strategy so reprocessing does not create duplicates.
