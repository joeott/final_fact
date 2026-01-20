"""
Chunk a page of OCR markdown and extract entities via OpenAI.

Contract:
- input is a single page text (string)
- output is a list of chunks, each with:
  - text (verbatim excerpt from the page)
  - entities (typed)

We DO NOT trust the model to compute offsets. We locate each chunk’s text in the page text
in sequential order to compute deterministic (document-level) char offsets.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError

from ..llm.openai_client import OpenAIService


EntityType = Literal["PERSON", "ORGANIZATION", "PLACE", "DATE", "PHONE", "EMAIL", "ADDRESS", "OTHER"]


class EntityOut(BaseModel):
    entity_type: EntityType
    text: str = Field(min_length=1)


class ChunkOut(BaseModel):
    text: str = Field(min_length=1)
    entities: List[EntityOut] = Field(default_factory=list)


class PageChunkingResult(BaseModel):
    chunks: List[ChunkOut]


class EntitiesForChunkOut(BaseModel):
    text: str = Field(min_length=1)
    entities: List[EntityOut] = Field(default_factory=list)


class EntitiesOnlyResult(BaseModel):
    chunks: List[EntitiesForChunkOut]


SYSTEM_PROMPT = (
    "You are a legal document chunking and entity extraction service.\n"
    "Return ONLY valid JSON. No markdown. No commentary.\n"
    "You must preserve the input text exactly inside each chunk's `text` field (verbatim substrings).\n"
    "Do not merge content across pages (you are only given one page).\n"
)

SYSTEM_PROMPT_ENTITIES_ONLY = (
    "You are a legal document entity extraction service.\n"
    "Return ONLY valid JSON. No markdown. No commentary.\n"
    "You will be given an array of chunk texts. Extract entities from each chunk.\n"
    "Do not invent entities; entities must appear in the chunk text.\n"
)


def _make_user_prompt(page_number: int, page_text: str, target_chars: int) -> str:
    return (
        "Task: split the page into coherent chunks for legal retrieval and extract entities.\n\n"
        f"Constraints:\n"
        f"- page_number: {page_number}\n"
        f"- target chunk size: ~{target_chars} characters (soft target)\n"
        "- produce 1..N chunks\n"
        "- each chunk.text MUST be a verbatim substring of the page text\n"
        "- entity types allowed: PERSON, ORGANIZATION, PLACE, DATE, PHONE, EMAIL, ADDRESS, OTHER\n"
        "- entities must be extracted from chunk.text only\n\n"
        "Return JSON with shape:\n"
        '{ "chunks": [ { "text": "...", "entities": [ { "entity_type": "PERSON", "text": "..." } ] } ] }\n\n'
        "Page text:\n"
        "-----\n"
        f"{page_text}\n"
        "-----\n"
    )


def _make_user_prompt_entities_only(page_number: int, chunks: List[str]) -> str:
    # Keep it simple and deterministic: we provide the chunk texts and require entities only.
    joined = "\n\n".join([f"CHUNK {i}:\n-----\n{t}\n-----" for i, t in enumerate(chunks)])
    return (
        "Task: extract entities for each provided chunk.\n\n"
        f"Constraints:\n"
        f"- page_number: {page_number}\n"
        "- entity types allowed: PERSON, ORGANIZATION, PLACE, DATE, PHONE, EMAIL, ADDRESS, OTHER\n"
        "- return one output object per input chunk, in the same order\n"
        "- each output chunk.text MUST exactly equal the input chunk text\n\n"
        "Return JSON with shape:\n"
        '{ "chunks": [ { "text": "...", "entities": [ { "entity_type": "PERSON", "text": "..." } ] } ] }\n\n'
        "Chunks:\n"
        f"{joined}\n"
    )


def _deterministic_chunk_offsets(page_text: str, target_chars: int) -> List[Tuple[int, int]]:
    """
    Deterministic, substring-preserving chunking fallback.

    Heuristic:
    - chunk near target_chars
    - prefer breaking on paragraph/sentence/whitespace boundaries
    - trim leading/trailing whitespace for each chunk (still substring)
    """

    if target_chars <= 0:
        raise ValueError("target_chars must be > 0")

    n = len(page_text)
    out: List[Tuple[int, int]] = []
    start = 0
    while start < n:
        # skip leading whitespace
        while start < n and page_text[start].isspace():
            start += 1
        if start >= n:
            break

        end_guess = min(start + target_chars, n)
        if end_guess >= n:
            end = n
        else:
            window_start = max(start + 1, end_guess - 250)
            window = page_text[window_start:end_guess]

            # Prefer paragraph break, then newline, then sentence-ish, then last space.
            candidates: List[int] = []
            para = window.rfind("\n\n")
            if para != -1:
                candidates.append(window_start + para + 2)
            nl = window.rfind("\n")
            if nl != -1:
                candidates.append(window_start + nl + 1)
            sent = window.rfind(". ")
            if sent != -1:
                candidates.append(window_start + sent + 2)
            sp = window.rfind(" ")
            if sp != -1:
                candidates.append(window_start + sp + 1)

            end = max(candidates) if candidates else end_guess

        # trim trailing whitespace
        while end > start and page_text[end - 1].isspace():
            end -= 1

        if end <= start:
            # Fallback hard advance to prevent infinite loops
            end = min(start + target_chars, n)
            if end <= start:
                break

        out.append((start, end))
        start = end

    return out


def _find_chunk_offsets_sequential(page_text: str, chunks: List[str]) -> List[Tuple[int, int]]:
    """
    Find each chunk in the page text in sequential order.

    Strategy:
    - normalize line endings
    - search from last_end forward
    - if exact match fails, try a whitespace-normalized fallback that maps
      normalized offsets back onto original character offsets deterministically
    """
    text = page_text
    offsets: List[Tuple[int, int]] = []
    cursor = 0

    def _normalize_with_map(s: str) -> Tuple[str, List[int]]:
        """
        Collapse all whitespace runs to a single space and return:
        - normalized string
        - mapping list where map[i] is the original index for normalized[i]
        """

        norm_chars: List[str] = []
        mapping: List[int] = []
        in_ws = False
        for i, ch in enumerate(s):
            if ch.isspace():
                if not in_ws:
                    norm_chars.append(" ")
                    mapping.append(i)
                    in_ws = True
                continue
            norm_chars.append(ch)
            mapping.append(i)
            in_ws = False

        # Trim leading/trailing space (and keep mapping aligned).
        # Leading
        while norm_chars and norm_chars[0] == " ":
            norm_chars.pop(0)
            mapping.pop(0)
        # Trailing
        while norm_chars and norm_chars[-1] == " ":
            norm_chars.pop()
            mapping.pop()

        return "".join(norm_chars), mapping

    norm_text, norm_map = _normalize_with_map(text)

    for chunk_text in chunks:
        if not chunk_text:
            raise ValueError("Empty chunk_text not allowed")
        idx = text.find(chunk_text, cursor)
        if idx == -1:
            # Fallback: whitespace-normalized match with deterministic mapping back
            norm_chunk = re.sub(r"\s+", " ", chunk_text).strip()
            if not norm_chunk:
                raise ValueError("Chunk text normalized to empty; cannot locate")

            # Convert original cursor into normalized cursor using the mapping list.
            # norm_map is increasing (monotonic), so bisect gives first normalized index
            # that maps to an original index >= cursor.
            norm_cursor = bisect_left(norm_map, cursor)
            norm_start = norm_text.find(norm_chunk, max(0, norm_cursor - 50))
            if norm_start == -1:
                raise ValueError("Could not locate chunk text in page text (even after normalization)")

            # Map normalized indices back to original indices.
            start = norm_map[norm_start]
            end_norm_idx = norm_start + len(norm_chunk) - 1
            if end_norm_idx >= len(norm_map):
                raise ValueError("Normalized match exceeds mapping bounds")
            end = norm_map[end_norm_idx] + 1

            if start < cursor:
                raise ValueError("Chunks overlap or are out of order; cannot compute stable offsets")

            offsets.append((start, end))
            cursor = end
            continue
        start = idx
        end = idx + len(chunk_text)
        if start < cursor:
            raise ValueError("Chunks overlap or are out of order; cannot compute stable offsets")
        offsets.append((start, end))
        cursor = end
    return offsets


@dataclass(frozen=True)
class ChunkWithOffsets:
    text: str
    entities: List[Dict[str, str]]
    page_start: int
    page_end: int


class OpenAIPageChunker:
    def __init__(self, service: OpenAIService, target_chars: int = 1200):
        self.service = service
        self.target_chars = target_chars

    def chunk_page(self, *, page_number: int, page_text: str) -> List[ChunkWithOffsets]:
        # Primary path: ask model to chunk + entities, then locate offsets deterministically.
        try:
            raw = self.service.chat_json(
                system=SYSTEM_PROMPT,
                user=_make_user_prompt(page_number, page_text, self.target_chars),
                max_output_tokens=2500,
                temperature=0.1,
                retries=2,
            )

            parsed = PageChunkingResult.model_validate(raw)
            chunk_texts = [c.text for c in parsed.chunks]
            offsets = _find_chunk_offsets_sequential(page_text, chunk_texts)

            out: List[ChunkWithOffsets] = []
            for c, (start, end) in zip(parsed.chunks, offsets):
                out.append(
                    ChunkWithOffsets(
                        text=c.text,
                        entities=[{"entity_type": e.entity_type, "text": e.text} for e in c.entities],
                        page_start=start,
                        page_end=end,
                    )
                )
            return out
        except Exception:
            # Fallback: deterministic local chunking + model entities only.
            spans = _deterministic_chunk_offsets(page_text, self.target_chars)
            chunk_texts = [page_text[s:e] for (s, e) in spans]

            raw2 = self.service.chat_json(
                system=SYSTEM_PROMPT_ENTITIES_ONLY,
                user=_make_user_prompt_entities_only(page_number, chunk_texts),
                max_output_tokens=2000,
                temperature=0.1,
                retries=2,
            )

            try:
                parsed2 = EntitiesOnlyResult.model_validate(raw2)
            except ValidationError as e:
                raise ValueError(f"Invalid entities-only response schema: {e}") from e

            if len(parsed2.chunks) != len(chunk_texts):
                raise ValueError("entities-only response length mismatch")

            out2: List[ChunkWithOffsets] = []
            for (start, end), c in zip(spans, parsed2.chunks):
                # Ensure identity: if model returns different text, force the input text.
                text_exact = page_text[start:end]
                out2.append(
                    ChunkWithOffsets(
                        text=text_exact,
                        entities=[{"entity_type": e.entity_type, "text": e.text} for e in c.entities],
                        page_start=start,
                        page_end=end,
                    )
                )
            return out2

