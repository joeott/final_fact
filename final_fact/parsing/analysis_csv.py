"""
Parse input/organized/analysis/analysis.csv.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .normalize_keys import extract_doc_prefix, normalized_title_key, organized_basename


@dataclass(frozen=True)
class AnalysisRow:
    original_file_path: str
    organized_doc_number: str
    file_type: str
    file_description: str
    relevance_analysis: str

    @property
    def organized_stem(self) -> str:
        return Path(self.organized_doc_number).stem

    @property
    def doc_prefix(self) -> str:
        return extract_doc_prefix(self.organized_doc_number)

    @property
    def organized_basename(self) -> str:
        return organized_basename(self.organized_doc_number)

    @property
    def normalized_title_key(self) -> str:
        return normalized_title_key(self.organized_doc_number)


def read_analysis_csv(path: Path) -> List[AnalysisRow]:
    path = Path(path)
    rows: List[AnalysisRow] = []
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if not r:
                continue
            rows.append(
                AnalysisRow(
                    original_file_path=(r.get("Original File Path") or "").strip(),
                    organized_doc_number=(r.get("Organized Doc Number") or "").strip(),
                    file_type=(r.get("File Type") or "").strip(),
                    file_description=(r.get("File Description") or "").strip(),
                    relevance_analysis=(r.get("Relevance Analysis") or "").strip(),
                )
            )
    return rows

