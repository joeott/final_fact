"""
OCR utilities for final_fact.

Contract:
- Mistral-only OCR via Vertex rawPredict (mistral-ocr-2505).
- Emit markdown with explicit page marker lines:
    Page X of Y
  so downstream chunking can remain page-isolated.
"""

