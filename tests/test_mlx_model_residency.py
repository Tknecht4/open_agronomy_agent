"""Model-free contracts for bounded MLX weight ownership."""

from __future__ import annotations

import gc
import json
import sys
import time
import types
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

import pytest

from agronomy_agent import agent


class _Model:
    pass


class _Tokenizer:
    def apply_chat_template(self, messages, *, tokenize, **_kwargs):
        return [1, 2, 3] if tokenize else "prompt"


@pytest.fixture
def fake_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snapshots: dict[str, Path] = {}
    calls: list[str] = []
    references: list[weakref.ReferenceType[_Model]] = []
    failures: set[str] = set()

    def resolve(model_id: str, *, revision: str | None = None) -> Path:
        name = f"{model_id.replace('/', '_')}@{revision or 'main'}"
        if name not in snapshots:
            path = tmp_path / name
            path.mkdir()
            (path / "config.json").write_text(json.dumps({"max_position_embeddings": 4096}))
            snapshots[name] = path
        return snapshots[name]

    def load(path: str):
        calls.append(path)
        if Path(path).name in failures:
            raise RuntimeError("fixture load failed")
        model = _Model()
        references.append(weakref.ref(model))
        return model, _Tokenizer()

    mlx = types.ModuleType("mlx_lm")
    mlx.load = load  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx_lm", mlx)
    monkeypatch.setattr(agent, "resolve_local_model_snapshot", resolve)
    agent._MLX_MODEL_CACHE.clear()
    agent.reset_mlx_prompt_caches()
    yield snapshots, calls, references, failures
    agent._MLX_MODEL_CACHE.clear()
    agent.reset_mlx_prompt_caches()


def test_reusable_generators_do_not_pin_evicted_models(fake_models, monkeypatch: pytest.MonkeyPatch):
    _, calls, references, _ = fake_models
    seen: list[_Model] = []

    def generate(self, _messages, **_kwargs):
        seen.append(self._model)
        return "answer"

    monkeypatch.setattr(agent.MLXGenerator, "_generate_locked", generate)
    first = agent.MLXGenerator("model/a", model_revision="r1")
    second = agent.MLXGenerator("model/b", model_revision="r1")
    first.warmup()
    assert first._model is None and len(agent._MLX_MODEL_CACHE) == 1
    assert first.count_prompt_tokens([]) == 3
    assert first._model is None and len(calls) == 1
    first.generate([])
    assert first.last_generation_stats["model_load_status"] == "already_loaded"
    seen.clear()
    second.generate([])
    assert second._model is None and len(agent._MLX_MODEL_CACHE) == 1
    gc.collect()
    assert references[0]() is None
    assert first.count_prompt_tokens([]) == 3
    assert first._pending_model_load_ms is not None
    first.generate([])
    assert first._model is None and len(agent._MLX_MODEL_CACHE) == 1
    assert first.last_generation_stats["model_load_status"] == "loaded_during_prompt_count"
    assert len(calls) == 3


def test_pair_identity_includes_draft_snapshot_and_evicts_kv(fake_models):
    snapshots, calls, references, _ = fake_models
    first = agent.MLXGenerator("target", model_revision="r1", draft_model_id="draft")
    first.warmup()
    assert len(calls) == 2
    pair = next(iter(agent._MLX_MODEL_CACHE))
    assert str(snapshots["target@r1"]) in pair[0]
    assert str(snapshots["draft@main"]) in pair[1]
    agent._MLX_PREFIX_CACHES[("old",)] = object()
    other = agent.MLXGenerator("target", model_revision="r2", draft_model_id="draft")
    other.warmup()
    assert len(agent._MLX_MODEL_CACHE) == 1
    assert len(calls) == 4
    assert not agent._MLX_PREFIX_CACHES
    gc.collect()
    assert references[0]() is None and references[1]() is None
    first.warmup()
    assert len(calls) == 6


def test_failed_draft_load_leaves_no_partial_pair_or_generator_refs(fake_models):
    _, calls, _, failures = fake_models
    failures.add("draft@main")
    generator = agent.MLXGenerator("target", draft_model_id="draft")
    with pytest.raises(RuntimeError, match="fixture load failed"):
        generator.warmup()
    assert len(calls) == 2
    assert not agent._MLX_MODEL_CACHE
    assert generator._model is None and generator._draft_model is None
    failures.clear()
    generator.warmup()
    assert len(calls) == 4 and len(agent._MLX_MODEL_CACHE) == 1


def test_active_pair_cannot_be_evicted_and_count_load_is_rechecked(
    fake_models, monkeypatch: pytest.MonkeyPatch,
):
    _, calls, _, _ = fake_models
    first = agent.MLXGenerator("first")
    second = agent.MLXGenerator("second")
    first._load()
    try:
        with pytest.raises(RuntimeError, match="active operation"):
            second.warmup()
        assert len(calls) == 1
        assert len(agent._MLX_MODEL_CACHE) == 1
    finally:
        first._release_model()
    second.warmup()
    first.count_prompt_tokens([])
    assert first._pending_model_load_ms is not None
    second.warmup()
    assert first._model is None
    monkeypatch.setattr(agent.MLXGenerator, "_generate_locked", lambda *_args, **_kwargs: "answer")
    first.generate([])
    assert len(calls) == 5
    assert first.last_generation_stats["model_load_status"] == "loaded_during_generation"
    assert agent._MLX_ACTIVE_MODEL_USES == 0


def test_count_failure_releases_model_lease(fake_models, monkeypatch: pytest.MonkeyPatch):
    def fail_count(self, _messages, **_kwargs):
        raise ValueError("fixture tokenizer failed")

    monkeypatch.setattr(_Tokenizer, "apply_chat_template", fail_count)
    generator = agent.MLXGenerator("count-failure")
    with pytest.raises(ValueError, match="fixture tokenizer failed"):
        generator.count_prompt_tokens([])
    assert generator._model is None and generator._tokenizer is None
    assert generator._pending_model_load_ms is None
    assert agent._MLX_ACTIVE_MODEL_USES == 0


def test_count_and_generate_requests_are_serialized_and_release_on_failure(
    fake_models, monkeypatch: pytest.MonkeyPatch,
):
    _, _, _, _ = fake_models
    active = 0
    maximum = 0
    lock = Lock()

    def generate(self, _messages, **_kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        if self.model_id == "bad":
            raise RuntimeError("fixture generation failed")
        return "answer"

    monkeypatch.setattr(agent.MLXGenerator, "_generate_locked", generate)
    generators = [agent.MLXGenerator(name) for name in ("a", "bad", "b", "a")]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(g.generate, []) for g in generators]
        assert futures[0].result() == "answer"
        with pytest.raises(RuntimeError, match="fixture generation failed"):
            futures[1].result()
        assert futures[2].result() == futures[3].result() == "answer"
    assert maximum == 1
    assert len(agent._MLX_MODEL_CACHE) == 1
    assert all(g._model is None for g in generators)
    assert all(g._pending_model_load_ms is None for g in generators)
