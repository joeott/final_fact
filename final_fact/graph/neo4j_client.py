"""
Neo4j client wrapper for the FACT graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from neo4j import Driver, GraphDatabase


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    username: str
    password: str
    database: str = "neo4j"


class Neo4jClient:
    def __init__(self, cfg: Neo4jConfig):
        self.cfg = cfg
        self.driver: Driver = GraphDatabase.driver(cfg.uri, auth=(cfg.username, cfg.password))

    def close(self) -> None:
        self.driver.close()

    def verify(self) -> None:
        self.driver.verify_connectivity()

    def write(self, cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        params = params or {}
        with self.driver.session(database=self.cfg.database) as session:
            result = session.run(cypher, **params)
            return [dict(r) for r in result]

    def write_many(self, cypher: str, rows: List[Dict[str, Any]]) -> None:
        with self.driver.session(database=self.cfg.database) as session:
            session.run(cypher, rows=rows)

