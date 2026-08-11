from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from agronomy_agent.agno_runtime.local_index import infer_namespaces, tokenize

GRAPH_QUERY_STOPWORDS = {
    "after",
    "before",
    "check",
    "checked",
    "crop",
    "grower",
    "goal",
    "method",
    "recommend",
    "recommending",
    "soil",
    "suspects",
    "yield",
}
NUTRIENT_TOKENS = {
    "boron",
    "calcium",
    "copper",
    "iron",
    "magnesium",
    "manganese",
    "molybdenum",
    "nitrogen",
    "phosphorus",
    "potassium",
    "sulfate",
    "sulfur",
    "zinc",
}
CROP_TOKENS = {"corn", "maize", "soybean", "wheat", "canola", "barley", "rice"}


@dataclass(frozen=True)
class GraphHit:
    node_id: str
    name: str
    kind: str
    evidence: str
    neighbors: tuple[str, ...]
    namespaces: tuple[str, ...]


class KnowledgeGraph:
    def __init__(self, path: Path) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.nodes = {row["id"]: row for row in payload.get("nodes", [])}
        self.edges = payload.get("edges", [])
        self._build_neighbors()

    @classmethod
    def from_paths(cls, paths: list[Path]) -> "KnowledgeGraph":
        obj = cls.__new__(cls)
        obj.nodes = {}
        obj.edges = []
        for path in paths:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            for row in payload.get("nodes", []):
                obj.nodes[row["id"]] = row
            obj.edges.extend(payload.get("edges", []))
        obj._build_neighbors()
        return obj

    def _build_neighbors(self) -> None:
        self.neighbor_names: dict[str, list[str]] = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            src = edge.get("source")
            dst = edge.get("target")
            if src in self.nodes and dst in self.nodes:
                label = edge.get("relation", "related_to")
                self.neighbor_names[src].append(f"{label}: {self.nodes[dst]['name']}")
        self.node_tokens: dict[str, set[str]] = {}
        self.node_namespaces: dict[str, set[str]] = {}
        for node_id, node in self.nodes.items():
            haystack = " ".join([node.get("name", ""), node.get("kind", ""), node.get("description", ""), " ".join(node.get("aliases", []))])
            self.node_tokens[node_id] = set(tokenize(haystack))
            self.node_namespaces[node_id] = set(infer_namespaces(_node_as_doc(node_id, node)))

    def lookup_names(self, names: Iterable[str]) -> list[GraphHit]:
        """Resolve exact concept names or aliases without semantic overreach.

        This is used for governed cross-store joins where a broad token search
        could silently replace a mapped attribute with a related but materially
        different laboratory measurement.
        """

        requested = {
            str(name).strip().casefold()
            for name in names
            if str(name).strip()
        }
        if not requested:
            return []
        hits: list[GraphHit] = []
        for node_id, node in self.nodes.items():
            labels = {
                str(node.get("name") or "").strip().casefold(),
                *{
                    str(alias).strip().casefold()
                    for alias in node.get("aliases", [])
                    if str(alias).strip()
                },
            }
            if not requested.intersection(labels):
                continue
            hits.append(
                GraphHit(
                    node_id=node_id,
                    name=node.get("name", ""),
                    kind=node.get("kind", ""),
                    evidence=node.get("description", ""),
                    neighbors=tuple(self.neighbor_names.get(node_id, [])[:4]),
                    namespaces=tuple(sorted(self.node_namespaces.get(node_id, set()))),
                )
            )
        return hits

    def search(
        self,
        query: str,
        limit: int = 5,
        namespaces: Iterable[str] | None = None,
        query_expansion: Iterable[str] | None = None,
    ) -> list[GraphHit]:
        q_tokens = set(tokenize(query)) - GRAPH_QUERY_STOPWORDS
        expansion_tokens = set(tokenize(" ".join(query_expansion or []))) - GRAPH_QUERY_STOPWORDS
        query_nutrients = q_tokens & NUTRIENT_TOKENS
        query_crops = q_tokens & CROP_TOKENS
        route_namespaces = set(namespaces or [])
        hits: list[tuple[float, str]] = []
        for node_id, node in self.nodes.items():
            hay_tokens = self.node_tokens.get(node_id, set())
            overlap = q_tokens & hay_tokens
            expansion_overlap = expansion_tokens & hay_tokens
            if overlap or expansion_overlap:
                score = float(len(overlap)) + (0.35 * len(expansion_overlap))
                if query_nutrients and not query_nutrients & hay_tokens:
                    score *= 0.45
                if "sulfur" in query_nutrients and {"dioxide", "acid"} & hay_tokens and not ({"dioxide", "acid"} & q_tokens):
                    score *= 0.3
                node_crops = hay_tokens & CROP_TOKENS
                if query_crops and node_crops and query_crops.isdisjoint(node_crops):
                    score *= 0.35
                node_namespaces = self.node_namespaces.get(node_id, set())
                if route_namespaces:
                    namespace_overlap = len(route_namespaces & node_namespaces)
                    if namespace_overlap:
                        score *= 1.0 + min(0.5, 0.2 * namespace_overlap)
                    else:
                        score *= 0.72
                hits.append((score, node_id))
        hits.sort(reverse=True)
        return [
            GraphHit(
                node_id=node_id,
                name=self.nodes[node_id]["name"],
                kind=self.nodes[node_id].get("kind", ""),
                evidence=self.nodes[node_id].get("description", ""),
                neighbors=tuple(self.neighbor_names.get(node_id, [])[:4]),
                namespaces=tuple(sorted(self.node_namespaces.get(node_id, set()))),
            )
            for _, node_id in hits[:limit]
        ]


def _node_as_doc(node_id: str, node: dict) -> dict:
    return {
        "doc_id": node_id,
        "title": node.get("name", ""),
        "text": node.get("description", ""),
        "tags": [node.get("kind", ""), *node.get("aliases", [])],
    }
