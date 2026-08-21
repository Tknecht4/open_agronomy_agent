"""Hash-bound lazy access to large offline corpus releases.

The normal product index is intentionally compact.  A release registered here
is still part of the offline product, but its shards are read only after an
explicit request that names its jurisdictional scope.  This prevents a large
analogue corpus from changing ordinary Canadian retrieval or startup time.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from heapq import nlargest
from pathlib import Path
from typing import Any

from agronomy_agent.agno_runtime.local_index import RetrievedDoc, tokenize
from agronomy_agent.corpus_release import canonical_json


_EXPLICIT_US_NRCS_RE = re.compile(
    r"\b(?:nrcs|usda|united states|u\.s\.|mlra|major land resource|ecological site|"
    r"ecological-site)\b",
    re.IGNORECASE,
)
# MLRA identifiers are zero-padded three-digit codes followed by a letter.
# Capture the entire identifier: dropping a leading zero turns ``001X`` into
# ``01X`` and silently expands an explicit request to the whole release.
_MLRA_RE = re.compile(r"\b(?:mlra\s*)?(\d{3}[a-z])\b", re.IGNORECASE)
_CANADIAN_DECISIVE_REQUEST_RE = re.compile(
    r"\b(?:canada|canadian|alberta|saskatchewan|manitoba|ontario|quebec|british columbia)\b.*\b(?:legal|label|rate|threshold|prescription|calibration)\b|\b(?:legal|label|rate|threshold|prescription|calibration)\b.*\b(?:canada|canadian|alberta|saskatchewan|manitoba|ontario|quebec|british columbia)\b",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class OnDemandCorpusRelease:
    """A validated immutable release whose retrievers are built lazily."""

    manifest_path: Path
    release_id: str
    activation: str
    jurisdiction: str
    retrieval_policy: str
    _manifest: dict[str, Any]
    _documents: dict[tuple[str, ...], list[dict[str, Any]]] = field(default_factory=dict)
    _statistics_index_path: Path | None = None
    _statistics_index_sha256: str | None = None
    _statistics: dict[str, Any] | None = None

    @classmethod
    def from_config(cls, entry: dict[str, Any]) -> "OnDemandCorpusRelease":
        path = Path(str(entry.get("manifest_path") or ""))
        if not path.is_file():
            raise ValueError(f"on-demand release manifest is missing: {path}")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        declared = str(manifest.get("store_sha256") or "")
        unsigned = dict(manifest)
        unsigned.pop("store_sha256", None)
        if len(declared) != 64 or hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest() != declared:
            raise ValueError(f"on-demand release manifest hash mismatch: {path}")
        release_id = str(entry.get("release_id") or "")
        if release_id != str(manifest.get("release_id") or ""):
            raise ValueError("on-demand release id does not match manifest")
        if str(entry.get("activation") or "") != "explicit_us_nrcs_or_mlra":
            raise ValueError("unsupported on-demand corpus activation")
        if str(entry.get("retrieval_policy") or "") != "context_only":
            raise ValueError("on-demand corpus must be context-only")
        index = manifest.get("bm25_statistics_index")
        if not isinstance(index, dict):
            raise ValueError("on-demand corpus is missing persisted BM25 statistics")
        index_path = path.parent / str(index.get("path") or "")
        index_sha256 = str(index.get("sha256") or "")
        if not index_path.is_file() or _sha256(index_path) != index_sha256:
            raise ValueError("on-demand corpus BM25 statistics failed hash validation")
        release = cls(
            manifest_path=path,
            release_id=release_id,
            activation=str(entry["activation"]),
            jurisdiction=str(entry.get("jurisdiction") or ""),
            retrieval_policy=str(entry["retrieval_policy"]),
            _manifest=manifest,
            _statistics_index_path=index_path,
            _statistics_index_sha256=index_sha256,
        )
        return release

    def _statistics_for(self, relative_shards: tuple[str, ...]) -> dict[str, Any]:
        if self._statistics is None:
            if self._statistics_index_path is None:
                raise ValueError("on-demand corpus lacks BM25 statistics index")
            payload = json.loads(self._statistics_index_path.read_text(encoding="utf-8"))
            declared = str(payload.get("index_sha256") or "")
            unsigned = dict(payload)
            unsigned.pop("index_sha256", None)
            if declared != hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest():
                raise ValueError("on-demand corpus BM25 statistics hash mismatch")
            self._statistics = {
                str(item.get("path") or ""): item
                for item in payload.get("shards") or []
                if isinstance(item, dict)
            }
        selected = {relative: self._statistics.get(relative) for relative in relative_shards}
        if any(value is None for value in selected.values()):
            raise ValueError("on-demand corpus BM25 statistics omit a selected shard")
        document_lengths: dict[str, int] = {}
        document_frequencies: Counter[str] = Counter()
        document_count = 0
        for item in selected.values():
            assert isinstance(item, dict)
            document_count += int(item.get("document_count") or 0)
            document_lengths.update({str(key): int(value) for key, value in (item.get("document_token_counts") or {}).items()})
            document_frequencies.update({str(key): int(value) for key, value in (item.get("document_frequencies") or {}).items()})
        average_length = sum(document_lengths.values()) / max(1, document_count)
        return {"document_lengths": document_lengths, "document_frequencies": document_frequencies, "document_count": document_count, "average_length": average_length}

    def activates_for(self, question: str) -> bool:
        # An explicit U.S. reference may request analogue context, but it must
        # never enter a Canadian decisive/legal-rate request merely because the
        # question also mentions USDA or an ecological-site description.
        return (
            bool(_EXPLICIT_US_NRCS_RE.search(question))
            and bool(_MLRA_RE.search(question))
            and not bool(_CANADIAN_DECISIVE_REQUEST_RE.search(question))
        )

    def _selected_relative_shards(self, question: str) -> tuple[str, ...]:
        by_mlra = self._manifest.get("mlra_shards") or {}
        selected: set[str] = set()
        for match in _MLRA_RE.finditer(question):
            selected.update(str(value) for value in by_mlra.get(match.group(1).upper(), []) if value)
        if selected:
            return tuple(sorted(selected))
        return tuple(str(item["path"]) for item in self._manifest.get("shards") or [])

    def _documents_for(self, relative_shards: tuple[str, ...]) -> list[dict[str, Any]]:
        cached = self._documents.get(relative_shards)
        if cached is not None:
            return cached
        by_path = {str(item.get("path") or ""): item for item in self._manifest.get("shards") or []}
        documents: list[dict[str, Any]] = []
        for relative in relative_shards:
            item = by_path.get(relative)
            if item is None:
                raise ValueError(f"on-demand manifest lacks selected shard: {relative}")
            path = self.manifest_path.parent / relative
            if not path.is_file() or _sha256(path) != str(item.get("sha256") or ""):
                raise ValueError(f"on-demand release shard failed hash validation: {path}")
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        record = json.loads(line)
                        record["_corpus_path"] = path.as_posix()
                        documents.append(record)
        self._documents[relative_shards] = documents
        return documents

    @staticmethod
    def _to_retrieved_doc(record: dict[str, Any], score: float) -> RetrievedDoc:
        locator = record.get("source_locator") if isinstance(record.get("source_locator"), dict) else None
        return RetrievedDoc(
            doc_id=str(record.get("doc_id") or ""),
            title=str(record.get("title") or ""),
            text=str(record.get("text") or ""),
            source=str(record.get("source") or ""),
            score=round(score, 4),
            tags=tuple(str(value) for value in record.get("tags") or []),
            namespaces=(),
            source_type=str(record.get("source_type") or ""),
            allowed_roles=tuple(str(value) for value in record.get("allowed_roles") or []),
            knowledge_domains=tuple(str(value) for value in record.get("knowledge_domains") or []),
            knowledge_bucket=str(record.get("knowledge_bucket") or ""),
            source_id=str(record.get("source_id") or record.get("source") or ""),
            jurisdictions=tuple(str(value) for value in record.get("jurisdiction") or record.get("region") or []),
            retrieval_policy=str(record.get("retrieval_policy") or "context_only"),
            raw_sha256=str(record.get("raw_sha256") or ""),
            chunk_sha256=str(record.get("chunk_sha256") or ""),
            corpus_path=str(record.get("_corpus_path") or ""),
            transfer_scope=str(record.get("transfer_scope") or ""),
            applicability_boundary=str(record.get("applicability_boundary") or ""),
            source_locator=dict(locator) if locator else None,
        )

    def search(self, question: str, **kwargs: Any) -> list[RetrievedDoc]:
        if not self.activates_for(question):
            return []
        top_k = int(kwargs.get("top_k", 5))
        permitted_policies = {str(value) for value in kwargs.get("retrieval_policies") or ()}
        documents = self._documents_for(self._selected_relative_shards(question))
        statistics = self._statistics_for(self._selected_relative_shards(question))
        requested_mlras = {match.group(1).upper() for match in _MLRA_RE.finditer(question)}
        query_tokens = tokenize(" ".join([question, *[str(value) for value in kwargs.get("query_expansion") or ()]]))
        if not query_tokens:
            return []
        query_counts = Counter(query_tokens)
        eligible = [
            record
            for record in documents
            if not permitted_policies or str(record.get("retrieval_policy") or "context_only") in permitted_policies
        ]
        if not eligible:
            return []
        token_counts: list[Counter[str]] = []
        lengths: list[int] = []
        for record in eligible:
            # Exact BM25 tokenization is deliberately shared with the compact
            # retriever.  The release is lazy at the shard boundary, never by
            # replacing token length with a character-count approximation.
            tokens = tokenize(
                " ".join(
                    [
                        str(record.get("title") or ""),
                        str(record.get("mlra") or ""),
                        *[str(value) for value in record.get("tags") or ()],
                        str(record.get("text") or ""),
                    ]
                )
            )
            counts = Counter(token for token in tokens if token in query_counts)
            counts = Counter({token: count for token, count in counts.items() if count})
            token_counts.append(counts)
            expected_length = statistics["document_lengths"].get(str(record.get("doc_id") or ""))
            if expected_length is None or int(expected_length) != len(tokens):
                raise ValueError("on-demand corpus BM25 statistics do not match source record")
            lengths.append(max(1, int(expected_length)))
        doc_freq: Counter[str] = statistics["document_frequencies"]
        average_length = float(statistics["average_length"])
        scores: list[tuple[float, int]] = []
        total = int(statistics["document_count"])
        for index, counts in enumerate(token_counts):
            score = 0.0
            norm = 1.2 * (1 - 0.75 + 0.75 * lengths[index] / max(1.0, average_length))
            for token, query_count in query_counts.items():
                frequency = counts.get(token, 0)
                if not frequency:
                    continue
                idf = math.log(1 + (total - doc_freq[token] + 0.5) / (doc_freq[token] + 0.5))
                score += query_count * idf * (frequency * 2.2 / (frequency + norm))
            # An explicit MLRA identifier is a source selector, not merely a
            # lexical hint.  The selected shard can contain several MLRAs, so
            # prefer records whose immutable metadata exactly matches the
            # requested identifier before general BM25 ordering.
            if requested_mlras and str(eligible[index].get("mlra") or "").upper() in requested_mlras:
                score += 100.0
            if score > 0:
                scores.append((score, index))
        return [self._to_retrieved_doc(eligible[index], score) for score, index in nlargest(top_k, scores)]
