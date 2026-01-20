# Context: final_fact scaffold plan (2026-01-14)

## Objective

Create an optimal, professional `final_fact` codebase that applies the **final Kunda loader** setup but replaces OCR+LaTeX chunking with:

- input markdown from `input/organized/ocr/*.md`
- OpenAI chunking that **preserves page numbers**
- JSON staging locally
- load to Neo4j FACT graph with Kunda-style graph shape
- integrate `analysis.csv` into the graph + document similarity edges
- enable Markov-style retrieval via precomputed per-chunk local context

## Key decisions

- **Neo4j target**: existing FACT graph credentials (`NEO4J_FACT_*` in `/Users/joe/Projects/.env`)\n+- **Staging location**: local folder `/Users/joe/Projects/final_fact/output/staging/`\n+- **Project UUID**: deterministic UUIDv5 derived from case name by default (override via `FINAL_FACT_PROJECT_UUID`)\n+
## Kunda reference points (fact_improve)

- Base loader: `/Users/joe/Projects/fact_improve/load_kunda_to_neo4j.py`\n+- Markov retrieval utilities: `/Users/joe/Projects/fact_improve/libs/markov_retrieval/*`\n+- Kunda enrichment pipeline scripts: `/Users/joe/Projects/fact_improve/input/Kunda, Nagaraj/Kunda v. Smith/ai_docs/enrichment/pipeline/*`\n+
## Next implementation milestones

1. Scaffold `final_fact` package + docs.\n+2. Markdown page parsing + OpenAI chunk+entities → staging JSON.\n+3. Neo4j loader + indexes + embeddings.\n+4. analysis.csv ingest + doc similarity edges.\n+5. Canonical entities + Markov enrichment fields.\n+
