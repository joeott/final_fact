"""
Normalization helpers for joining analysis.csv rows to CaseDocument nodes.
"""

from __future__ import annotations

import re
from pathlib import Path


DOC_PREFIX_RE = re.compile(r"(DOC_\d{4})", re.IGNORECASE)


def extract_doc_prefix(text: str) -> str:
    m = DOC_PREFIX_RE.search(text or "")
    return (m.group(1).upper() if m else "")


def organized_basename(name: str) -> str:
    """
    Basename without extension, trimmed.
    """
    base = Path(name or "").name
    stem = Path(base).stem
    return stem.strip()


def normalized_title_key(name: str) -> str:
    """
    Lowercased, punctuation-stripped key for fuzzy joining.

    Heuristics:
    - drop file extension
    - drop leading DOC_#### prefix
    - collapse whitespace
    - keep only a-z0-9 and spaces
    """
    stem = organized_basename(name)
    stem = DOC_PREFIX_RE.sub("", stem)
    stem = stem.lower()
    stem = re.sub(r"[^a-z0-9\\s]+", " ", stem)
    stem = re.sub(r"\\s+", " ", stem).strip()
    return stem

