"""
OpenAI client wrapper.

We keep this thin so it’s easy to swap models and control retries centrally.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str
    chunk_model: str
    embedding_model: str


class OpenAIService:
    def __init__(self, cfg: OpenAIConfig):
        self.cfg = cfg
        self.client = OpenAI(api_key=cfg.api_key)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        resp = self.client.embeddings.create(model=self.cfg.embedding_model, input=texts)
        # preserve order
        return [d.embedding for d in resp.data]

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 2000,
        temperature: float = 0.2,
        retries: int = 2,
    ) -> Any:
        """
        Call chat model and parse JSON response.

        Uses strict JSON-only instruction and retries once with a repair prompt if needed.
        """
        last_err: Optional[Exception] = None
        prompt_user = user
        for attempt in range(retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.cfg.chunk_model,
                    temperature=temperature,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt_user},
                    ],
                    max_tokens=max_output_tokens,
                )
                text = (resp.choices[0].message.content or "").strip()
                # Strip markdown fences if present
                if text.startswith("```"):
                    text = text.split("```", 2)[1] if "```" in text else text
                    text = text.replace("json", "", 1).strip()
                return json.loads(text)
            except Exception as e:
                last_err = e
                if attempt >= retries:
                    break
                # Repair prompt: provide the raw output and require valid JSON
                prompt_user = (
                    "You returned invalid JSON. Return ONLY valid JSON for the same task.\n\n"
                    f"Previous output:\n{text if 'text' in locals() else ''}"
                )
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"OpenAI JSON call failed after retries: {last_err}")

