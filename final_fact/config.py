"""
final_fact configuration.

Defaults are chosen to match the working patterns in fact_improve:
- centralized env at /Users/joe/Projects/.env
- Neo4j FACT graph credentials: NEO4J_FACT_*
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv


DEFAULT_ENV_PATH = Path("/Users/joe/Projects/.env")


def _load_env() -> None:
    # Centralized env is canonical in this environment.
    if DEFAULT_ENV_PATH.exists():
        load_dotenv(DEFAULT_ENV_PATH)


def _deterministic_uuid5(namespace: str, name: str) -> str:
    """
    Deterministic UUIDv5 helper.

    namespace:
      - if UUID string: used as namespace UUID
      - else: treated as DNS namespace seed
    """
    try:
        ns_uuid = uuid.UUID(namespace)
    except Exception:
        ns_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, namespace)
    return str(uuid.uuid5(ns_uuid, name))


@dataclass(frozen=True)
class Settings:
    # --- Case identity ---
    tenant_uuid: str
    case_name: str
    project_uuid: str

    # --- Paths ---
    project_root: Path
    input_base_dir: Path
    input_ocr_dir: Path
    input_analysis_csv: Path
    output_staging_dir: Path

    # --- OpenAI (chunking + embeddings) ---
    openai_api_key: str
    openai_chunk_model: str
    openai_embedding_model: str

    # --- Neo4j FACT graph ---
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str

    # --- Runtime knobs ---
    default_max_workers: int = 6

    @property
    def neo4j_auth(self) -> Tuple[str, str]:
        return (self.neo4j_username, self.neo4j_password)


def load_settings(
    *,
    project_root: Path | str = "/Users/joe/Projects/final_fact",
    case_name: str = "Kunda v. Smith (final_fact)",
    tenant_uuid: str = "ott-law-firm",
    project_uuid: Optional[str] = None,
    input_base_dir: Optional[Path | str] = None,
) -> Settings:
    """
    Load settings from env + defaults.

    project_uuid:
      - if provided, used verbatim
      - else deterministic UUIDv5(case_name) so reruns are idempotent
    """
    _load_env()

    project_root = Path(project_root)
    # Input directory root:
    # - default: {project_root}/input (backward compatible)
    # - case-scoped: {project_root}/input/<case_dir> (e.g. input/Jostes_depo)
    resolved_input_base_dir = Path(input_base_dir) if input_base_dir is not None else (project_root / "input")
    input_ocr_dir = resolved_input_base_dir / "organized" / "ocr"
    input_analysis_csv = resolved_input_base_dir / "organized" / "analysis" / "analysis.csv"
    output_staging_dir = project_root / "output" / "staging"

    resolved_project_uuid = project_uuid or os.getenv("FINAL_FACT_PROJECT_UUID")
    if not resolved_project_uuid:
        resolved_project_uuid = _deterministic_uuid5("final_fact_project", case_name)

    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_api_key:
        raise ValueError("Missing OPENAI_API_KEY in /Users/joe/Projects/.env")

    neo4j_uri = os.getenv("NEO4J_FACT_URI", "")
    neo4j_username = os.getenv("NEO4J_FACT_USERNAME", "")
    neo4j_password = os.getenv("NEO4J_FACT_PASSWORD", "")
    neo4j_database = os.getenv("NEO4J_FACT_DATABASE", "neo4j")
    if not (neo4j_uri and neo4j_username and neo4j_password):
        raise ValueError("Missing NEO4J_FACT_* credentials in /Users/joe/Projects/.env")

    openai_chunk_model = os.getenv("OPENAI_CHUNK_MODEL", "gpt-4o-mini")
    openai_embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    output_staging_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        tenant_uuid=tenant_uuid,
        case_name=case_name,
        project_uuid=resolved_project_uuid,
        project_root=project_root,
        input_base_dir=resolved_input_base_dir,
        input_ocr_dir=input_ocr_dir,
        input_analysis_csv=input_analysis_csv,
        output_staging_dir=output_staging_dir,
        openai_api_key=openai_api_key,
        openai_chunk_model=openai_chunk_model,
        openai_embedding_model=openai_embedding_model,
        neo4j_uri=neo4j_uri,
        neo4j_username=neo4j_username,
        neo4j_password=neo4j_password,
        neo4j_database=neo4j_database,
    )


def deterministic_document_uuid(project_uuid: str, doc_key: str) -> str:
    """Deterministic document UUID (idempotent reruns)."""
    return _deterministic_uuid5(project_uuid, f"document::{doc_key}")


def deterministic_chunk_uuid(document_uuid: str, start: int, end: int) -> str:
    """Deterministic chunk UUID matching AWS-CDK style: uuid5(document_uuid, 'start:end')."""
    if start < 0:
        raise ValueError("start must be >= 0")
    if end <= start:
        raise ValueError("end must be > start")
    return _deterministic_uuid5(document_uuid, f"{int(start)}:{int(end)}")

