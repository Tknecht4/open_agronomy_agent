"""Controller-only provenance for unchanged historical benchmark renderings.

This module neither renders model prompts nor selects evidence. A frozen
profile describes exact records observed through the canonical product path.
V2 admits a complete rendering or its exact prefix, with explicit delivery
spans; source membership is independently checked by the transport consumer.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

ARTIFACT_SCHEMA = "open_agronomy_agent.render_bound_artifact_contract.v1"
ENVELOPE_SCHEMA = "open_agronomy_agent.canonical_egress_envelope.v2"
PROFILE_SCHEMA = "open_agronomy_agent.canonical_render_profile.v1"
PROVENANCE_SCHEMA = "open_agronomy_agent.rendered_record_provenance.v1"
ROOT = Path(__file__).resolve().parents[2]
RENDERER_FILES = frozenset({
    "src/agronomy_agent/context_packer.py", "configs/context_policy_v1.yaml",
    "configs/rag.yaml", "src/agronomy_agent/agno_runtime/knowledge_graph.py",
    "src/agronomy_agent/agno_runtime/local_index.py",
})
KINDS = {
    "document": ("selected_document_excerpts", "content_fragment", "content_sha256", "source_text", "source_text_fragment", "source_text_fragment_sha256"),
    "graph": ("graph_evidence", "evidence_fragment", "evidence_sha256", "node_evidence_text", "node_evidence_fragment", "node_evidence_fragment_sha256"),
    "guard": ("governed_guard_notes", "outbound_fragment", "outbound_fragment_sha256", "text", None, None),
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def digest(value: Any) -> str:
    return sha(canonical(value))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("render provenance: " + message)


def valid_hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


@lru_cache(maxsize=1)
def _renderer_graph():
    import yaml
    from agronomy_agent.agno_runtime.knowledge_graph import KnowledgeGraph
    retrieval = yaml.safe_load((ROOT/"configs/rag.yaml").read_text())["retrieval"]
    paths = [(ROOT/name).resolve() for name in retrieval["graph_paths"]]
    require(all(p.is_relative_to(ROOT) for p in paths), "graph path outside source")
    return KnowledgeGraph.from_paths(paths, require_manifests=True)


def checked_profile(profile: Mapping[str, Any], *, base_artifact_contract: Mapping[str, Any]) -> dict[str, Any]:
    require(isinstance(profile, Mapping) and set(profile) == {"schema_version", "renderer", "records", "cases", "sha256"}, "profile fields")
    require(profile["schema_version"] == PROFILE_SCHEMA, "profile version")
    require(valid_hash(profile["sha256"]) and profile["sha256"] == digest({k:v for k,v in profile.items() if k != "sha256"}), "profile hash")
    renderer = profile["renderer"]
    require(isinstance(renderer, Mapping) and set(renderer) == {"reference_commit", "reference_source_sha256", "files"}, "renderer fields")
    require(isinstance(renderer["reference_commit"], str) and re.fullmatch(r"[a-f0-9]{40}", renderer["reference_commit"]) is not None, "renderer commit")
    require(valid_hash(renderer["reference_source_sha256"]), "renderer source hash")
    require(isinstance(renderer["files"], Mapping) and set(renderer["files"]) == RENDERER_FILES, "renderer inventory")
    for name, expected in renderer["files"].items():
        require(valid_hash(expected) and hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected, "renderer bytes differ: " + name)
    records = profile["records"]
    require(isinstance(records, Mapping) and len(records) <= 20000, "record inventory")
    for identity, template in records.items():
        require(valid_hash(identity) and isinstance(template, Mapping) and identity == digest(template), "record identity")
        require(set(template) == {"kind", "full_record", "full_render", "full_render_sha256", "identity_header", "body_start", "source_sha256", "renderer_inputs"}, "record fields")
        kind = template["kind"]
        require(kind in KINDS and isinstance(template["full_record"], Mapping), "record kind")
        _, fragment_key, fragment_hash, source_key, _, _ = KINDS[kind]
        record = template["full_record"]
        full, header = template["full_render"], template["identity_header"]
        source = record.get(source_key)
        require(isinstance(full, str) and full and isinstance(source, str) and source, "empty full source/rendering")
        require(isinstance(header, str) and header and full.startswith(header), "identity header")
        require(type(template["body_start"]) is int and len(header) <= template["body_start"] <= len(full), "body offset")
        require(template["full_render_sha256"] == sha(full) and template["source_sha256"] == sha(source), "full source/render hash")
        require(record.get(fragment_key) == full and record.get(fragment_hash) == sha(full), "full membership record")
        start = template["body_start"]
        require(full[start:start+len(source)] == source, "source body bytes")
        inputs = template["renderer_inputs"]
        require(isinstance(inputs, Mapping), "renderer inputs")
        if kind == "guard":
            require(not inputs and header == f"- {record.get('name')}: " and full == header + source and start == len(header), "guard rendering")
        elif kind == "graph":
            require(set(inputs) == {"neighbors"} and isinstance(inputs["neighbors"], list) and all(isinstance(n, str) and n for n in inputs["neighbors"]), "graph neighbors")
            neighbors = "; ".join(inputs["neighbors"]) if inputs["neighbors"] else "no direct neighbors"
            require(header == f"- {record.get('node_name')} ({record.get('node_kind')}): " and full == header + source + f" Related: {neighbors}." and start == len(header), "graph rendering")
            hit = _renderer_graph()._hit(record["node_id"])
            require((hit.name, hit.kind, hit.evidence, hit.graph_sha256, list(hit.neighbors)) ==
                    (record["node_name"], record["node_kind"], source, record["graph_sha256"], inputs["neighbors"]),
                    "graph rendering differs from public source and edges")
        else:
            require(set(inputs) == {"form", "role", "document_attributes", "source_row"}, "document renderer inputs")
            row = inputs["source_row"]
            require(isinstance(row, Mapping) and digest(row) == record.get("document_row_sha256"), "public document row hash")
            corpus = base_artifact_contract["allowed_corpora"].get(record.get("corpus_path_sha256"))
            require(isinstance(corpus, Mapping), "document corpus membership")
            member = corpus["allowed_documents"].get(record.get("document_identity_sha256"))
            require(isinstance(member, Mapping) and member.get("row_sha256") == digest(row), "public document row membership")
            if inputs["form"] == "source_projection":
                require(not inputs["role"] and not inputs["document_attributes"], "projection attributes")
                require(header == f"Source: {record.get('title')}: " and full == header + source and start == len(header), "source projection")
            else:
                require(inputs["form"] == "packed" and inputs["role"] in {"CONSTRAINT", "BOUNDED ACTION SUPPORT", "SOURCE INTERPRETATION", "SUPPORTING", "REGIONAL PRIOR", "VOCABULARY"}, "packed role")
                attrs = inputs["document_attributes"]
                require(isinstance(attrs, Mapping) and set(attrs) == {"retrieval_policy", "content_risk_tags", "answer_role", "transfer_scope", "applicability_boundary"}, "document attributes")
                # Authenticate policy inputs against the admitted public row,
                # including the original retriever's corpus-level restriction.
                # The retriever implementation is itself renderer-hash-bound.
                from agronomy_agent.agno_runtime.local_index import _normalize_string_values
                policy = str(row.get("retrieval_policy") or "standard").strip().lower()
                if policy != "requires_live_authority" and (corpus["runtime_eligibility"] == "context_only" or policy == "context_only"):
                    policy = "context_only"
                expected_attrs = {
                    "retrieval_policy": policy,
                    "content_risk_tags": _normalize_string_values(row.get("content_risk_tags")),
                    **{k:str(row.get(k) or "") for k in ("answer_role", "transfer_scope", "applicability_boundary")},
                }
                require(dict(attrs) == expected_attrs, "document policy inputs differ from admitted source")
                from types import SimpleNamespace
                from agronomy_agent.context_packer import _doc_policy_note
                prefix = f"- [{inputs['role']}] [{record.get('doc_id')}]."
                complete_header = prefix + _doc_policy_note(SimpleNamespace(**attrs)) + f" Title: {record.get('title')}. Source: {record.get('source')}. Excerpt: "
                require(header == prefix and full == complete_header + source and start == len(complete_header), "packed rendering")
    cases = profile["cases"]
    require(isinstance(cases, Mapping) and cases, "case inventory")
    for case_id, case in cases.items():
        require(isinstance(case_id, str) and case_id and isinstance(case, Mapping) and set(case) == {"question_sha256", "scopes"}, "case fields")
        require(valid_hash(case["question_sha256"]) and isinstance(case["scopes"], Mapping), "case identity")
        require(set(case["scopes"]) <= {"candidate_generation", "verification"}, "case phases")
        for phase, scope in case["scopes"].items():
            require(isinstance(scope, Mapping) and set(scope) == {"messages_sha256", "evidence_sha256", "records", "selected_context", "render_frames"}, "scope fields")
            require(valid_hash(scope["messages_sha256"]) if phase == "candidate_generation" else scope["messages_sha256"] is None, "message binding")
            require(valid_hash(scope["evidence_sha256"]) if phase == "verification" else scope["evidence_sha256"] is None, "evidence binding")
            require(isinstance(scope["records"], list) and len(scope["records"]) <= 128, "scope record count")
            selected = scope["selected_context"]
            require(isinstance(selected, Mapping) and set(selected) == {"documents", "guard_names", "graph_record_order"}, "selected context fields")
            require(isinstance(selected["documents"], list) and isinstance(selected["guard_names"], list) and isinstance(selected["graph_record_order"], list), "selected context inventory")
            source_headers = {}
            for member in selected["documents"]:
                require(isinstance(member, Mapping) and set(member) == {"corpus_path_sha256", "document_identity_sha256"}, "selected document fields")
                corpus = base_artifact_contract["allowed_corpora"].get(member["corpus_path_sha256"], {})
                public = corpus.get("allowed_documents", {}).get(member["document_identity_sha256"])
                require(isinstance(public, Mapping), "selected context document outside public inventory")
                source_headers[member["document_identity_sha256"]] = f"Source: {public['title']}: "
            require(len(selected["guard_names"]) == len(set(selected["guard_names"])) and all(isinstance(n, str) and n.endswith("_guard") for n in selected["guard_names"]), "selected guard identities")
            order = selected["graph_record_order"]
            require(all(k in records and records[k]["kind"] == "graph" for k in order), "selected graph order")
            frames = scope["render_frames"]
            require(isinstance(frames, list), "render frame inventory")
            import yaml
            policy = yaml.safe_load((ROOT/"configs/context_policy_v1.yaml").read_text())
            slot = next(row for row in policy["slots"] if row["slot"] == "kg_vocabulary_hints")
            graph_occurrences = []
            header = "Knowledge graph vocabulary hints:\n"
            for frame in frames:
                require(isinstance(frame, Mapping) and set(frame) == {"message_index", "start", "prefix", "record_ids"}, "graph frame fields")
                require(type(frame["message_index"]) is int and frame["message_index"] in {0,1} and type(frame["start"]) is int and frame["start"] >= 0, "graph frame position")
                require(phase != "verification" or frame["message_index"] == 1, "verifier frame outside evidence")
                require(frame["record_ids"] == order[:slot["max_items"]] and bool(frame["record_ids"]), "graph frame differs from original selected order")
                full = header + "\n".join(records[k]["full_render"] for k in frame["record_ids"])
                prefix = frame["prefix"]
                require(isinstance(prefix, str) and prefix.startswith(header) and len(prefix)>len(header) and full.startswith(prefix) and len(prefix)<=slot["max_tokens"]*4, "graph frame is not a bounded original render prefix")
                start, remaining = frame["start"]+len(header), prefix[len(header):]
                for identity in frame["record_ids"]:
                    if not remaining:break
                    rendered = records[identity]["full_render"]
                    fragment = rendered[:len(remaining)]
                    require(remaining.startswith(fragment), "graph frame record bytes")
                    graph_occurrences.append((identity, fragment, frame["message_index"], start, start+len(fragment)))
                    remaining=remaining[len(rendered):]
                    if remaining:
                        require(remaining.startswith("\n"), "graph frame separator")
                        remaining=remaining[1:]
                    start+=len(rendered)+1
            observed_graph_occurrences=[]
            for item in scope["records"]:
                require(isinstance(item, Mapping) and set(item) == {"record_id", "fragment", "spans"}, "scope record fields")
                require(item["record_id"] in records and isinstance(item["fragment"], str), "scope record identity")
                template = records[item["record_id"]]
                require(bool(item["fragment"]) and template["full_render"].startswith(item["fragment"]), "not an exact canonical render prefix")
                if not item["fragment"].startswith(template["identity_header"]):
                    require(len(item["fragment"]) <= template["body_start"], "partial identity cannot contain source body")
                    if template["kind"] == "document":
                        require(template["renderer_inputs"]["form"] == "source_projection" and item["fragment"].startswith("Source: ") and len(item["fragment"])>len("Source: "), "unframed partial packed-document identity")
                        compatible=[identity for identity, h in source_headers.items() if h.startswith(item["fragment"])]
                        require(compatible == [template["full_record"]["document_identity_sha256"]], "partial document header is ambiguous in original selected context")
                    elif template["kind"] == "guard":
                        require(item["fragment"].startswith("- "+template["full_record"]["name"]), "partial guard must visibly identify its governed name")
                        compatible=[n for n in selected["guard_names"] if ("- "+n+": ").startswith(item["fragment"])]
                        require(compatible == [template["full_record"]["name"]], "partial guard header is ambiguous in original selected context")
                require(isinstance(item["spans"], list) and item["spans"], "missing frozen occurrences")
                for span in item["spans"]:
                    require(isinstance(span, Mapping) and set(span) == {"message_index", "start", "end"}, "span fields")
                    require(all(type(span[k]) is int for k in span), "span integer type")
                    require(span["message_index"] in {0, 1} and 0 <= span["start"] < span["end"] and span["end"]-span["start"] == len(item["fragment"]), "span range")
                    require(phase != "verification" or span["message_index"] == 1, "verifier source belongs in its user evidence frame")
                    if template["kind"] == "graph":
                        observed_graph_occurrences.append((item["record_id"], item["fragment"], span["message_index"], span["start"], span["end"]))
            require(sorted(observed_graph_occurrences) == sorted(graph_occurrences), "graph records lack exact original ordered-slot prefix proof")
    return json.loads(canonical(profile))


def build_records(profile: Mapping[str, Any], *, eval_id: str, phase: str, arm: str,
                  messages: Sequence[Mapping[str, str]], question: str,
                  verifier_evidence_text: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Bind frozen source records to actual messages without changing messages."""
    result = {spec[0]: [] for spec in KINDS.values()}
    case = profile["cases"].get(eval_id)
    require(isinstance(case, Mapping) and case["question_sha256"] == sha(question), "question outside original scope")
    if arm == "raw_model":
        require(phase == "candidate_generation", "raw phase")
        return result
    require(arm == "production_full" and phase in case["scopes"], "uncompiled full-system scope")
    scope = case["scopes"][phase]
    if phase == "candidate_generation":
        require(digest(list(messages)) == scope["messages_sha256"], "actual model messages changed")
    else:
        require(isinstance(verifier_evidence_text, str) and sha(verifier_evidence_text) == scope["evidence_sha256"], "actual verifier evidence changed")
    # A structurally valid declared frame is insufficient: its complete
    # header/prefix must occur at the frozen location in the actual request.
    # In particular, an unrelated bare dash cannot imply a graph identity.
    for frame in scope["render_frames"]:
        index, start = frame["message_index"], frame["start"]
        require(index < len(messages), "frame message index")
        content = messages[index]["content"]
        if phase == "verification":
            prefix = f"USER QUESTION\n{question}\n\nALLOWED EVIDENCE\n"
            evidence = (verifier_evidence_text or "").strip()
            require(messages[index]["role"] == "user" and content.startswith(prefix+evidence), "exact verifier frame")
            require(start+len(frame["prefix"]) <= len(evidence), "frame outside verifier evidence")
            start += len(prefix)
        end = start+len(frame["prefix"])
        require(content[start:end] == frame["prefix"], "actual original render frame differs")
        require(start == 0 or content[start-1] == "\n", "render frame start boundary")
        require(end == len(content) or content[end] == "\n", "render frame end boundary")
    occupied: list[tuple[int, int, int]] = []
    for item in scope["records"]:
        identity, fragment = item["record_id"], item["fragment"]
        template = profile["records"][identity]
        kind = template["kind"]
        group, fragment_key, fragment_hash, source_key, source_fragment_key, source_fragment_hash = KINDS[kind]
        record = dict(template["full_record"])
        spans = []
        # Candidate positions are frozen absolute message offsets. Verifier
        # positions are frozen relative to the exact admitted evidence field;
        # a variable draft can never create another source occurrence.
        for frozen in item["spans"]:
            index = frozen["message_index"]
            require(index < len(messages), "message span index")
            content = messages[index]["content"]
            offset, end = frozen["start"], frozen["end"]
            if phase == "verification":
                prefix = f"USER QUESTION\n{question}\n\nALLOWED EVIDENCE\n"
                rendered_evidence = (verifier_evidence_text or "").strip()
                require(messages[index]["role"] == "user" and content.startswith(prefix + rendered_evidence), "exact verifier evidence frame")
                require(end <= len(rendered_evidence), "span outside verifier evidence")
                offset, end = offset + len(prefix), end + len(prefix)
            else:
                question_at = content.find(question)
                require(question_at < 0 or end <= question_at or offset >= question_at + len(question), "source span reclassifies question text")
            require(0 <= offset < end <= len(content) and content[offset:end] == fragment, "actual source span differs")
            require(offset == 0 or content[offset-1] == "\n", "source is not a rendered record boundary")
            require(end == len(content) or content[end] == "\n", "source span cuts a longer rendered line")
            require(not any(i == index and offset < b and a < end for i, a, b in occupied), "overlapping source spans")
            occupied.append((index, offset, end))
            spans.append({"message_index": index, "start": offset, "end": end})
        require(bool(spans), "source fragment absent from its actual evidence frame")
        delivered = max(0, min(len(record[source_key]), len(fragment) - template["body_start"]))
        record[fragment_key], record[fragment_hash] = fragment, sha(fragment)
        if source_fragment_key is not None:
            record[source_fragment_key] = record[source_key][:delivered]
            record[source_fragment_hash] = sha(record[source_fragment_key])
        if kind == "document":
            record["excerpt_chars"] = len(fragment)
        record["render_provenance"] = {
            "schema_version": PROVENANCE_SCHEMA, "record_id": identity,
            "profile_sha256": profile["sha256"], "full_render_sha256": template["full_render_sha256"],
            "full_source_sha256": template["source_sha256"],
            "mode": "complete" if fragment == template["full_render"] else "prefix",
            "delivered_source_chars": delivered, "metadata_only": delivered == 0,
            "identity_header_complete": fragment.startswith(template["identity_header"]),
            "identity_binding": ("observed_complete_header" if fragment.startswith(template["identity_header"])
                else "controller_inferred_original_slot_order" if kind == "graph"
                else "controller_inferred_unique_selected_header"),
            "source_body_complete": delivered == len(record[source_key]), "spans": spans,
        }
        result[group].append(record)
    return result
