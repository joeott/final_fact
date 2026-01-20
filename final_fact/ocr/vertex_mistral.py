from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import google.auth
import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from pypdf import PdfReader, PdfWriter


@dataclass(frozen=True)
class VertexMistralOcrConfig:
    project_id: str = "document-processor-v3"
    location: str = "us-central1"
    model_id: str = "mistral-ocr-2505"

    # Mistral OCR via Vertex has practical request size limits; keep chunk pages bounded.
    max_pages_per_request: int = 25

    # Retry behavior (handles 429 + transient failures)
    # NOTE: Quota errors (429) can require waiting for a minute-scale refill window.
    max_retries: int = 10
    initial_backoff_seconds: float = 5.0


def _vertex_endpoint(cfg: VertexMistralOcrConfig) -> str:
    return (
        f"https://{cfg.location}-aiplatform.googleapis.com/v1beta1/"
        f"projects/{cfg.project_id}/locations/{cfg.location}/publishers/mistralai/models/{cfg.model_id}:rawPredict"
    )


def _get_token() -> str:
    # Vertex AI rawPredict requires a cloud-platform scoped access token.
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(GoogleAuthRequest())
    return str(creds.token)


def _post_rawpredict(*, cfg: VertexMistralOcrConfig, pdf_bytes: bytes, filename_hint: str) -> Dict[str, Any]:
    """
    Call Vertex rawPredict for Mistral OCR.
    Returns parsed JSON response.
    """
    encoded_content = base64.b64encode(pdf_bytes).decode("utf-8")

    payload = {
        "model": cfg.model_id,
        "document": {"type": "document_url", "document_url": f"data:application/pdf;base64,{encoded_content}"},
        "include_image_base64": False,
    }

    endpoint = _vertex_endpoint(cfg)
    headers = {"Authorization": f"Bearer {_get_token()}", "Content-Type": "application/json"}

    backoff = float(cfg.initial_backoff_seconds)
    last_err: Optional[str] = None
    for attempt in range(int(cfg.max_retries) + 1):
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=300)
        except Exception as e:
            last_err = f"request_error: {e}"
            if attempt >= int(cfg.max_retries):
                raise RuntimeError(f"OCR request failed ({filename_hint}): {last_err}")
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception as e:
                raise RuntimeError(f"OCR response JSON parse failed ({filename_hint}): {e}")

        # Retry quota and transient server issues
        if resp.status_code in (429, 500, 502, 503, 504):
            last_err = f"http_{resp.status_code}: {resp.text[:300]}"
            if attempt >= int(cfg.max_retries):
                raise RuntimeError(f"OCR request failed ({filename_hint}): {last_err}")
            time.sleep(backoff)
            backoff *= 2
            continue

        raise RuntimeError(f"OCR request failed ({filename_hint}): http_{resp.status_code}: {resp.text[:300]}")

    raise RuntimeError(f"OCR request failed ({filename_hint}): {last_err or 'unknown'}")


def _extract_pages_markdown(result_json: Dict[str, Any]) -> List[str]:
    """
    Return per-page markdown strings in order.
    """
    pages = result_json.get("pages")
    if not isinstance(pages, list):
        return []
    out: List[str] = []
    for p in pages:
        if isinstance(p, dict):
            out.append(str(p.get("markdown") or ""))
        else:
            out.append("")
    return out


def _chunk_page_ranges(total_pages: int, max_pages_per_request: int) -> List[Tuple[int, int]]:
    """
    Return 0-based (start, end_exclusive) ranges covering all pages.
    """
    if total_pages <= 0:
        return []
    step = max(1, int(max_pages_per_request))
    ranges: List[Tuple[int, int]] = []
    start = 0
    while start < total_pages:
        end = min(start + step, total_pages)
        ranges.append((start, end))
        start = end
    return ranges


def ocr_pdf_to_markdown(
    *,
    pdf_path: Path,
    out_md_path: Path,
    cfg: VertexMistralOcrConfig,
    force: bool = False,
    ocr_raw_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    OCR a single PDF into markdown with explicit page markers.

    Output format:
      Page 1 of N
      <page 1 markdown>

      Page 2 of N
      <page 2 markdown>
      ...
    """
    pdf_path = Path(pdf_path)
    out_md_path = Path(out_md_path)
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    if ocr_raw_dir is not None:
        ocr_raw_dir.mkdir(parents=True, exist_ok=True)

    if out_md_path.exists() and not force:
        return {"status": "cached", "pdf_path": str(pdf_path), "out_md_path": str(out_md_path)}

    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    if total_pages <= 0:
        raise RuntimeError(f"PDF has no pages: {pdf_path}")

    md_parts: List[str] = []
    md_parts.append(f"# OCR Output for {pdf_path.name}")
    md_parts.append("")

    ranges = _chunk_page_ranges(total_pages, cfg.max_pages_per_request)
    for idx, (start, end) in enumerate(ranges):
        writer = PdfWriter()
        for page_num in range(start, end):
            writer.add_page(reader.pages[page_num])

        # Serialize chunk PDF to bytes
        import io

        buf = io.BytesIO()
        writer.write(buf)
        chunk_bytes = buf.getvalue()

        hint = f"{pdf_path.name}::pages_{start+1}-{end}::chunk_{idx+1}_of_{len(ranges)}"
        result_json = _post_rawpredict(cfg=cfg, pdf_bytes=chunk_bytes, filename_hint=hint)

        if ocr_raw_dir is not None:
            raw_path = ocr_raw_dir / f"{out_md_path.stem}__pages_{start+1:04d}-{end:04d}.json"
            raw_path.write_text(json.dumps(result_json, indent=2, ensure_ascii=False), encoding="utf-8")

        page_markdowns = _extract_pages_markdown(result_json)
        # If API returns fewer pages than requested, we still label what we got.
        for rel_i, page_md in enumerate(page_markdowns):
            global_page = start + rel_i + 1
            md_parts.append(f"Page {global_page} of {total_pages}")
            md_parts.append("")
            md_parts.append(page_md.strip())
            md_parts.append("")

    out_md_path.write_text("\n".join(md_parts).strip() + "\n", encoding="utf-8")
    return {
        "status": "ok",
        "pdf_path": str(pdf_path),
        "out_md_path": str(out_md_path),
        "total_pages": total_pages,
    }

