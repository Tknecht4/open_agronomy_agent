"""Native-MLX implementation of the pinned LFM2.5 prompt router.

The module itself has no eager MLX import, so the default application and test
suite remain portable to non-Apple hosts.  MLX and mlx-lm are loaded only when
an operator explicitly constructs this shadow backend.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Callable

from agronomy_agent.lfm_prompt_router import (
    LfmPromptRouter,
    LfmPromptRouterConfig,
)

CRITICAL_FILE_SHA256 = {
    "config.json": "c814ae464727ff899bac53d9f522b853498088f27401e50cf657b02756725186",
    "model.safetensors": "9fab23eeb312d951bca8a0dfa4068ca4be4d55283a66c6fe5cbe9cf1e14e631d",
    "tokenizer.json": "3a63c54c318111dd49d589cc3a17b63a76067afe9af99439a3f408d1ae11ee86",
    "tokenizer_config.json": "ba91dd002005cdf48ada14d3406571d06adc50b141bb4284e390b0e4c8d8aa2c",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MlxLfmPromptRouter(LfmPromptRouter):
    """MLX/Metal backend with the same route-result contract as the control."""

    def __init__(
        self,
        config: LfmPromptRouterConfig | None = None,
        *,
        model: Any | None = None,
        tokenizer: Any | None = None,
        loader: Callable[[LfmPromptRouterConfig], tuple[Any, Any, str, str]]
        | None = None,
    ) -> None:
        resolved = config or LfmPromptRouterConfig(
            device="auto", dtype="float32", trust_remote_code=False
        )
        super().__init__(
            resolved,
            model=model,
            tokenizer=tokenizer,
            loader=loader or self._load_mlx,
        )

    @staticmethod
    def _load_mlx(
        config: LfmPromptRouterConfig,
    ) -> tuple[Any, Any, str, str]:
        if not config.model_path:
            raise ValueError(
                "MLX requires an explicit local path to the pinned prepared snapshot"
            )
        snapshot = Path(config.model_path).resolve()
        if snapshot.name != config.revision:
            raise ValueError(
                "MLX snapshot directory must be the exact pinned revision"
            )
        config_path = snapshot / "config.json"
        weights_path = snapshot / "model.safetensors"
        if not config_path.is_file() or not weights_path.is_file():
            raise FileNotFoundError(
                f"incomplete local LFM prompt-router snapshot: {snapshot}"
            )
        for relative_path, expected in CRITICAL_FILE_SHA256.items():
            actual = _sha256(snapshot / relative_path)
            if actual != expected:
                raise ValueError(
                    f"snapshot integrity failure for {relative_path}: {actual}"
                )

        # Lazy imports are essential: importing MLX initializes Metal, which is
        # inappropriate for the default deterministic router and unavailable on
        # non-Apple hosts.
        import mlx.core as mx
        import mlx.nn as nn
        from mlx_lm.models import lfm2 as mlx_lfm2
        from transformers import AutoTokenizer

        requested = config.device
        if requested in {"auto", "gpu", "mps"}:
            mx.set_default_device(mx.gpu)
            device_name = "mlx_gpu"
        elif requested == "cpu":
            mx.set_default_device(mx.cpu)
            device_name = "mlx_cpu"
        else:
            raise ValueError(f"unsupported MLX device: {requested}")
        if config.dtype not in {"auto", "float32"}:
            raise ValueError(
                "the parity backend intentionally preserves the released float32 weights"
            )

        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
        model_config = dict(raw_config)
        model_config["block_ff_dim"] = raw_config["intermediate_size"]
        args = mlx_lfm2.ModelArgs.from_dict(model_config)

        class BidirectionalShortConv(mlx_lfm2.ShortConv):
            def __call__(self, x, mask=None, cache=None):
                if cache is not None:
                    raise ValueError("bidirectional encoder does not support cache")
                projected = self.in_proj(x)
                gate_b, gate_c, values = mx.split(projected, 3, axis=-1)
                gated = gate_b * values
                if mask is not None:
                    gated = mx.where(mask[..., None], gated, 0)
                kernel = self.L_cache
                pad = kernel // 2
                padded = mx.pad(gated, [(0, 0), (pad, pad), (0, 0)])
                convolved = self.conv(padded)
                if convolved.shape[1] > gated.shape[1]:
                    convolved = convolved[:, : gated.shape[1], :]
                elif convolved.shape[1] < gated.shape[1]:
                    convolved = mx.pad(
                        convolved,
                        [
                            (0, 0),
                            (0, gated.shape[1] - convolved.shape[1]),
                            (0, 0),
                        ],
                    )
                return self.out_proj(gate_c * convolved)

        class BidirectionalLayer(mlx_lfm2.Lfm2DecoderLayer):
            def __init__(self, layer_args, layer_idx):
                super().__init__(layer_args, layer_idx)
                if not self.is_attention_layer:
                    self.conv = BidirectionalShortConv(layer_args, layer_idx)

            def __call__(self, x, mask=None, cache=None):
                if cache is not None:
                    raise ValueError("bidirectional encoder does not support cache")
                normalized = self.operator_norm(x)
                if self.is_attention_layer:
                    residual = self.self_attn(
                        normalized, mask=None, cache=None
                    )
                else:
                    residual = self.conv(normalized, mask=mask, cache=None)
                hidden = x + residual
                return hidden + self.feed_forward(self.ffn_norm(hidden))

        class BidirectionalBackbone(nn.Module):
            def __init__(self, model_args):
                super().__init__()
                self.embed_tokens = nn.Embedding(
                    model_args.vocab_size, model_args.hidden_size
                )
                self.layers = [
                    BidirectionalLayer(model_args, index)
                    for index in range(model_args.num_hidden_layers)
                ]
                self.embedding_norm = nn.RMSNorm(
                    model_args.hidden_size, eps=model_args.norm_eps
                )

            def __call__(self, input_ids, attention_mask=None):
                hidden = self.embed_tokens(input_ids)
                for layer in self.layers:
                    hidden = layer(
                        hidden,
                        mask=attention_mask
                        if not layer.is_attention_layer
                        else None,
                    )
                return self.embedding_norm(hidden)

        class MlxSequenceRouter(nn.Module):
            def __init__(self, model_args, projection_dim):
                super().__init__()
                self.lfm2 = BidirectionalBackbone(model_args)
                self.tok_proj = nn.Linear(
                    model_args.hidden_size, projection_dim, bias=True
                )
                self.rule_proj = nn.Linear(
                    model_args.hidden_size, projection_dim, bias=True
                )
                self.score_bias = mx.array(0.0, dtype=mx.float32)
                self.logit_scale = mx.array(1.0, dtype=mx.float32)

            @staticmethod
            def _prefix(routes):
                body = (
                    "\n".join(f"- {route}" for route in routes)
                    if routes
                    else "- (none)"
                )
                return f"Categories:\n{body}\n\nText:\n"

            @staticmethod
            def _category_ranges(routes):
                ranges = []
                position = len("Categories:\n")
                for route in routes:
                    start = position + 2
                    end = start + len(route)
                    ranges.append((start, end))
                    position = end + 1
                return ranges

            @staticmethod
            def _normalize(values):
                denominator = mx.sqrt(
                    mx.sum(values * values, axis=-1, keepdims=True)
                )
                return values / mx.maximum(denominator, 1e-12)

            def route(self, text, routes, tokenizer, threshold=None):
                prefix = self._prefix(routes)
                full_text = prefix + text
                encoded = tokenizer(full_text, return_offsets_mapping=True)
                offsets = encoded["offset_mapping"]
                input_ids = mx.array([encoded["input_ids"]], dtype=mx.int32)
                attention = encoded.get("attention_mask")
                attention_mask = (
                    mx.array([attention], dtype=mx.bool_)
                    if attention is not None
                    else None
                )
                hidden = self.lfm2(input_ids, attention_mask=attention_mask)

                text_start = len(prefix)
                text_indices = [
                    index
                    for index, (start, end) in enumerate(offsets)
                    if end > text_start and start != end
                ]
                if text_indices:
                    text_hidden = mx.take(
                        hidden, mx.array(text_indices), axis=1
                    )
                    text_rep = mx.mean(text_hidden, axis=1)
                else:
                    text_rep = mx.zeros(
                        (1, hidden.shape[-1]), dtype=hidden.dtype
                    )

                category_reps = []
                for start, end in self._category_ranges(routes):
                    indices = [
                        index
                        for index, (token_start, token_end) in enumerate(offsets)
                        if token_start < end
                        and token_end > start
                        and token_start != token_end
                    ]
                    if indices:
                        category_hidden = mx.take(
                            hidden, mx.array(indices), axis=1
                        )
                        category_reps.append(
                            mx.mean(category_hidden, axis=1)[0]
                        )
                    else:
                        category_reps.append(
                            mx.zeros((hidden.shape[-1],), dtype=hidden.dtype)
                        )
                categories = mx.stack(category_reps, axis=0)[None, :, :]

                query = self._normalize(self.tok_proj(text_rep))
                category_vectors = self._normalize(
                    self.rule_proj(categories)
                )
                scale = mx.minimum(mx.exp(self.logit_scale), 30.0)
                logits = (
                    mx.einsum("bd,brd->br", query, category_vectors) * scale
                    + self.score_bias
                )
                probabilities = mx.softmax(logits, axis=-1)[0]
                mx.eval(probabilities)
                results = [
                    {"route": route, "score": float(probability)}
                    for route, probability in zip(
                        routes, probabilities.tolist()
                    )
                    if threshold is None or float(probability) >= threshold
                ]
                return sorted(
                    results, key=lambda item: item["score"], reverse=True
                )

        model = MlxSequenceRouter(args, raw_config.get("rule_proj_dim", 256))
        weights = mx.load(str(weights_path))
        sanitized = {}
        for name, value in weights.items():
            if name.endswith(".conv.conv.weight") and value.shape[1] == 1:
                value = value.transpose(0, 2, 1)
            sanitized[name] = value
        model.load_weights(list(sanitized.items()), strict=True)
        mx.eval(model.parameters())

        tokenizer = AutoTokenizer.from_pretrained(
            str(snapshot),
            local_files_only=True,
            trust_remote_code=False,
        )
        return model, tokenizer, device_name, "float32"
