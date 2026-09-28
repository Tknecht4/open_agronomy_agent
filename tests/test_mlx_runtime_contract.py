"""Model-free contracts for token accounting and isolated, bounded KV reuse."""

from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from agronomy_agent import agent


class _Tokenizer:
    def apply_chat_template(self, messages: list[dict[str, str]], *, tokenize: bool, **_: Any) -> Any:
        text = "|".join(f"{item['role']}:{item['content']}" for item in messages) + "|assistant:"
        return list(text.encode()) if tokenize else text

    def encode(self, text: str, *, add_special_tokens: bool = False) -> list[int]:
        return list(text.encode())


class _FakePrefixCache:
    def __init__(self, *, max_size: int, max_bytes: int) -> None:
        self.max_size = max_size
        self.max_bytes = max_bytes
        self.entries: dict[tuple[str, tuple[int, ...]], tuple[list[dict[str, Any]], int]] = {}

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def nbytes(self) -> int:
        return sum(size for _, size in self.entries.values())

    def insert_cache(self, model: str, tokens: list[int], value: list[dict[str, Any]], *, cache_type: str) -> None:
        assert cache_type == "system"
        self.entries[(model, tuple(tokens))] = (value, sum(item["nbytes"] for item in value))
        while len(self.entries) > self.max_size or self.nbytes > self.max_bytes:
            self.entries.pop(next(iter(self.entries)))

    def fetch_nearest_cache(self, model: str, tokens: list[int]) -> tuple[Any, list[int]]:
        hits = [
            (prefix, value) for (model_id, prefix), (value, _) in self.entries.items()
            if model_id == model and tokens[:len(prefix)] == list(prefix)
        ]
        if not hits:
            return None, tokens
        prefix, value = max(hits, key=lambda hit: len(hit[0]))
        return copy.deepcopy(value), tokens[len(prefix):]


@pytest.fixture
def fake_cache(monkeypatch: pytest.MonkeyPatch):
    module = types.ModuleType("mlx_lm.models.cache")
    module.LRUPromptCache = _FakePrefixCache  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx_lm.models.cache", module)
    agent.reset_mlx_prompt_caches()
    yield
    agent.reset_mlx_prompt_caches()


def test_exact_count_and_declared_context_from_local_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    (tmp_path / "config.json").write_text(json.dumps({
        "text_config": {"max_position_embeddings": 8192},
    }))
    fake_mlx = types.ModuleType("mlx_lm")
    fake_mlx.load = lambda _: (object(), _Tokenizer())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx_lm", fake_mlx)
    monkeypatch.setattr(agent, "resolve_local_model_snapshot", lambda *_args, **_kwargs: tmp_path)
    generator = agent.MLXGenerator("fixture/model")
    assert generator.context_window_tokens is None
    messages = [{"role": "system", "content": "A"}, {"role": "user", "content": "B"}]
    assert generator.count_prompt_tokens(messages) == len(b"system:A|user:B|assistant:")
    assert generator.context_window_tokens == 8192
    assert generator._pending_model_load_ms is not None


def test_cache_scope_revision_and_kv_settings_isolate_mutable_entries(fake_cache) -> None:
    first = agent.MLXGenerator("fixture/model", model_revision="r1", prompt_cache_enabled=True)
    first.set_cache_scope("session-a:draft")
    tokens = [1, 2, 3]
    first._prefix_cache().insert_cache(first.model_id, tokens, [{"nbytes": 4, "state": [1]}], cache_type="system")
    fetched, rest = first._prefix_cache().fetch_nearest_cache(first.model_id, [1, 2, 3, 4])
    assert rest == [4]
    fetched[0]["state"].append(99)
    assert first._prefix_cache().fetch_nearest_cache(first.model_id, [1, 2, 3, 4])[0][0]["state"] == [1]

    variants = [
        agent.MLXGenerator("fixture/model", model_revision="r2", prompt_cache_enabled=True),
        agent.MLXGenerator("fixture/model", model_revision="r1", kv_bits=4, prompt_cache_enabled=True),
        agent.MLXGenerator("fixture/model", model_revision="r1", max_kv_size=128, prompt_cache_enabled=True),
        agent.MLXGenerator("fixture/model", model_revision="r1", prefill_step_size=512, prompt_cache_enabled=True),
    ]
    for variant in variants:
        variant.set_cache_scope("session-a:draft")
        assert variant._prefix_cache().fetch_nearest_cache(variant.model_id, tokens)[0] is None
    first.set_cache_scope("session-a:verifier")
    assert first._prefix_cache().fetch_nearest_cache(first.model_id, tokens)[0] is None
    first.set_cache_scope("session-b:draft")
    assert first._prefix_cache().fetch_nearest_cache(first.model_id, tokens)[0] is None
    with pytest.raises(ValueError):
        first.set_cache_scope("  ")


def test_cache_aggregate_namespace_and_byte_bounds(fake_cache, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "_MLX_PREFIX_CACHE_MAX_NAMESPACES", 2)
    monkeypatch.setattr(agent, "_MLX_PREFIX_CACHE_MAX_TOTAL_BYTES", 7)
    generator = agent.MLXGenerator("fixture/model", prompt_cache_enabled=True, prompt_cache_max_bytes=100)
    generator.set_cache_scope("one")
    one = generator._prefix_cache()
    one.insert_cache(generator.model_id, [1], [{"nbytes": 4}], cache_type="system")
    generator.set_cache_scope("two")
    two = generator._prefix_cache()
    two.insert_cache(generator.model_id, [2], [{"nbytes": 4}], cache_type="system")
    agent._prune_mlx_prefix_caches()
    assert agent.mlx_prompt_cache_stats()["nbytes"] <= 7
    assert generator._prefix_cache() is two
    generator.set_cache_scope("three")
    generator._prefix_cache()
    assert agent.mlx_prompt_cache_stats()["cache_count"] <= 2
    generator.set_cache_scope("one")
    assert generator._prefix_cache() is not one


def test_http_backend_reports_unknown_tokenization_and_context() -> None:
    generator = agent.OpenAICompatibleGenerator("fixture", base_url="http://127.0.0.1:1")
    assert generator.context_window_tokens is None
    assert generator.count_prompt_tokens([{"role": "user", "content": "hi"}]) is None
    generator.set_cache_scope("session-a:draft")


def test_stream_receipt_preserves_exact_prompt_accounting_and_unknown_rates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = types.ModuleType("mlx.core")
    core.random = types.SimpleNamespace(seed=lambda _: None)  # type: ignore[attr-defined]
    mlx = types.ModuleType("mlx")
    mlx.core = core  # type: ignore[attr-defined]
    mlx_lm = types.ModuleType("mlx_lm")
    mlx_lm.generate = lambda *_args, **_kwargs: "unused"  # type: ignore[attr-defined]
    mlx_lm.stream_generate = lambda *_args, **_kwargs: iter([  # type: ignore[attr-defined]
        types.SimpleNamespace(text="answer", generation_tokens=1, from_draft=False),
    ])
    sampler = types.ModuleType("mlx_lm.sample_utils")
    sampler.make_sampler = lambda **_kwargs: None  # type: ignore[attr-defined]
    for name, module in (
        ("mlx", mlx), ("mlx.core", core), ("mlx_lm", mlx_lm), ("mlx_lm.sample_utils", sampler),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    generator = agent.MLXGenerator("fixture/model", use_stream_generate=True)
    generator._model = object()
    generator._tokenizer = _Tokenizer()
    messages = [{"role": "user", "content": "hello"}]
    assert generator._generate_on_mlx_thread(messages) == "answer"
    receipt = generator.last_generation_stats
    assert receipt["prompt_tokens"] == len(b"user:hello|assistant:")
    assert receipt["cached_prompt_tokens"] == 0
    assert receipt["uncached_prompt_tokens"] == receipt["prompt_tokens"]
    assert receipt["prompt_cache_status"] == "disabled"
    assert receipt["prompt_cache_hit"] is False
    assert receipt["generation_tps"] is None and receipt["prompt_tps"] is None
    assert receipt["time_to_first_token_ms"] is not None
    assert receipt["model_load_status"] == "already_loaded"


def test_stable_prefix_prefill_uses_deterministic_sampler_and_copied_cache(
    monkeypatch: pytest.MonkeyPatch, fake_cache,
) -> None:
    core = types.ModuleType("mlx.core")
    core.array = lambda tokens: tokens  # type: ignore[attr-defined]
    core.argmax = lambda logits, *, axis: (logits, axis)  # type: ignore[attr-defined]
    mlx = types.ModuleType("mlx")
    mlx.core = core  # type: ignore[attr-defined]
    generated: list[list[int]] = []

    def prefill(tokens: list[int], _model: Any, **kwargs: Any):
        assert kwargs["max_tokens"] == 0
        assert kwargs["sampler"]("logits") == ("logits", -1)
        generated.append(tokens)
        return iter(())

    generate_module = types.ModuleType("mlx_lm.generate")
    generate_module.generate_step = prefill  # type: ignore[attr-defined]
    cache_module = sys.modules["mlx_lm.models.cache"]
    cache_module.make_prompt_cache = lambda *_args, **_kwargs: [{"nbytes": 4, "state": [1]}]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx", mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    monkeypatch.setitem(sys.modules, "mlx_lm.generate", generate_module)
    generator = agent.MLXGenerator(
        "fixture/model", prompt_cache_enabled=True, prompt_cache_min_prefix_tokens=4,
    )
    generator._model = object()
    generator._tokenizer = _Tokenizer()
    messages = [
        {"role": "system", "content": "Rules"},
        {"role": "user", "content": "Stable context\n\nFirst question"},
    ]
    prompt = generator._tokenizer.apply_chat_template(messages, tokenize=False)
    tokens = generator._tokenizer.apply_chat_template(messages, tokenize=True)
    first, rest, cached, status = generator._prepare_prompt_cache(messages, prompt, tokens)
    assert generated and status == "prepared_this_request"
    assert cached + len(rest) == len(tokens)
    assert cached > 0 and len(rest) > 0
    first[0]["state"].append(99)
    second, second_rest, second_cached, second_status = generator._prepare_prompt_cache(messages, prompt, tokens)
    assert second_status == "reused_saved_prefix"
    assert second_cached == cached
    assert second_cached + len(second_rest) == len(tokens)
    assert second[0]["state"] == [1]
    assert len(generated) == 1

    # Exercise the public generation receipt across a cold preparation and a
    # later request; only the latter is an inter-request cache hit.
    agent.reset_mlx_prompt_caches()
    fake_mlx = types.ModuleType("mlx_lm")
    fake_mlx.generate = lambda *_args, **_kwargs: "unused"  # type: ignore[attr-defined]
    fake_mlx.stream_generate = lambda *_args, **_kwargs: iter([  # type: ignore[attr-defined]
        types.SimpleNamespace(text="answer", generation_tokens=1, from_draft=False),
    ])
    sampler = types.ModuleType("mlx_lm.sample_utils")
    sampler.make_sampler = lambda **_kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx_lm", fake_mlx)
    monkeypatch.setitem(sys.modules, "mlx_lm.sample_utils", sampler)
    assert generator._generate_on_mlx_thread(messages) == "answer"
    cold = dict(generator.last_generation_stats)
    assert cold["prompt_cache_status"] == "prepared_this_request"
    assert cold["prompt_cache_hit"] is False
    assert cold["cached_prompt_tokens"] + cold["uncached_prompt_tokens"] == cold["prompt_tokens"]
    assert generator._generate_on_mlx_thread(messages) == "answer"
    reused = generator.last_generation_stats
    assert reused["prompt_cache_status"] == "reused_saved_prefix"
    assert reused["prompt_cache_hit"] is True
    assert reused["cached_prompt_tokens"] + reused["uncached_prompt_tokens"] == reused["prompt_tokens"]
    assert reused["cached_prompt_tokens"] == cold["cached_prompt_tokens"]
