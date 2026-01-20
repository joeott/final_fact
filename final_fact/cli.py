"""
CLI entrypoint for final_fact.

Primary goal (Round 1): markdown → OpenAI chunking → local staging JSON.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import List, Optional

from .config import deterministic_chunk_uuid, deterministic_document_uuid, load_settings
from .io.staging import LocalStagingStore, ManifestDocument, StagedDocumentRef
from .llm.openai_client import OpenAIConfig, OpenAIService
from .llm.chunk_and_entities import OpenAIPageChunker
from .parsing.page_markers import split_markdown_into_pages
from .graph.neo4j_client import Neo4jClient, Neo4jConfig
from .graph.indexes import apply_constraints_and_indexes
from .graph.loader import load_project_staging
from .parsing.analysis_csv import read_analysis_csv
from .graph.similarity import ingest_analysis_rows, embed_documents, build_document_similarity_edges
from .entities.load_entities import load_entities_pipeline
from .graph.markov_enrichment import enrich_markov_context
from .parsing.normalize_keys import extract_doc_prefix, normalized_title_key, organized_basename
from .graph.analysis_join_report import write_analysis_join_report
from .graph.document_links import build_shares_entity_edges
from .ocr.vertex_mistral import VertexMistralOcrConfig, ocr_pdf_to_markdown
from .validation.ingest_run_report import write_ingest_run_report, write_load_run_report
from .validation.ocr_run_report import write_ocr_run_report


def _iter_markdown_files(input_dir: Path) -> List[Path]:
    return sorted([p for p in input_dir.glob("*.md") if p.is_file()])


def _resolve_input_base_dir(arg: Optional[str]) -> Optional[str]:
    """
    CLI passes this through to `load_settings(input_base_dir=...)`.
    We accept either:
    - absolute path: /Users/joe/Projects/final_fact/input/Jostes_depo
    - relative path: input/Jostes_depo (resolved relative to project root inside load_settings)
    """
    if not arg:
        return None
    p = Path(arg)
    if p.is_absolute():
        return str(p)
    # Resolve relative to current working directory (repo root in typical usage).
    return str((Path.cwd() / p).resolve())


def cmd_ingest(args: argparse.Namespace) -> int:
    settings = load_settings(
        case_name=args.case_name,
        tenant_uuid=args.tenant_uuid,
        project_uuid=args.project_uuid,
        input_base_dir=_resolve_input_base_dir(getattr(args, "input_base_dir", None)),
    )
    input_dir = settings.input_ocr_dir
    if not input_dir.exists():
        raise RuntimeError(f"OCR input dir not found: {input_dir}")

    store = LocalStagingStore(settings.output_staging_dir, settings.project_uuid)

    all_files = _iter_markdown_files(input_dir)
    scanned_files = len(all_files)

    # Filters: prefix / start-at / limit
    files = all_files
    if args.only_prefix:
        want = args.only_prefix.upper()
        files = [p for p in files if extract_doc_prefix(p.name) == want]
    if args.start_at:
        files = files[int(args.start_at) :]
    if args.limit_docs is not None:
        files = files[: int(args.limit_docs)]

    # Pre-populate / refresh manifest records (checkpoint)
    manifest_seed: List[ManifestDocument] = []
    for md_path in files:
        doc_key = md_path.name
        document_uuid = deterministic_document_uuid(settings.project_uuid, doc_key)
        manifest_seed.append(
            ManifestDocument(
                document_uuid=document_uuid,
                title=md_path.name,
                source_file=md_path.stem,
                ocr_markdown_path=str(md_path),
                source_file_path=str(md_path),
                status="pending",
            )
        )
    store.upsert_manifest_documents(manifest_seed)

    existing_idx = store.read_manifest_documents_index()
    to_process: List[Path] = []
    skipped = 0
    for md_path in files:
        doc_key = md_path.name
        document_uuid = deterministic_document_uuid(settings.project_uuid, doc_key)
        existing = existing_idx.get(document_uuid)

        if args.resume and existing and existing.status in ("staged", "loaded"):
            doc_dir = store.project_dir / document_uuid
            meta_ok = (doc_dir / "document_metadata.json").exists()
            chunks_ok = (doc_dir / "chunks").exists()
            if meta_ok and chunks_ok:
                skipped += 1
                continue

        to_process.append(md_path)

    # Thread-local OpenAI clients to avoid cross-thread surprises
    _tls = {}

    def _get_chunker() -> OpenAIPageChunker:
        import threading

        tid = threading.get_ident()
        if tid in _tls:
            return _tls[tid]
        svc = OpenAIService(
            OpenAIConfig(
                api_key=settings.openai_api_key,
                chunk_model=settings.openai_chunk_model,
                embedding_model=settings.openai_embedding_model,
            )
        )
        ch = OpenAIPageChunker(service=svc, target_chars=args.target_chunk_chars)
        _tls[tid] = ch
        return ch

    def _chunk_page_with_retry(*, page_number: int, page_text: str) -> List[Any]:
        last: Optional[Exception] = None
        for attempt in range(int(args.retry) + 1):
            try:
                return _get_chunker().chunk_page(page_number=page_number, page_text=page_text)
            except Exception as e:
                last = e
                if attempt >= int(args.retry):
                    break
                time.sleep(float(args.backoff_seconds) * (2**attempt))
        raise RuntimeError(f"chunk_page failed after retries: {last}")

    def _stage_one(md_path: Path) -> Dict[str, Any]:
        started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        doc_key = md_path.name
        document_uuid = deterministic_document_uuid(settings.project_uuid, doc_key)
        source_file = md_path.stem
        # For deposition prep, the file name represents the exhibit name and must be preserved.
        exhibit_name = md_path.stem

        raw = md_path.read_text(encoding="utf-8", errors="ignore")
        pages = split_markdown_into_pages(raw)
        if args.max_pages_per_doc is not None:
            pages = pages[: int(args.max_pages_per_doc)]

        # Stable full_text offsets: we insert \n\n between pages.
        page_offsets = {}
        cursor = 0
        ordered_pages = pages
        for i, p in enumerate(ordered_pages):
            page_offsets[p.page_number] = cursor
            cursor += len(p.text)
            if i < len(ordered_pages) - 1:
                cursor += 2

        # Join keys for analysis.csv alignment
        doc_prefix = extract_doc_prefix(md_path.name)
        org_base = organized_basename(md_path.name)
        norm_key = normalized_title_key(md_path.name)

        chunk_index = 0
        for p in ordered_pages:
            if not p.text.strip():
                continue
            page_chunks = _chunk_page_with_retry(page_number=p.page_number, page_text=p.text)
            base = page_offsets.get(p.page_number, 0)
            for pc in page_chunks:
                full_start = base + pc.page_start
                full_end = base + pc.page_end
                chunk_uuid = deterministic_chunk_uuid(document_uuid, full_start, full_end)

                chunk_data = {
                    "tenant_uuid": settings.tenant_uuid,
                    "project_uuid": settings.project_uuid,
                    "document_uuid": document_uuid,
                    "chunk_uuid": chunk_uuid,
                    # Compatibility with existing FACT graph utilities:
                    "id": chunk_uuid,
                    # Exhibit identity (must be preserved exactly)
                    "exhibit_name": exhibit_name,
                    "chunk_index": chunk_index,
                    "page_number": p.page_number,
                    "char_start": full_start,
                    "char_end": full_end,
                    "text": pc.text,
                    "clean_text": pc.text.strip(),
                    # Neo4j properties cannot store list-of-maps; store JSON + a flat string list.
                    "entities_json": json.dumps(pc.entities, ensure_ascii=False),
                    "entities_flat": [f"{e.get('entity_type','OTHER')}::{e.get('text','')}" for e in pc.entities],
                    "source_file": source_file,
                    "source_file_path": str(md_path),
                    "ocr_markdown_path": str(md_path),
                }
                store.write_chunk(document_uuid, chunk_uuid, chunk_data)
                chunk_index += 1

        staged_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        doc_meta = {
            "tenant_uuid": settings.tenant_uuid,
            "project_uuid": settings.project_uuid,
            "case_name": settings.case_name,
            "document_uuid": document_uuid,
            "title": md_path.name,
            "source_file": source_file,
            # Exhibit identity (must be preserved exactly)
            "exhibit_name": exhibit_name,
            "doc_prefix": doc_prefix,
            "organized_basename": org_base,
            "normalized_title_key": norm_key,
            "ocr_markdown_path": str(md_path),
            "source_file_path": str(md_path),  # provenance; later can map to original PDF
            "page_count_detected": max([p.page_number for p in ordered_pages], default=0),
            "chunk_count": chunk_index,
            "staged_at": staged_at,
        }
        store.write_document_metadata(document_uuid, doc_meta)

        return {
            "document_uuid": document_uuid,
            "title": md_path.name,
            "chunk_count": chunk_index,
            "page_count_detected": doc_meta["page_count_detected"],
            "started_at": started_at,
            "completed_at": staged_at,
            "staged_at": staged_at,
            "error": "",
        }

    run_started = time.perf_counter()
    staged_docs = 0
    staged_chunks = 0
    failed_docs = 0
    failures: List[Dict[str, str]] = []

    workers = int(args.workers or settings.default_max_workers)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_stage_one, p): p for p in to_process}
        for fut in as_completed(futs):
            md_path = futs[fut]
            try:
                r = fut.result()
                staged_docs += 1
                staged_chunks += int(r.get("chunk_count") or 0)
                store.update_manifest_document(
                    r["document_uuid"],
                    title=r.get("title", md_path.name),
                    source_file=md_path.stem,
                    ocr_markdown_path=str(md_path),
                    source_file_path=str(md_path),
                    status="staged",
                    error="",
                    chunk_count=int(r.get("chunk_count") or 0),
                    page_count_detected=int(r.get("page_count_detected") or 0),
                    started_at=r.get("started_at", ""),
                    completed_at=r.get("completed_at", ""),
                    staged_at=r.get("staged_at", ""),
                )
            except Exception as e:
                failed_docs += 1
                doc_key = md_path.name
                document_uuid = deterministic_document_uuid(settings.project_uuid, doc_key)
                err = str(e)
                failures.append({"path": str(md_path), "title": md_path.name, "document_uuid": document_uuid, "error": err})
                now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                store.update_manifest_document(
                    document_uuid,
                    title=md_path.name,
                    source_file=md_path.stem,
                    ocr_markdown_path=str(md_path),
                    source_file_path=str(md_path),
                    status="failed",
                    error=err,
                    started_at=now,
                    completed_at=now,
                )

    duration = time.perf_counter() - run_started
    report_path = write_ingest_run_report(
        project_root=settings.project_root,
        case_name=settings.case_name,
        project_uuid=settings.project_uuid,
        scanned_files=scanned_files,
        selected_files=len(files),
        skipped=skipped,
        staged_docs=staged_docs,
        staged_chunks=staged_chunks,
        failed_docs=failed_docs,
        failures=failures,
        duration_seconds=duration,
        args_summary={
            "workers": workers,
            "limit_docs": args.limit_docs,
            "start_at": args.start_at,
            "only_prefix": args.only_prefix,
            "max_pages_per_doc": args.max_pages_per_doc,
            "retry": args.retry,
            "backoff_seconds": args.backoff_seconds,
            "target_chunk_chars": args.target_chunk_chars,
            "resume": args.resume,
        },
    )

    print(f"Staged {staged_docs} documents ({staged_chunks} chunks); failed={failed_docs}; skipped={skipped}")
    print(f"Checkpoint manifest: {store.project_dir / 'manifest.json'}")
    print(f"Run report: {report_path}")
    return 0


def cmd_ocr(args: argparse.Namespace) -> int:
    settings = load_settings(
        case_name=args.case_name,
        tenant_uuid=args.tenant_uuid,
        project_uuid=args.project_uuid,
        input_base_dir=_resolve_input_base_dir(getattr(args, "input_base_dir", None)),
    )

    input_base = Path(settings.input_base_dir)
    if not input_base.exists():
        raise RuntimeError(f"Input base dir not found: {input_base}")

    # Source PDFs are expected at the top-level of input_base_dir for this workflow.
    all_pdfs = sorted([p for p in input_base.glob("*.pdf") if p.is_file()])
    scanned_files = len(all_pdfs)

    pdfs = all_pdfs
    if args.start_at:
        pdfs = pdfs[int(args.start_at) :]
    if args.limit_docs is not None:
        pdfs = pdfs[: int(args.limit_docs)]

    ocr_dir = settings.input_ocr_dir
    ocr_dir.mkdir(parents=True, exist_ok=True)

    ocr_raw_dir = None
    if args.write_raw_json:
        ocr_raw_dir = Path(settings.input_base_dir) / "organized" / "ocr_raw"
        ocr_raw_dir.mkdir(parents=True, exist_ok=True)

    cfg = VertexMistralOcrConfig(max_pages_per_request=int(args.max_pages_per_request))

    run_started = time.perf_counter()
    ok = 0
    failed = 0
    skipped = 0
    failures: List[Dict[str, str]] = []

    def _one(pdf_path: Path) -> Dict[str, Any]:
        # Throttle between requests to reduce 429s for base-model quotas.
        if float(args.request_delay_seconds) > 0:
            time.sleep(float(args.request_delay_seconds))
        out_md = ocr_dir / f"{pdf_path.stem}.md"
        return ocr_pdf_to_markdown(
            pdf_path=pdf_path,
            out_md_path=out_md,
            cfg=cfg,
            force=bool(args.force),
            ocr_raw_dir=ocr_raw_dir,
        )

    workers = int(args.workers or settings.default_max_workers)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, p): p for p in pdfs}
        for fut in as_completed(futs):
            pdf_path = futs[fut]
            try:
                r = fut.result()
                if r.get("status") == "cached":
                    skipped += 1
                else:
                    ok += 1
            except Exception as e:
                failed += 1
                failures.append({"path": str(pdf_path), "title": pdf_path.name, "error": str(e)})

    duration = time.perf_counter() - run_started
    report_path = write_ocr_run_report(
        project_root=settings.project_root,
        case_name=settings.case_name,
        project_uuid=settings.project_uuid,
        input_base_dir=str(settings.input_base_dir),
        scanned_files=scanned_files,
        selected_files=len(pdfs),
        skipped_cached=skipped,
        ocr_ok=ok,
        ocr_failed=failed,
        failures=failures,
        duration_seconds=duration,
        args_summary={
            "workers": workers,
            "limit_docs": args.limit_docs,
            "start_at": args.start_at,
            "force": bool(args.force),
            "max_pages_per_request": int(args.max_pages_per_request),
            "write_raw_json": bool(args.write_raw_json),
        },
    )

    print(f"OCR complete: ok={ok}, failed={failed}, skipped_cached={skipped} (output={ocr_dir})")
    print(f"Run report: {report_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="final_fact")
    sub = p.add_subparsers(dest="cmd", required=True)

    ocr = sub.add_parser("ocr", help="OCR PDFs into markdown with page markers (Mistral via Vertex)")
    ocr.add_argument("--case-name", required=True)
    ocr.add_argument("--tenant-uuid", default="ott-law-firm")
    ocr.add_argument("--project-uuid", default=None)
    ocr.add_argument(
        "--input-base-dir",
        default=None,
        help="Case-scoped input root containing PDFs (e.g. input/Jostes_depo). OCR markdown written to <input-base-dir>/organized/ocr/*.md",
    )
    ocr.add_argument("--workers", type=int, default=None)
    ocr.add_argument("--limit-docs", type=int, default=None)
    ocr.add_argument("--start-at", type=int, default=0)
    ocr.add_argument("--force", action="store_true", help="Re-OCR even if cached markdown exists")
    ocr.add_argument("--max-pages-per-request", type=int, default=25)
    ocr.add_argument(
        "--request-delay-seconds",
        type=float,
        default=2.0,
        help="Sleep this many seconds before each OCR request (helps avoid 429 quota errors).",
    )
    ocr.add_argument("--write-raw-json", action="store_true", help="Write per-chunk OCR raw JSON to organized/ocr_raw/")
    ocr.set_defaults(func=cmd_ocr)

    ingest = sub.add_parser("ingest", help="Chunk OCR markdown and write staging JSON")
    ingest.add_argument("--case-name", required=True)
    ingest.add_argument("--tenant-uuid", default="ott-law-firm")
    ingest.add_argument("--project-uuid", default=None)
    ingest.add_argument(
        "--input-base-dir",
        default=None,
        help="Case-scoped input root (e.g. input/Jostes_depo). OCR markdown expected at <input-base-dir>/organized/ocr/*.md",
    )
    ingest.add_argument("--workers", type=int, default=None)
    ingest.add_argument("--limit-docs", type=int, default=None)
    ingest.add_argument("--start-at", type=int, default=0)
    ingest.add_argument("--only-prefix", type=str, default=None, help="Restrict to a DOC_#### prefix")
    ingest.add_argument("--max-pages-per-doc", type=int, default=None)
    ingest.add_argument("--target-chunk-chars", type=int, default=1200)
    ingest.add_argument("--retry", type=int, default=2)
    ingest.add_argument("--backoff-seconds", type=float, default=1.0)
    ingest.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        default=True,
        help="Skip docs already staged/loaded in manifest.json",
    )
    ingest.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Do not skip staged/loaded docs (still idempotent, but slower)",
    )
    ingest.set_defaults(func=cmd_ingest)

    idx = sub.add_parser("indexes", help="Create Neo4j constraints and indexes")
    idx.add_argument("--case-name", required=True)
    idx.add_argument("--tenant-uuid", default="ott-law-firm")
    idx.add_argument("--project-uuid", default=None)
    idx.add_argument("--input-base-dir", default=None, help="Case-scoped input root (e.g. input/Jostes_depo)")
    idx.set_defaults(func=cmd_indexes)

    load = sub.add_parser("load-neo4j", help="Load staged JSON into Neo4j")
    load.add_argument("--case-name", required=True)
    load.add_argument("--tenant-uuid", default="ott-law-firm")
    load.add_argument("--project-uuid", default=None)
    load.add_argument("--input-base-dir", default=None, help="Case-scoped input root (e.g. input/Jostes_depo)")
    load.add_argument("--limit-docs", type=int, default=None)
    load.add_argument("--start-at", type=int, default=0)
    load.add_argument("--only-prefix", type=str, default=None, help="Restrict to a DOC_#### prefix")
    load.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        default=True,
        help="Skip documents already marked loaded in manifest.json",
    )
    load.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Do not skip loaded documents (still idempotent, but slower)",
    )
    load.set_defaults(func=cmd_load_neo4j)

    a = sub.add_parser("ingest-analysis", help="Attach analysis.csv fields to documents")
    a.add_argument("--case-name", required=True)
    a.add_argument("--tenant-uuid", default="ott-law-firm")
    a.add_argument("--project-uuid", default=None)
    a.add_argument("--input-base-dir", default=None, help="Case-scoped input root (e.g. input/Jostes_depo)")
    a.set_defaults(func=cmd_ingest_analysis)

    rpt = sub.add_parser("analysis-join-report", help="Write analysis join coverage report to ai_docs/")
    rpt.add_argument("--case-name", required=True)
    rpt.add_argument("--tenant-uuid", default="ott-law-firm")
    rpt.add_argument("--project-uuid", default=None)
    rpt.add_argument("--input-base-dir", default=None, help="Case-scoped input root (e.g. input/Jostes_depo)")
    rpt.add_argument("--top-n", type=int, default=50)
    rpt.set_defaults(func=cmd_analysis_join_report)

    links = sub.add_parser("build-doc-entity-links", help="Create SHARES_ENTITY edges between documents")
    links.add_argument("--case-name", required=True)
    links.add_argument("--tenant-uuid", default="ott-law-firm")
    links.add_argument("--project-uuid", default=None)
    links.add_argument("--input-base-dir", default=None, help="Case-scoped input root (e.g. input/Jostes_depo)")
    links.add_argument("--min-entity-mentions", type=int, default=3)
    links.add_argument("--limit-entities", type=int, default=5000)
    links.add_argument("--max-docs-per-entity", type=int, default=50)
    links.add_argument("--min-shared-entities", type=int, default=2)
    links.set_defaults(func=cmd_build_doc_entity_links)

    ed = sub.add_parser("embed-docs", help="Compute summary embeddings for documents")
    ed.add_argument("--case-name", required=True)
    ed.add_argument("--tenant-uuid", default="ott-law-firm")
    ed.add_argument("--project-uuid", default=None)
    ed.add_argument("--input-base-dir", default=None, help="Case-scoped input root (e.g. input/Jostes_depo)")
    ed.add_argument("--limit", type=int, default=200)
    ed.set_defaults(func=cmd_embed_docs)

    sim = sub.add_parser("build-doc-similarity", help="Create SIMILAR_TO edges between documents")
    sim.add_argument("--case-name", required=True)
    sim.add_argument("--tenant-uuid", default="ott-law-firm")
    sim.add_argument("--project-uuid", default=None)
    sim.add_argument("--input-base-dir", default=None, help="Case-scoped input root (e.g. input/Jostes_depo)")
    sim.add_argument("--top-k", type=int, default=10)
    sim.add_argument("--max-edges-per-doc", type=int, default=None)
    sim.add_argument("--limit-docs", type=int, default=200)
    sim.add_argument("--min-score", type=float, default=0.75)
    sim.add_argument("--reset", action="store_true", help="Delete existing SIMILAR_TO edges for project before rebuilding")
    sim.set_defaults(func=cmd_build_doc_similarity)

    ent = sub.add_parser("load-entities", help="Canonicalize entities and load entity graph")
    ent.add_argument("--case-name", required=True)
    ent.add_argument("--tenant-uuid", default="ott-law-firm")
    ent.add_argument("--project-uuid", default=None)
    ent.add_argument("--input-base-dir", default=None, help="Case-scoped input root (e.g. input/Jostes_depo)")
    ent.add_argument("--limit-chunks", type=int, default=20000)
    ent.set_defaults(func=cmd_load_entities)

    mk = sub.add_parser("markov-enrich", help="Compute Markov neighbor_summary/traversal_hints")
    mk.add_argument("--case-name", required=True)
    mk.add_argument("--tenant-uuid", default="ott-law-firm")
    mk.add_argument("--project-uuid", default=None)
    mk.add_argument("--input-base-dir", default=None, help="Case-scoped input root (e.g. input/Jostes_depo)")
    mk.add_argument("--limit-chunks", type=int, default=50000)
    mk.set_defaults(func=cmd_markov_enrich)

    return p


def _neo4j_client_from_settings(
    case_name: str, tenant_uuid: str, project_uuid: Optional[str], input_base_dir: Optional[str]
) -> tuple[Neo4jClient, str, str, str, Path]:
    settings = load_settings(
        case_name=case_name,
        tenant_uuid=tenant_uuid,
        project_uuid=project_uuid,
        input_base_dir=_resolve_input_base_dir(input_base_dir),
    )
    client = Neo4jClient(
        Neo4jConfig(
            uri=settings.neo4j_uri,
            username=settings.neo4j_username,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        )
    )
    return client, settings.tenant_uuid, settings.project_uuid, settings.case_name, settings.output_staging_dir


def cmd_indexes(args: argparse.Namespace) -> int:
    client, _, _, _, _ = _neo4j_client_from_settings(
        args.case_name, args.tenant_uuid, args.project_uuid, getattr(args, "input_base_dir", None)
    )
    try:
        client.verify()
        apply_constraints_and_indexes(client)
    finally:
        client.close()
    print("Indexes/constraints applied (best-effort).")
    return 0


def cmd_load_neo4j(args: argparse.Namespace) -> int:
    client, tenant_uuid, project_uuid, case_name, staging_root = _neo4j_client_from_settings(
        args.case_name, args.tenant_uuid, args.project_uuid, getattr(args, "input_base_dir", None)
    )
    settings = load_settings(
        case_name=args.case_name,
        tenant_uuid=args.tenant_uuid,
        project_uuid=args.project_uuid,
        input_base_dir=_resolve_input_base_dir(getattr(args, "input_base_dir", None)),
    )
    store = LocalStagingStore(settings.output_staging_dir, settings.project_uuid)
    try:
        client.verify()
        docs = sorted(store.list_manifest_documents(), key=lambda d: (d.title or d.document_uuid))
        if args.only_prefix:
            want = args.only_prefix.upper()
            docs = [d for d in docs if extract_doc_prefix(d.title) == want]
        if args.start_at:
            docs = docs[int(args.start_at) :]
        if args.limit_docs is not None:
            docs = docs[: int(args.limit_docs)]

        selected_docs = len(docs)
        skipped_loaded = 0
        docs_to_load: List[dict] = []
        for d in docs:
            if args.resume and d.status == "loaded":
                skipped_loaded += 1
                continue
            docs_to_load.append({"document_uuid": d.document_uuid})

        project_dir = Path(staging_root) / project_uuid
        run_started = time.perf_counter()
        stats = load_project_staging(
            client=client,
            project_dir=project_dir,
            tenant_uuid=tenant_uuid,
            project_uuid=project_uuid,
            case_name=case_name,
            limit_docs=None,
            docs_override=docs_to_load,
        )
        duration = time.perf_counter() - run_started

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for du in stats.documents_loaded_uuids:
            store.update_manifest_document(du, status="loaded", error="", loaded_at=now, completed_at=now)
        for f in stats.failures:
            du = f.get("document_uuid", "")
            if du:
                store.update_manifest_document(du, status="failed", error=f.get("error", ""), completed_at=now)

        report_path = write_load_run_report(
            project_root=settings.project_root,
            case_name=settings.case_name,
            project_uuid=settings.project_uuid,
            selected_docs=selected_docs,
            skipped_loaded=skipped_loaded,
            loaded_docs=stats.documents_loaded,
            loaded_chunks=stats.chunks_loaded,
            failed_docs=stats.documents_failed,
            failures=stats.failures,
            duration_seconds=duration,
            args_summary={
                "limit_docs": args.limit_docs,
                "start_at": args.start_at,
                "only_prefix": args.only_prefix,
                "resume": args.resume,
            },
        )
    finally:
        client.close()
    print(
        f"Loaded: {stats.documents_loaded} documents, {stats.chunks_loaded} chunks; "
        f"failed={stats.documents_failed}; skipped_loaded={skipped_loaded} (project_uuid={project_uuid})"
    )
    print(f"Checkpoint manifest: {store.project_dir / 'manifest.json'}")
    print(f"Run report: {report_path}")
    return 0


def _openai_service_from_settings(case_name: str, tenant_uuid: str, project_uuid: Optional[str]) -> tuple[OpenAIService, str]:
    settings = load_settings(case_name=case_name, tenant_uuid=tenant_uuid, project_uuid=project_uuid)
    svc = OpenAIService(
        OpenAIConfig(
            api_key=settings.openai_api_key,
            chunk_model=settings.openai_chunk_model,
            embedding_model=settings.openai_embedding_model,
        )
    )
    return svc, settings.project_uuid


def cmd_ingest_analysis(args: argparse.Namespace) -> int:
    client, _, project_uuid, _, _ = _neo4j_client_from_settings(
        args.case_name, args.tenant_uuid, args.project_uuid, getattr(args, "input_base_dir", None)
    )
    try:
        client.verify()
        settings = load_settings(
            case_name=args.case_name,
            tenant_uuid=args.tenant_uuid,
            project_uuid=args.project_uuid,
            input_base_dir=_resolve_input_base_dir(getattr(args, "input_base_dir", None)),
        )
        rows = read_analysis_csv(settings.input_analysis_csv)
        result = ingest_analysis_rows(client=client, project_uuid=project_uuid, rows=rows)
    finally:
        client.close()
    print(
        f"analysis.csv ingested onto {result.updated_documents} documents "
        f"(matched_rows={result.matched_rows}, unmatched_rows={result.unmatched_rows}, ambiguous_rows={result.ambiguous_rows}) "
        f"(project_uuid={project_uuid})"
    )
    return 0


def cmd_analysis_join_report(args: argparse.Namespace) -> int:
    client, _, project_uuid, _, _ = _neo4j_client_from_settings(
        args.case_name, args.tenant_uuid, args.project_uuid, getattr(args, "input_base_dir", None)
    )
    try:
        client.verify()
        settings = load_settings(
            case_name=args.case_name,
            tenant_uuid=args.tenant_uuid,
            project_uuid=args.project_uuid,
            input_base_dir=_resolve_input_base_dir(getattr(args, "input_base_dir", None)),
        )
        rows = read_analysis_csv(settings.input_analysis_csv)
        out_dir = settings.project_root / "ai_docs" / "validation" / "analysis_join"
        report_path = write_analysis_join_report(
            client=client,
            project_uuid=project_uuid,
            analysis_rows=rows,
            output_dir=out_dir,
            top_n=args.top_n,
        )
    finally:
        client.close()
    print(f"Wrote analysis join report: {report_path}")
    return 0


def cmd_build_doc_entity_links(args: argparse.Namespace) -> int:
    client, _, project_uuid, _, _ = _neo4j_client_from_settings(
        args.case_name, args.tenant_uuid, args.project_uuid, getattr(args, "input_base_dir", None)
    )
    try:
        client.verify()
        n = build_shares_entity_edges(
            client=client,
            project_uuid=project_uuid,
            min_entity_mentions=args.min_entity_mentions,
            limit_entities=args.limit_entities,
            max_docs_per_entity=args.max_docs_per_entity,
            min_shared_entities=args.min_shared_entities,
        )
    finally:
        client.close()
    print(f"Created/updated {n} SHARES_ENTITY edges (project_uuid={project_uuid})")
    return 0


def cmd_embed_docs(args: argparse.Namespace) -> int:
    client, _, project_uuid, _, _ = _neo4j_client_from_settings(
        args.case_name, args.tenant_uuid, args.project_uuid, getattr(args, "input_base_dir", None)
    )
    openai, _ = _openai_service_from_settings(args.case_name, args.tenant_uuid, args.project_uuid)
    try:
        client.verify()
        n = embed_documents(client=client, openai=openai, project_uuid=project_uuid, limit=args.limit)
    finally:
        client.close()
    print(f"Embedded {n} documents (project_uuid={project_uuid})")
    return 0


def cmd_build_doc_similarity(args: argparse.Namespace) -> int:
    client, _, project_uuid, _, _ = _neo4j_client_from_settings(
        args.case_name, args.tenant_uuid, args.project_uuid, getattr(args, "input_base_dir", None)
    )
    try:
        client.verify()
        n = build_document_similarity_edges(
            client=client,
            project_uuid=project_uuid,
            top_k=args.top_k,
            max_edges_per_doc=args.max_edges_per_doc,
            limit_docs=args.limit_docs,
            min_score=args.min_score,
            reset=args.reset,
        )
    finally:
        client.close()
    print(f"Created/updated {n} SIMILAR_TO edges (project_uuid={project_uuid})")
    return 0


def cmd_load_entities(args: argparse.Namespace) -> int:
    client, _, project_uuid, _, _ = _neo4j_client_from_settings(
        args.case_name, args.tenant_uuid, args.project_uuid, getattr(args, "input_base_dir", None)
    )
    try:
        client.verify()
        stats = load_entities_pipeline(client=client, project_uuid=project_uuid, limit_chunks=args.limit_chunks)
    finally:
        client.close()
    print(
        "Entities loaded: "
        f"raw={stats['raw_entities']}, canonical={stats['canonical_entities']}, "
        f"mentions={stats['mentions']}, cooccurs={stats['cooccurs']} (project_uuid={project_uuid})"
    )
    return 0


def cmd_markov_enrich(args: argparse.Namespace) -> int:
    client, _, project_uuid, _, _ = _neo4j_client_from_settings(
        args.case_name, args.tenant_uuid, args.project_uuid, getattr(args, "input_base_dir", None)
    )
    try:
        client.verify()
        n = enrich_markov_context(client=client, project_uuid=project_uuid, limit_chunks=args.limit_chunks)
    finally:
        client.close()
    print(f"Markov-enriched {n} chunks (project_uuid={project_uuid})")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

