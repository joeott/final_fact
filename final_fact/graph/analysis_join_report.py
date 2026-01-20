"""
Generate an auditable analysis.csv join coverage report in ai_docs/.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..parsing.analysis_csv import AnalysisRow
from ..parsing.normalize_keys import extract_doc_prefix, normalized_title_key, organized_basename
from .neo4j_client import Neo4jClient


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


@dataclass(frozen=True)
class DocKey:
    document_uuid: str
    title: str
    source_file: str
    doc_prefix: str
    normalized_key: str


def _fetch_doc_keys(client: Neo4jClient, project_uuid: str) -> List[DocKey]:
    rows = client.write(
        """
        MATCH (d:CaseDocument)
        WHERE d.project_uuid = $project_uuid
        RETURN d.document_uuid as document_uuid,
               coalesce(d.title,'') as title,
               coalesce(d.source_file,'') as source_file,
               coalesce(d.doc_prefix,'') as doc_prefix,
               coalesce(d.normalized_title_key,'') as normalized_title_key
        """,
        {"project_uuid": project_uuid},
    )
    out: List[DocKey] = []
    for r in rows:
        title = r["title"]
        source_file = r["source_file"]
        dp = (r.get("doc_prefix") or "").strip() or extract_doc_prefix(title) or extract_doc_prefix(source_file)
        nk = (r.get("normalized_title_key") or "").strip() or normalized_title_key(title) or normalized_title_key(source_file)
        out.append(DocKey(r["document_uuid"], title, source_file, dp, nk))
    return out


def _preview_join(rows: List[AnalysisRow], docs: List[DocKey]) -> Tuple[List[str], List[str]]:
    """
    Return (unmatched_rows, ambiguous_rows) as organized_doc_number strings.
    """
    prefix_map: Dict[str, List[str]] = {}
    key_map: Dict[str, List[str]] = {}
    for d in docs:
        if d.doc_prefix:
            prefix_map.setdefault(d.doc_prefix, []).append(d.document_uuid)
        if d.normalized_key:
            key_map.setdefault(d.normalized_key, []).append(d.document_uuid)

    unmatched: List[str] = []
    ambiguous: List[str] = []
    for r in rows:
        dp = r.doc_prefix
        nk = r.normalized_title_key
        chosen = None

        if dp and dp in prefix_map:
            cands = prefix_map[dp]
            if len(cands) == 1:
                chosen = cands[0]
            else:
                ambiguous.append(r.organized_doc_number)
                continue

        if not chosen and nk and nk in key_map:
            cands = key_map[nk]
            if len(cands) == 1:
                chosen = cands[0]
            else:
                ambiguous.append(r.organized_doc_number)
                continue

        if not chosen:
            unmatched.append(r.organized_doc_number)

    return unmatched, ambiguous


def write_analysis_join_report(
    *,
    client: Neo4jClient,
    project_uuid: str,
    analysis_rows: List[AnalysisRow],
    output_dir: Path,
    top_n: int = 50,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    docs = _fetch_doc_keys(client, project_uuid)

    # Neo4j ground truth status (post-join)
    counts = client.write(
        """
        MATCH (d:CaseDocument)
        WHERE d.project_uuid = $project_uuid
        WITH count(d) as total,
             count(CASE WHEN d.analysis_ingested = true THEN 1 END) as with_analysis,
             count(CASE WHEN d.analysis_join_strategy = 'ambiguous' THEN 1 END) as ambiguous
        RETURN total, with_analysis, ambiguous
        """,
        {"project_uuid": project_uuid},
    )[0]

    unmatched_docs = client.write(
        """
        MATCH (d:CaseDocument)
        WHERE d.project_uuid = $project_uuid
          AND (d.analysis_ingested IS NULL OR d.analysis_ingested = false)
        RETURN d.document_uuid as document_uuid, d.title as title, d.doc_prefix as doc_prefix
        ORDER BY coalesce(d.doc_prefix,''), d.title
        LIMIT $limit
        """,
        {"project_uuid": project_uuid, "limit": int(top_n)},
    )

    # Preview join gaps from CSV (independent of whether join already run)
    unmatched_rows, ambiguous_rows = _preview_join(analysis_rows, docs)

    stamp = _now_stamp()
    report_path = output_dir / f"report_{stamp}.md"

    lines: List[str] = []
    lines.append(f"# analysis.csv join report ({stamp} UTC)")
    lines.append("")
    lines.append(f"**project_uuid**: `{project_uuid}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total CaseDocuments**: {counts.get('total', 0)}")
    lines.append(f"- **Documents with analysis_ingested=true**: {counts.get('with_analysis', 0)}")
    lines.append(f"- **Documents marked ambiguous**: {counts.get('ambiguous', 0)}")
    lines.append(f"- **analysis.csv rows**: {len(analysis_rows)}")
    lines.append(f"- **analysis.csv unmatched rows (preview)**: {len(unmatched_rows)}")
    lines.append(f"- **analysis.csv ambiguous rows (preview)**: {len(ambiguous_rows)}")
    lines.append("")

    lines.append("## Unmatched documents (top sample)")
    lines.append("")
    for d in unmatched_docs:
        lines.append(f"- `{d.get('doc_prefix') or ''}` `{d.get('document_uuid')}` — {d.get('title')}")
    if not unmatched_docs:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Unmatched analysis rows (preview, top sample)")
    lines.append("")
    for s in unmatched_rows[:top_n]:
        lines.append(f"- {s}")
    if not unmatched_rows:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Ambiguous analysis rows (preview, top sample)")
    lines.append("")
    for s in ambiguous_rows[:top_n]:
        lines.append(f"- {s}")
    if not ambiguous_rows:
        lines.append("- (none)")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path

