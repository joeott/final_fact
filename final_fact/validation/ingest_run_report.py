from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_truncate(s: str, n: int = 500) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."


def write_ingest_run_report(
    *,
    project_root: Path,
    case_name: str,
    project_uuid: str,
    scanned_files: int,
    selected_files: int,
    skipped: int,
    staged_docs: int,
    staged_chunks: int,
    failed_docs: int,
    failures: List[Dict[str, str]],
    duration_seconds: float,
    args_summary: Dict[str, Any],
    stamp: Optional[str] = None,
) -> Path:
    stamp = stamp or _now_stamp()
    out_dir = Path(project_root) / "ai_docs" / "validation" / "ingest_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ingest_run_{stamp}.md"

    rate_docs = (staged_docs / duration_seconds) if duration_seconds > 0 else 0.0
    rate_chunks = (staged_chunks / duration_seconds) if duration_seconds > 0 else 0.0

    lines: List[str] = []
    lines.append(f"# Ingest run report ({stamp})")
    lines.append("")
    lines.append(f"- generated_at: `{_now_iso()}`")
    lines.append(f"- case_name: `{case_name}`")
    lines.append(f"- project_uuid: `{project_uuid}`")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- markdown_files_scanned: **{scanned_files}**")
    lines.append(f"- markdown_files_selected: **{selected_files}**")
    lines.append(f"- skipped_already_staged_or_loaded: **{skipped}**")
    lines.append(f"- documents_staged: **{staged_docs}**")
    lines.append(f"- chunks_staged: **{staged_chunks}**")
    lines.append(f"- documents_failed: **{failed_docs}**")
    lines.append("")
    lines.append("## Timing")
    lines.append(f"- duration_seconds: **{duration_seconds:.2f}**")
    lines.append(f"- rate_docs_per_sec: **{rate_docs:.3f}**")
    lines.append(f"- rate_chunks_per_sec: **{rate_chunks:.3f}**")
    lines.append("")
    lines.append("## Args")
    for k in sorted(args_summary.keys()):
        lines.append(f"- {k}: `{args_summary[k]}`")
    lines.append("")

    lines.append("## Failures (top)")
    if not failures:
        lines.append("- (none)")
    else:
        for f in failures[:50]:
            title = f.get("title") or f.get("path") or f.get("document_uuid") or "unknown"
            err = _safe_truncate(f.get("error", ""))
            lines.append(f"- **{title}**: `{err}`")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_load_run_report(
    *,
    project_root: Path,
    case_name: str,
    project_uuid: str,
    selected_docs: int,
    skipped_loaded: int,
    loaded_docs: int,
    loaded_chunks: int,
    failed_docs: int,
    failures: List[Dict[str, str]],
    duration_seconds: float,
    args_summary: Dict[str, Any],
    stamp: Optional[str] = None,
) -> Path:
    stamp = stamp or _now_stamp()
    out_dir = Path(project_root) / "ai_docs" / "validation" / "ingest_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"load_neo4j_run_{stamp}.md"

    rate_docs = (loaded_docs / duration_seconds) if duration_seconds > 0 else 0.0
    rate_chunks = (loaded_chunks / duration_seconds) if duration_seconds > 0 else 0.0

    lines: List[str] = []
    lines.append(f"# Neo4j load run report ({stamp})")
    lines.append("")
    lines.append(f"- generated_at: `{_now_iso()}`")
    lines.append(f"- case_name: `{case_name}`")
    lines.append(f"- project_uuid: `{project_uuid}`")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- documents_selected: **{selected_docs}**")
    lines.append(f"- skipped_already_loaded: **{skipped_loaded}**")
    lines.append(f"- documents_loaded: **{loaded_docs}**")
    lines.append(f"- chunks_loaded: **{loaded_chunks}**")
    lines.append(f"- documents_failed: **{failed_docs}**")
    lines.append("")
    lines.append("## Timing")
    lines.append(f"- duration_seconds: **{duration_seconds:.2f}**")
    lines.append(f"- rate_docs_per_sec: **{rate_docs:.3f}**")
    lines.append(f"- rate_chunks_per_sec: **{rate_chunks:.3f}**")
    lines.append("")
    lines.append("## Args")
    for k in sorted(args_summary.keys()):
        lines.append(f"- {k}: `{args_summary[k]}`")
    lines.append("")

    lines.append("## Failures (top)")
    if not failures:
        lines.append("- (none)")
    else:
        for f in failures[:50]:
            du = f.get("document_uuid") or "unknown"
            err = _safe_truncate(f.get("error", ""))
            lines.append(f"- **{du}**: `{err}`")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path

