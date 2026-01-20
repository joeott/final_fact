"""
Local staging writer/reader.

Layout:
  output/staging/{project_uuid}/
    manifest.json
    {document_uuid}/
      document_metadata.json
      chunks/
        {chunk_uuid}.json
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class StagedDocumentRef:
    document_uuid: str
    title: str
    source_file: str
    ocr_markdown_path: str
    source_file_path: str
    chunk_count: int
    staged_at: str


@dataclass(frozen=True)
class ManifestDocument:
    """
    Status record for a single document in a project staging directory.

    Notes:
    - `status` is used by both phases (ingest, load-neo4j).
    - `started_at` / `completed_at` reflect the *most recent* phase attempt.
    """

    document_uuid: str
    title: str = ""
    source_file: str = ""
    ocr_markdown_path: str = ""
    source_file_path: str = ""

    status: str = "pending"  # pending|staged|loaded|failed
    error: str = ""

    chunk_count: int = 0
    page_count_detected: int = 0

    started_at: str = ""
    completed_at: str = ""
    staged_at: str = ""
    loaded_at: str = ""


def _coerce_manifest_document(d: Dict[str, Any]) -> ManifestDocument:
    """
    Backward compatible parser:
    - legacy manifests (Round 1) only had StagedDocumentRef fields.
    - if it looks staged but has no status, treat as `staged`.
    """

    base = {
        "document_uuid": str(d.get("document_uuid", "")),
        "title": str(d.get("title", "")),
        "source_file": str(d.get("source_file", "")),
        "ocr_markdown_path": str(d.get("ocr_markdown_path", "")),
        "source_file_path": str(d.get("source_file_path", "")),
        "status": str(d.get("status", "")) or "",
        "error": str(d.get("error", "")) or "",
        "chunk_count": int(d.get("chunk_count") or 0),
        "page_count_detected": int(d.get("page_count_detected") or 0),
        "started_at": str(d.get("started_at", "")) or "",
        "completed_at": str(d.get("completed_at", "")) or "",
        "staged_at": str(d.get("staged_at", "")) or "",
        "loaded_at": str(d.get("loaded_at", "")) or "",
    }

    if not base["status"]:
        # If there's a staged_at or chunk_count, it was staged in Round 1.
        if base["staged_at"] or base["chunk_count"] > 0:
            base["status"] = "staged"
        else:
            base["status"] = "pending"

    return ManifestDocument(**base)


def _merge_manifest_documents(existing: ManifestDocument, incoming: ManifestDocument) -> ManifestDocument:
    """
    Merge strategy:
    - Always take latest identity fields (title/paths), since files can move.
    - Preserve existing status unless incoming provides a stronger signal.
    - Update counts/timestamps when incoming has non-empty values.
    """

    ex = asdict(existing)
    inc = asdict(incoming)

    # Identity/provenance: prefer incoming (it reflects current filesystem).
    for k in ("title", "source_file", "ocr_markdown_path", "source_file_path"):
        if inc.get(k):
            ex[k] = inc[k]

    # Status: keep 'loaded' unless explicitly overridden by non-pending incoming.
    inc_status = (inc.get("status") or "").strip() or "pending"
    ex_status = (ex.get("status") or "").strip() or "pending"
    if inc_status != "pending":
        ex_status = inc_status
    ex["status"] = ex_status

    # Error:
    # - allow clearing error on successful transitions (staged/loaded)
    # - otherwise keep existing unless a new non-empty error is supplied
    if inc_status in ("staged", "loaded"):
        ex["error"] = str(inc.get("error", "") or "")
    elif inc.get("error"):
        ex["error"] = inc["error"]

    # Counts: take max to avoid losing progress on partial reruns.
    ex["chunk_count"] = max(int(ex.get("chunk_count") or 0), int(inc.get("chunk_count") or 0))
    ex["page_count_detected"] = max(
        int(ex.get("page_count_detected") or 0), int(inc.get("page_count_detected") or 0)
    )

    # Timestamps: only overwrite when incoming has a value.
    for k in ("started_at", "completed_at", "staged_at", "loaded_at"):
        if inc.get(k):
            ex[k] = inc[k]

    return ManifestDocument(**ex)


class LocalStagingStore:
    def __init__(self, staging_root: Path, project_uuid: str):
        self.staging_root = Path(staging_root)
        self.project_uuid = project_uuid
        self.project_dir = self.staging_root / self.project_uuid
        self.project_dir.mkdir(parents=True, exist_ok=True)

    def document_dir(self, document_uuid: str) -> Path:
        d = self.project_dir / document_uuid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def chunks_dir(self, document_uuid: str) -> Path:
        d = self.document_dir(document_uuid) / "chunks"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_document_metadata(self, document_uuid: str, metadata: Dict[str, Any]) -> Path:
        path = self.document_dir(document_uuid) / "document_metadata.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        return path

    def write_chunk(self, document_uuid: str, chunk_uuid: str, chunk_data: Dict[str, Any]) -> Path:
        path = self.chunks_dir(document_uuid) / f"{chunk_uuid}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(chunk_data, f, indent=2, ensure_ascii=False)
        return path

    def upsert_manifest(self, staged_docs: Iterable[StagedDocumentRef]) -> Path:
        """
        Backward compatible method used by Round 1 code.

        Converts refs to ManifestDocument(status='staged') and merges into existing manifest.
        """

        docs: List[ManifestDocument] = []
        for d in staged_docs:
            docs.append(
                ManifestDocument(
                    document_uuid=d.document_uuid,
                    title=d.title,
                    source_file=d.source_file,
                    ocr_markdown_path=d.ocr_markdown_path,
                    source_file_path=d.source_file_path,
                    status="staged",
                    chunk_count=int(d.chunk_count),
                    staged_at=d.staged_at,
                    completed_at=d.staged_at,
                )
            )

        return self.upsert_manifest_documents(docs)

    def upsert_manifest_documents(self, docs: Iterable[ManifestDocument]) -> Path:
        manifest_path = self.project_dir / "manifest.json"
        existing = self.read_manifest_documents_index()

        for d in docs:
            if not d.document_uuid:
                continue
            cur = existing.get(d.document_uuid)
            existing[d.document_uuid] = _merge_manifest_documents(cur, d) if cur else d

        docs_list = [asdict(d) for d in sorted(existing.values(), key=lambda x: (x.title or x.document_uuid))]
        payload = {"project_uuid": self.project_uuid, "generated_at": _now_iso(), "documents": docs_list}
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return manifest_path

    def read_manifest(self) -> Dict[str, Any]:
        manifest_path = self.project_dir / "manifest.json"
        if not manifest_path.exists():
            return {"project_uuid": self.project_uuid, "generated_at": None, "documents": []}
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def read_manifest_documents_index(self) -> Dict[str, ManifestDocument]:
        manifest = self.read_manifest()
        idx: Dict[str, ManifestDocument] = {}
        for raw in manifest.get("documents", []) or []:
            doc = _coerce_manifest_document(raw if isinstance(raw, dict) else {})
            if doc.document_uuid:
                idx[doc.document_uuid] = doc
        return idx

    def list_manifest_documents(self) -> List[ManifestDocument]:
        return list(self.read_manifest_documents_index().values())

    def update_manifest_document(self, document_uuid: str, **updates: Any) -> Path:
        """
        Atomic-ish update (read-modify-write). Safe for single-process concurrency when called
        from the main thread while workers do I/O.
        """

        document_uuid = str(document_uuid)
        if not document_uuid:
            raise ValueError("document_uuid is required")

        existing = self.read_manifest_documents_index()
        cur = existing.get(document_uuid) or ManifestDocument(document_uuid=document_uuid)
        merged = asdict(cur)
        for k, v in updates.items():
            if k not in merged:
                continue
            merged[k] = v

        existing[document_uuid] = ManifestDocument(**merged)
        return self.upsert_manifest_documents(existing.values())

    def list_staged_documents(self) -> List[StagedDocumentRef]:
        manifest = self.read_manifest()
        docs = []
        for d in manifest.get("documents", []) or []:
            if not isinstance(d, dict):
                continue
            docs.append(
                StagedDocumentRef(
                    document_uuid=str(d.get("document_uuid", "")),
                    title=str(d.get("title", "")),
                    source_file=str(d.get("source_file", "")),
                    ocr_markdown_path=str(d.get("ocr_markdown_path", "")),
                    source_file_path=str(d.get("source_file_path", "")),
                    chunk_count=int(d.get("chunk_count") or 0),
                    staged_at=str(d.get("staged_at", "")) or str(d.get("generated_at", "")) or "",
                )
            )
        return docs

