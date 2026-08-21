from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from agronomy_agent.agno_runtime.local_index import infer_namespaces, tokenize
from agronomy_agent.capability_registry import GraphRegistry, GraphSpec

GRAPH_MANIFEST_SCHEMA_VERSION = "open_agronomy_agent.knowledge_graph_manifest.v1"
GRAPH_AUTHORITY_ROLES = frozenset({"vocabulary_hint", "regional_context", "decision_evidence"})
GRAPH_COLLISION_POLICIES = frozenset({"error", "prefer_higher_priority"})

_GRAPH_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_:-]*$")
_RELATION_RE = re.compile(r"^[a-z][a-z0-9_:-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GRAPH_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "graph_id",
        "version",
        "data_path",
        "namespaces",
        "source",
        "license",
        "sha256",
        "authority_role",
        "priority",
        "collision_policy",
        "relation_vocabulary",
    }
)

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


class GraphValidationError(ValueError):
    """Raised when graph composition cannot preserve its declared contract."""


@dataclass(frozen=True)
class GraphManifest:
    """Validated runtime manifest and resolved paths for one graph artifact.

    This loader-owned type contains filesystem state. ``GraphSpec`` remains
    the canonical catalog contract and is produced by ``as_graph_spec`` after
    manifest validation succeeds.
    """

    graph_id: str
    version: str
    data_path: Path
    namespaces: tuple[str, ...]
    source: str
    license: str
    sha256: str
    authority_role: str
    priority: int
    collision_policy: str | None
    relation_vocabulary: tuple[str, ...]
    manifest_path: Path | None = None
    manifest_declared: bool = False

    @classmethod
    def from_manifest(
        cls,
        manifest_path: Path,
        *,
        expected_data_path: Path | None = None,
    ) -> "GraphManifest":
        manifest_path = manifest_path.resolve()
        payload = _read_json_object(manifest_path, kind="graph manifest")
        unknown_fields = sorted(set(payload) - _GRAPH_MANIFEST_FIELDS)
        if unknown_fields:
            raise GraphValidationError(f"unknown fields in graph manifest {manifest_path}: {unknown_fields}")
        schema_version = _required_string(payload, "schema_version", manifest_path)
        if schema_version != GRAPH_MANIFEST_SCHEMA_VERSION:
            raise GraphValidationError(
                f"unsupported graph manifest schema {schema_version!r} in {manifest_path}; "
                f"expected {GRAPH_MANIFEST_SCHEMA_VERSION!r}"
            )

        graph_id = _required_string(payload, "graph_id", manifest_path)
        if not _GRAPH_ID_RE.fullmatch(graph_id):
            raise GraphValidationError(f"invalid graph_id {graph_id!r} in {manifest_path}")
        version = _required_string(payload, "version", manifest_path)

        data_value = _required_string(payload, "data_path", manifest_path)
        declared_data_path = Path(data_value)
        if declared_data_path.is_absolute() or ".." in declared_data_path.parts:
            raise GraphValidationError(f"graph manifest data_path must be a safe relative path in {manifest_path}")
        data_path = (manifest_path.parent / declared_data_path).resolve()
        if expected_data_path is not None and data_path != expected_data_path.resolve():
            raise GraphValidationError(
                f"graph manifest {manifest_path} points to {data_path}, "
                f"not configured graph {expected_data_path.resolve()}"
            )
        if not data_path.is_file():
            raise GraphValidationError(f"configured graph data file does not exist: {data_path}")

        namespaces = _required_string_list(payload, "namespaces", manifest_path, pattern=_NAMESPACE_RE)
        source = _required_string(payload, "source", manifest_path)
        license_identifier = _required_string(payload, "license", manifest_path)
        expected_sha256 = _required_string(payload, "sha256", manifest_path).lower()
        if not _SHA256_RE.fullmatch(expected_sha256):
            raise GraphValidationError(f"invalid sha256 in graph manifest {manifest_path}")
        actual_sha256 = _sha256_file(data_path)
        if actual_sha256 != expected_sha256:
            raise GraphValidationError(
                f"graph checksum mismatch for {data_path}: expected {expected_sha256}, observed {actual_sha256}"
            )

        authority_role = _required_string(payload, "authority_role", manifest_path)
        if authority_role not in GRAPH_AUTHORITY_ROLES:
            raise GraphValidationError(
                f"invalid authority_role {authority_role!r} in {manifest_path}; "
                f"expected one of {sorted(GRAPH_AUTHORITY_ROLES)}"
            )
        priority = payload.get("priority")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise GraphValidationError(f"priority must be an integer in graph manifest {manifest_path}")
        collision_policy = _required_string(payload, "collision_policy", manifest_path)
        if collision_policy not in GRAPH_COLLISION_POLICIES:
            raise GraphValidationError(
                f"invalid collision_policy {collision_policy!r} in {manifest_path}; "
                f"expected one of {sorted(GRAPH_COLLISION_POLICIES)}"
            )
        relation_vocabulary = _required_string_list(
            payload,
            "relation_vocabulary",
            manifest_path,
            pattern=_RELATION_RE,
        )
        return cls(
            graph_id=graph_id,
            version=version,
            data_path=data_path,
            namespaces=namespaces,
            source=source,
            license=license_identifier,
            sha256=actual_sha256,
            authority_role=authority_role,
            priority=priority,
            collision_policy=collision_policy,
            relation_vocabulary=relation_vocabulary,
            manifest_path=manifest_path,
            manifest_declared=True,
        )

    @classmethod
    def legacy(cls, data_path: Path) -> "GraphManifest":
        """Create an explicit, non-authoritative compatibility spec.

        Direct callers can still load small, local graph fixtures without a
        manifest. Runtime configurations opt into ``require_manifests`` and
        therefore cannot take this path. Legacy graphs never declare a
        collision policy, so any cross-graph node collision fails closed.
        """

        data_path = data_path.resolve()
        if not data_path.is_file():
            raise GraphValidationError(f"configured graph data file does not exist: {data_path}")
        digest = _sha256_file(data_path)
        slug = re.sub(r"[^a-z0-9._-]+", "-", data_path.stem.casefold()).strip("-._") or "graph"
        return cls(
            graph_id=f"legacy.{slug}.{digest[:12]}",
            version="0",
            data_path=data_path,
            namespaces=(),
            source=f"local-file:{data_path}",
            license="NOASSERTION",
            sha256=digest,
            authority_role="vocabulary_hint",
            priority=0,
            collision_policy=None,
            relation_vocabulary=(),
            manifest_path=None,
            manifest_declared=False,
        )

    def as_graph_spec(self) -> GraphSpec:
        """Adapt validated runtime state to the canonical registry contract."""

        artifact_paths = [self.data_path]
        if self.manifest_path is not None:
            artifact_paths.append(self.manifest_path)
        return GraphSpec(
            graph_id=self.graph_id,
            version=self.version,
            provider_ref="agronomy_agent.agno_runtime.knowledge_graph:KnowledgeGraph",
            paths=tuple(path.as_posix() for path in artifact_paths),
            namespaces=self.namespaces,
            schema_id=(
                GRAPH_MANIFEST_SCHEMA_VERSION
                if self.manifest_declared
                else "open_agronomy_agent.legacy_knowledge_graph.v0"
            ),
            source=self.source,
            license=self.license,
            checksum=self.sha256,
            authority_role=self.authority_role,
            merge_priority=self.priority,
            collision_policy=self.collision_policy or "undeclared",
            relation_vocabulary=self.relation_vocabulary,
            manifest_declared=self.manifest_declared,
        )


@dataclass(frozen=True)
class GraphHit:
    node_id: str
    name: str
    kind: str
    evidence: str
    neighbors: tuple[str, ...]
    namespaces: tuple[str, ...]
    # Defaults preserve compatibility with callers that construct GraphHit
    # directly while ensuring loaded hits carry a complete graph origin.
    graph_id: str = "legacy.unknown"
    graph_version: str = "0"
    graph_source: str = "unknown"
    graph_license: str = "NOASSERTION"
    graph_sha256: str = ""
    authority_role: str = "vocabulary_hint"
    relation_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class _LoadedGraphArtifact:
    manifest: GraphManifest
    nodes: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, str], ...]


def load_graph_manifests(
    paths: Iterable[Path],
    *,
    require_manifests: bool = False,
) -> tuple[GraphManifest, ...]:
    """Resolve graph paths and validate their runtime manifests and checksums."""

    manifests: list[GraphManifest] = []
    for value in paths:
        configured_path = Path(value).resolve()
        if configured_path.name.endswith(".manifest.json"):
            if not configured_path.is_file():
                raise GraphValidationError(f"configured graph manifest does not exist: {configured_path}")
            manifest = GraphManifest.from_manifest(configured_path)
        else:
            if not configured_path.is_file():
                raise GraphValidationError(f"configured graph data file does not exist: {configured_path}")
            sidecar = _manifest_sidecar(configured_path)
            if sidecar.is_file():
                manifest = GraphManifest.from_manifest(sidecar, expected_data_path=configured_path)
            elif require_manifests:
                raise GraphValidationError(
                    f"configured graph {configured_path} requires provenance manifest {sidecar}"
                )
            else:
                manifest = GraphManifest.legacy(configured_path)
        manifests.append(manifest)

    graph_ids: dict[str, Path] = {}
    for manifest in manifests:
        previous = graph_ids.get(manifest.graph_id)
        if previous is not None:
            raise GraphValidationError(
                f"duplicate graph_id {manifest.graph_id!r} in {previous} and "
                f"{manifest.manifest_path or manifest.data_path}"
            )
        graph_ids[manifest.graph_id] = manifest.manifest_path or manifest.data_path
    return tuple(manifests)


def load_graph_specs(paths: Iterable[Path], *, require_manifests: bool = False) -> tuple[GraphSpec, ...]:
    """Load canonical registry specs for validated graph artifacts."""

    registry = GraphRegistry(
        manifest.as_graph_spec()
        for manifest in load_graph_manifests(paths, require_manifests=require_manifests)
    )
    return registry.specs


def graph_artifact_paths(paths: Iterable[Path], *, require_manifests: bool = False) -> tuple[Path, ...]:
    """Return every data and manifest artifact that contributes to a graph bundle."""

    resolved: list[Path] = []
    for manifest in load_graph_manifests(paths, require_manifests=require_manifests):
        resolved.append(manifest.data_path)
        if manifest.manifest_path is not None:
            resolved.append(manifest.manifest_path)
    return tuple(resolved)


class KnowledgeGraph:
    def __init__(self, path: Path, *, require_manifest: bool = False) -> None:
        loaded = self.from_paths([path], require_manifests=require_manifest)
        self.__dict__.update(loaded.__dict__)

    @classmethod
    def from_paths(cls, paths: Iterable[Path], *, require_manifests: bool = False) -> "KnowledgeGraph":
        manifests = load_graph_manifests(paths, require_manifests=require_manifests)
        loaded_graphs = tuple(_load_graph(manifest) for manifest in manifests)
        return cls._compose(loaded_graphs)

    @classmethod
    def _compose(cls, graphs: tuple[_LoadedGraphArtifact, ...]) -> "KnowledgeGraph":
        obj = cls.__new__(cls)
        # Input list order must not be merge authority. Priority and graph ID
        # provide a stable total order, and any collision must be declared.
        ordered = sorted(
            graphs,
            key=lambda graph: (
                -graph.manifest.priority,
                graph.manifest.graph_id,
                graph.manifest.version,
                str(graph.manifest.data_path),
            ),
        )
        obj.graph_manifests = tuple(graph.manifest for graph in ordered)
        obj.graph_registry = GraphRegistry(
            manifest.as_graph_spec() for manifest in obj.graph_manifests
        )
        # Public runtime graph specs now use the canonical registry contract.
        obj.graph_specs = obj.graph_registry.specs
        obj.nodes: dict[str, dict[str, Any]] = {}
        obj.node_origins: dict[str, GraphManifest] = {}
        obj.edges: list[dict[str, str]] = []
        obj.edge_origins: list[GraphManifest] = []

        node_candidates: dict[str, list[tuple[GraphManifest, dict[str, Any]]]] = {}
        losing_collided_nodes: dict[str, dict[str, GraphManifest]] = {}
        for graph in ordered:
            for node in graph.nodes:
                node_candidates.setdefault(node["id"], []).append((graph.manifest, node))

        for node_id, candidates in node_candidates.items():
            if len(candidates) > 1:
                policies = {spec.collision_policy for spec, _ in candidates}
                if policies != {"prefer_higher_priority"}:
                    origins = ", ".join(
                        f"{spec.graph_id}@{spec.version} policy={spec.collision_policy or 'undeclared'}"
                        for spec, _ in candidates
                    )
                    raise GraphValidationError(
                        f"duplicate node id {node_id!r} without shared precedence policy: {origins}"
                    )
                top_priority = candidates[0][0].priority
                if sum(spec.priority == top_priority for spec, _ in candidates) != 1:
                    origins = ", ".join(f"{spec.graph_id} priority={spec.priority}" for spec, _ in candidates)
                    raise GraphValidationError(f"duplicate node id {node_id!r} has ambiguous priority: {origins}")
            winner_spec, winner_node = candidates[0]
            for losing_spec, _ in candidates[1:]:
                losing_collided_nodes.setdefault(losing_spec.graph_id, {})[
                    node_id
                ] = winner_spec
            obj.nodes[node_id] = winner_node
            obj.node_origins[node_id] = winner_spec

        known_node_ids = set(obj.nodes)
        seen_edges: set[tuple[str, str, str, str]] = set()
        for graph in ordered:
            for edge in graph.edges:
                source_id = edge["source"]
                target_id = edge["target"]
                graph_losers = losing_collided_nodes.get(graph.manifest.graph_id, {})
                reattached = {
                    node_id: graph_losers[node_id]
                    for node_id in (source_id, target_id)
                    if node_id in graph_losers
                }
                if reattached:
                    collisions = ", ".join(
                        f"{node_id!r} -> winner {winner.graph_id!r}"
                        for node_id, winner in sorted(reattached.items())
                    )
                    raise GraphValidationError(
                        f"edge in losing graph {graph.manifest.graph_id!r} would reattach "
                        f"a collided node to a different graph identity: {source_id!r} "
                        f"-[{edge['relation']}]-> {target_id!r}; {collisions}; "
                        "graph manifests do not declare identity equivalence"
                    )
                if source_id not in known_node_ids or target_id not in known_node_ids:
                    missing = sorted({value for value in (source_id, target_id) if value not in known_node_ids})
                    raise GraphValidationError(
                        f"dangling edge in graph {graph.manifest.graph_id!r}: "
                        f"{source_id!r} -[{edge['relation']}]-> {target_id!r}; missing {missing}"
                    )
                edge_key = (graph.manifest.graph_id, source_id, edge["relation"], target_id)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                obj.edges.append(edge)
                obj.edge_origins.append(graph.manifest)
        obj._build_neighbors()
        return obj

    def _build_neighbors(self) -> None:
        self.neighbor_names: dict[str, list[str]] = {node_id: [] for node_id in self.nodes}
        self.relation_paths: dict[str, list[str]] = {node_id: [] for node_id in self.nodes}
        for edge, edge_origin in zip(self.edges, self.edge_origins, strict=True):
            source_id = edge["source"]
            target_id = edge["target"]
            label = edge["relation"]
            self.neighbor_names[source_id].append(f"{label}: {self.nodes[target_id]['name']}")
            relation_path = f"{edge_origin.graph_id}:{source_id}-[{label}]->{target_id}"
            self.relation_paths[source_id].append(relation_path)
            self.relation_paths[target_id].append(relation_path)
        self.node_tokens: dict[str, set[str]] = {}
        self.node_namespaces: dict[str, set[str]] = {}
        for node_id, node in self.nodes.items():
            haystack = " ".join(
                [
                    node.get("name", ""),
                    node.get("kind", ""),
                    node.get("description", ""),
                    " ".join(node.get("aliases", [])),
                ]
            )
            self.node_tokens[node_id] = set(tokenize(haystack))
            self.node_namespaces[node_id] = set(infer_namespaces(_node_as_doc(node_id, node)))

    def catalog(self) -> tuple[dict[str, Any], ...]:
        """Return the canonical registry records plus runtime composition counts."""

        rows: list[dict[str, Any]] = []
        for spec in self.graph_specs:
            record = spec.as_record()
            # Preserve the existing diagnostic field names while exposing the
            # canonical ``checksum`` and ``merge_priority`` fields alongside
            # them. Documentation consumers can migrate without ambiguity.
            record.update(
                {
                    "sha256": spec.checksum,
                    "priority": spec.merge_priority,
                    "node_count": sum(
                        origin.graph_id == spec.graph_id
                        for origin in self.node_origins.values()
                    ),
                    "edge_count": sum(
                        origin.graph_id == spec.graph_id
                        for origin in self.edge_origins
                    ),
                }
            )
            rows.append(record)
        return tuple(rows)

    def registry_catalog(self) -> dict[str, Any]:
        """Return the graph registry snapshot bound to this runtime instance."""

        return self.graph_registry.catalog()

    def lookup_names(self, names: Iterable[str]) -> list[GraphHit]:
        """Resolve exact concept names or aliases without semantic overreach.

        This is used for governed cross-store joins where a broad token search
        could silently replace a mapped attribute with a related but materially
        different laboratory measurement.
        """

        requested = {str(name).strip().casefold() for name in names if str(name).strip()}
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
            hits.append(self._hit(node_id))
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
        for node_id in self.nodes:
            hay_tokens = self.node_tokens.get(node_id, set())
            overlap = q_tokens & hay_tokens
            expansion_overlap = expansion_tokens & hay_tokens
            if overlap or expansion_overlap:
                score = float(len(overlap)) + (0.35 * len(expansion_overlap))
                if query_nutrients and not query_nutrients & hay_tokens:
                    score *= 0.45
                if "sulfur" in query_nutrients and {"dioxide", "acid"} & hay_tokens and not (
                    {"dioxide", "acid"} & q_tokens
                ):
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
        return [self._hit(node_id) for _, node_id in hits[:limit]]

    def _hit(self, node_id: str) -> GraphHit:
        node = self.nodes[node_id]
        origin = self.node_origins[node_id]
        return GraphHit(
            node_id=node_id,
            name=node["name"],
            kind=node.get("kind", ""),
            evidence=node.get("description", ""),
            neighbors=tuple(self.neighbor_names.get(node_id, [])[:4]),
            namespaces=tuple(sorted(self.node_namespaces.get(node_id, set()))),
            graph_id=origin.graph_id,
            graph_version=origin.version,
            graph_source=origin.source,
            graph_license=origin.license,
            graph_sha256=origin.sha256,
            authority_role=origin.authority_role,
            relation_paths=tuple(self.relation_paths.get(node_id, [])[:4]),
        )


def _load_graph(manifest: GraphManifest) -> _LoadedGraphArtifact:
    payload = _read_json_object(manifest.data_path, kind="knowledge graph")
    raw_nodes = payload.get("nodes")
    raw_edges = payload.get("edges", [])
    if not isinstance(raw_nodes, list):
        raise GraphValidationError(f"knowledge graph nodes must be an array in {manifest.data_path}")
    if not isinstance(raw_edges, list):
        raise GraphValidationError(f"knowledge graph edges must be an array in {manifest.data_path}")

    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for index, raw_node in enumerate(raw_nodes):
        location = f"{manifest.data_path} node[{index}]"
        if not isinstance(raw_node, dict):
            raise GraphValidationError(f"{location} must be an object")
        node_id = _required_string(raw_node, "id", location)
        if node_id in node_ids:
            raise GraphValidationError(
                f"duplicate node id {node_id!r} within graph {manifest.graph_id!r}"
            )
        node_ids.add(node_id)
        _required_string(raw_node, "name", location)
        _required_string(raw_node, "kind", location)
        for key in ("description", "source", "license"):
            if key in raw_node and not isinstance(raw_node[key], str):
                raise GraphValidationError(f"{location}.{key} must be a string")
        aliases = raw_node.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(value, str) for value in aliases):
            raise GraphValidationError(f"{location}.aliases must be an array of strings")
        explicit_namespaces = raw_node.get("namespaces")
        if explicit_namespaces is not None:
            if not isinstance(explicit_namespaces, list) or any(
                not isinstance(value, str) or not _NAMESPACE_RE.fullmatch(value)
                for value in explicit_namespaces
            ):
                raise GraphValidationError(f"{location}.namespaces must contain valid namespace identifiers")
            if manifest.manifest_declared and not set(explicit_namespaces).issubset(manifest.namespaces):
                undeclared = sorted(set(explicit_namespaces) - set(manifest.namespaces))
                raise GraphValidationError(
                    f"{location} uses namespaces absent from manifest {manifest.graph_id!r}: {undeclared}"
                )
        nodes.append(dict(raw_node))

    edges: list[dict[str, str]] = []
    for index, raw_edge in enumerate(raw_edges):
        location = f"{manifest.data_path} edge[{index}]"
        if not isinstance(raw_edge, dict):
            raise GraphValidationError(f"{location} must be an object")
        source = _required_string(raw_edge, "source", location)
        target = _required_string(raw_edge, "target", location)
        relation = _required_string(raw_edge, "relation", location)
        if not _RELATION_RE.fullmatch(relation):
            raise GraphValidationError(f"invalid relation {relation!r} at {location}")
        if manifest.relation_vocabulary and relation not in manifest.relation_vocabulary:
            raise GraphValidationError(
                f"relation {relation!r} at {location} is absent from manifest relation_vocabulary"
            )
        edges.append({"source": source, "target": target, "relation": relation})
    return _LoadedGraphArtifact(
        manifest=manifest,
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


def _manifest_sidecar(data_path: Path) -> Path:
    return data_path.with_name(f"{data_path.stem}.manifest.json")


def _read_json_object(path: Path, *, kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GraphValidationError(f"{kind} does not exist: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GraphValidationError(f"unable to read {kind} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GraphValidationError(f"{kind} must be a JSON object: {path}")
    return payload


def _required_string(payload: dict[str, Any], key: str, location: Path | str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GraphValidationError(f"{location}.{key} must be a non-empty string")
    return value.strip()


def _required_string_list(
    payload: dict[str, Any],
    key: str,
    location: Path | str,
    *,
    pattern: re.Pattern[str],
) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise GraphValidationError(f"{location}.{key} must be a non-empty array")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not pattern.fullmatch(item):
            raise GraphValidationError(f"invalid {key} value {item!r} in {location}")
        if item in normalized:
            raise GraphValidationError(f"duplicate {key} value {item!r} in {location}")
        normalized.append(item)
    return tuple(normalized)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _node_as_doc(node_id: str, node: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": node_id,
        "title": node.get("name", ""),
        "text": node.get("description", ""),
        "tags": [node.get("kind", ""), *node.get("aliases", [])],
    }
