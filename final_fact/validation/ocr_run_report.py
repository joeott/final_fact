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


def write_ocr_run_report(
    *,
    project_root: Path,
    case_name: str,
    project_uuid: str,
    input_base_dir: str,
    scanned_files: int,
    selected_files: int,
    skipped_cached: int,
    ocr_ok: int,
    ocr_failed: int,
    failures: List[Dict[str, str]],
    duration_seconds: float,
    args_summary: Dict[str, Any],
    stamp: Optional[str] = None,
) -> Path:
    stamp = stamp or _now_stamp()
    out_dir = Path(project_root) / "ai_docs" / "validation" / "ocr_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ocr_run_{stamp}.md"

    rate_docs = (ocr_ok / duration_seconds) if duration_seconds > 0 else 0.0

    lines: List[str] = []
    lines.append(f"# OCR run report ({stamp})")
    lines.append("")
    lines.append(f"- generated_at: `{_now_iso()}`")
    lines.append(f"- case_name: `{case_name}`")
    lines.append(f"- project_uuid: `{project_uuid}`")
    lines.append(f"- input_base_dir: `{input_base_dir}`")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- source_files_scanned: **{scanned_files}**")
    lines.append(f"- source_files_selected: **{selected_files}**")
    lines.append(f"- skipped_cached_markdown: **{skipped_cached}**")
    lines.append(f"- ocr_ok: **{ocr_ok}**")
    lines.append(f"- ocr_failed: **{ocr_failed}**")
    lines.append("")
    lines.append("## Timing")
    lines.append(f"- duration_seconds: **{duration_seconds:.2f}**")
    lines.append(f"- rate_docs_per_sec: **{rate_docs:.3f}**")
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
            title = f.get("title") or f.get("path") or "unknown"
            err = _safe_truncate(f.get("error", ""))
            lines.append(f"- **{title}**: `{err}`")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path

