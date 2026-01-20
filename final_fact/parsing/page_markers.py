"""
OCR markdown page marker parsing.

We rely on explicit page marker lines emitted by OCR markdown, e.g.:
  "Page 1 of 6"

We must preserve page numbers and never mix text across pages during chunking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


PAGE_MARKER_RE = re.compile(r"^\s*Page\s+(?P<page>\d+)\s+of\s+(?P<total>\d+)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class PageBlock:
    page_number: int
    total_pages: Optional[int]
    text: str  # text content for this page (excluding the marker line)


def detect_page_marker(line: str) -> Optional[Tuple[int, int]]:
    """
    Returns (page_number, total_pages) if line is a page marker, else None.
    """
    m = PAGE_MARKER_RE.match(line or "")
    if not m:
        return None
    return (int(m.group("page")), int(m.group("total")))


def split_markdown_into_pages(markdown_text: str) -> List[PageBlock]:
    """
    Split an OCR markdown file into page blocks.

    Behavior:
    - If page markers exist, split by them. Each marker starts a new page.
    - Content before the first marker is treated as page_number=0 (front-matter).
      This is kept so no text is dropped; downstream may choose to skip page 0.
    - If no markers exist, return a single page block page_number=0.
    """
    lines = (markdown_text or "").splitlines()

    page_blocks: List[PageBlock] = []
    current_page: int = 0
    current_total: Optional[int] = None
    buf: List[str] = []

    saw_any_marker = False

    for line in lines:
        marker = detect_page_marker(line)
        if marker:
            saw_any_marker = True
            # flush existing buffer as previous page
            page_blocks.append(
                PageBlock(
                    page_number=current_page,
                    total_pages=current_total,
                    text="\n".join(buf).strip(),
                )
            )
            buf = []
            current_page, current_total = marker
            continue

        buf.append(line)

    # final buffer
    page_blocks.append(
        PageBlock(
            page_number=current_page,
            total_pages=current_total,
            text="\n".join(buf).strip(),
        )
    )

    # If there were no markers, treat entire document as a single page 1.
    # This ensures we still produce chunks for documents lacking explicit page markers.
    if not saw_any_marker:
        return [PageBlock(page_number=1, total_pages=1, text=(markdown_text or "").strip())]

    # Drop empty leading page 0 if it’s pure front-matter whitespace
    if page_blocks and page_blocks[0].page_number == 0 and not page_blocks[0].text.strip():
        page_blocks = page_blocks[1:]

    return page_blocks


def iter_pages_with_offsets(pages: Iterable[PageBlock]) -> List[Tuple[PageBlock, int]]:
    """
    Compute stable offsets for pages in a reconstructed full_text.

    We define full_text = page1.text + "\\n\\n" + page2.text + "\\n\\n" + ...
    and return each page with its starting char offset into that full_text.
    """
    pages_list = list(pages)
    offsets: List[Tuple[PageBlock, int]] = []
    cursor = 0
    for i, p in enumerate(pages_list):
        offsets.append((p, cursor))
        # advance cursor
        cursor += len(p.text)
        if i < len(pages_list) - 1:
            cursor += 2
    return offsets

