# Runbook: local staging → Neo4j (scaffold)

This repo is scaffolded to run in small batches first.

## Setup

```bash
cd /Users/joe/Projects/final_fact
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Ensure `/Users/joe/Projects/.env` has:

- `OPENAI_API_KEY`
- `NEO4J_FACT_URI`, `NEO4J_FACT_USERNAME`, `NEO4J_FACT_PASSWORD`

Ensure **Google Vertex auth uses the same credentials as your Google CLI** (Application Default Credentials):

```bash
# 1) Use the same Google account you use with gcloud
gcloud auth login

# 2) Make those credentials available to Python via ADC (required for Vertex rawPredict)
gcloud auth application-default login

# 3) Ensure the correct project is active (this repo expects document-processor-v3)
gcloud config set project document-processor-v3

# Optional sanity check (should print a token)
gcloud auth application-default print-access-token >/dev/null && echo "ADC OK"
```

## Case-scoped OCR (recommended)

For cases where the source PDFs live in a single directory (example: `input/Jostes_depo/*.pdf`), generate OCR markdown with explicit page markers (`Page X of Y`) into a **case-scoped** location:

```bash
python -m final_fact.cli ocr \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo
```

This writes:
- OCR markdown: `input/Jostes_depo/organized/ocr/*.md`
- OCR run report: `ai_docs/validation/ocr_runs/ocr_run_*.md`

## Ingest a small sample (first 5 markdown files)

```bash
python -m final_fact.cli ingest \
  --case-name "Kunda v. Smith (final_fact)" \
  --limit-docs 5 \
  --max-pages-per-doc 5
```

For the case-scoped example above:

```bash
python -m final_fact.cli ingest \
  --case-name "Jostes_depo" \
  --input-base-dir input/Jostes_depo \
  --limit-docs 2 \
  --max-pages-per-doc 5
```

## Next steps (after ingest)

```bash
python -m final_fact.cli indexes --case-name "Kunda v. Smith (final_fact)"
python -m final_fact.cli load-neo4j --case-name "Kunda v. Smith (final_fact)"

# analysis.csv integration
python -m final_fact.cli ingest-analysis --case-name "Kunda v. Smith (final_fact)"
python -m final_fact.cli analysis-join-report --case-name "Kunda v. Smith (final_fact)"

# doc similarity (from analysis summaries)
python -m final_fact.cli embed-docs --case-name "Kunda v. Smith (final_fact)" --limit 500
python -m final_fact.cli build-doc-similarity --case-name "Kunda v. Smith (final_fact)" --top-k 10 --min-score 0.75 --reset

# entity graph + doc links
python -m final_fact.cli load-entities --case-name "Kunda v. Smith (final_fact)" --limit-chunks 50000
python -m final_fact.cli build-doc-entity-links --case-name "Kunda v. Smith (final_fact)"

# retrieval enrichment
python -m final_fact.cli markov-enrich --case-name "Kunda v. Smith (final_fact)" --limit-chunks 50000
```

