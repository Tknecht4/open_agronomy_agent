"""Optional LFM2.5 zero-shot prompt-routing experiment.

This module is deliberately outside the live routing path.  It lazy-loads the
third-party model, defaults to a pinned and already-cached snapshot, and can
only suggest a primary ``question_type``.  It never selects safety tools, risk
levels, namespaces, or answer policy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Sequence


MODEL_ID = "LiquidAI/LFM2.5-Encoder-350M-Prompt-Router"
MODEL_REVISION = "35ca4a0469f180f1cf05a630df8842fa17ac18e3"
ONTOLOGY_VERSION = "open_agronomy_agent.question_type.concise.v2"

# This is the frozen v2 evaluation ontology, not the complete live contract.
# The live router also emits ``integrated_management``; adding that lane would
# change every softmax score, so it is deferred to a separately frozen v3.
# Rich descriptions document the meaning of each evaluated local label.
ROUTE_DESCRIPTIONS: Mapping[str, str] = {
    "conceptual": (
        "General agronomy explanation or concept that is not primarily a field "
        "measurement, management operation, diagnosis, regulated product, "
        "fertility, soil-water, seed-treatment, or regional-context decision."
    ),
    "crop_management": (
        "Crop establishment, rotation, seeding, harvest, storage, grazing, "
        "timing, machinery, or other non-pesticide crop management decision."
    ),
    "exam_review": (
        "Study, quiz, flash-card, or examination-review request about agronomy."
    ),
    "fertility_diagnostic": (
        "Diagnose a possible nutrient, pH, manure-credit, or soil-test problem "
        "without enough calibrated evidence to prescribe a numeric application rate."
    ),
    "fertility_rate": (
        "Calculate, verify, or recommend a fertilizer, lime, manure, or nutrient "
        "application rate using measurements, units, credits, and local calibration."
    ),
    "field_data": (
        "Read, compare, calculate from, map, record, or retrieve field-specific "
        "observations, samples, measurements, boundaries, history, or sensor data."
    ),
    "plant_health": (
        "Diagnose or manage crop symptoms, disease, insects, weeds, injury, or "
        "other plant-health conditions without making a product-label decision."
    ),
    "product_label": (
        "Choose, mix, rate, time, or check legality and safety of a named or "
        "implied pesticide, herbicide, fungicide, insecticide, or regulated product."
    ),
    "regional_context": (
        "Ask about a named region's climate, soils, land capability, statistics, "
        "maps, public datasets, or historical environmental context."
    ),
    "seed_treatment": (
        "Choose, assess, or safely use a seed treatment, inoculant, coating, "
        "treated seed, or seed-applied pesticide."
    ),
    "soil_water": (
        "Assess soil moisture, drainage, irrigation, salinity, sodicity, erosion, "
        "compaction, trafficability, runoff, or other soil-water condition."
    ),
}

# Liquid's published example uses short free-text lanes ("Coding", "Sales"),
# not full policy definitions.  The v1 long-definition formulation was retired
# after a frozen 31-case development run (3/31 raw top-1).  These concise v2
# lanes were then frozen before the independent-authoring suite.
ROUTE_LANES: Mapping[str, str] = {
    "conceptual": "General agronomy explanation",
    "crop_management": "Crop management operation",
    "exam_review": "Agronomy study or exam review",
    "fertility_diagnostic": "Nutrient or soil fertility diagnosis",
    "fertility_rate": "Fertilizer, lime, or manure rate calculation",
    "field_data": "Field data, records, maps, or measurements",
    "plant_health": "Crop disease, insect, weed, or injury diagnosis",
    "product_label": "Pesticide label, spray rate, or tank mix",
    "regional_context": "Regional soil, climate, land, or statistics",
    "seed_treatment": "Seed treatment or treated seed",
    "soil_water": "Soil moisture, drainage, irrigation, or erosion",
}

PROTECTED_CURRENT_ROUTES = frozenset(
    {"fertility_diagnostic", "fertility_rate", "product_label", "seed_treatment"}
)


@dataclass(frozen=True)
class LfmPromptRouterConfig:
    """Configuration for a fail-closed, portable prompt-router instance."""

    model_id: str = MODEL_ID
    revision: str = MODEL_REVISION
    model_path: str | None = None
    modules_cache_dir: str | None = None
    device: str = "auto"
    dtype: str = "auto"
    local_files_only: bool = True
    trust_remote_code: bool = True
    top_score_threshold: float = 0.40
    margin_threshold: float = 0.08

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", self.revision):
            raise ValueError("revision must be a full 40-character lowercase commit SHA")
        if not self.local_files_only:
            raise ValueError(
                "runtime network access is disabled; prepare a pinned snapshot separately"
            )
        if not (0.0 <= self.top_score_threshold <= 1.0):
            raise ValueError("top_score_threshold must be between 0 and 1")
        if not (0.0 <= self.margin_threshold <= 1.0):
            raise ValueError("margin_threshold must be between 0 and 1")


@dataclass(frozen=True)
class RouteScore:
    route: str
    description: str
    score: float


@dataclass(frozen=True)
class LfmRouteResult:
    available: bool
    selected_route: str | None
    scores: tuple[RouteScore, ...] = field(default_factory=tuple)
    abstained: bool = True
    abstain_reason: str | None = None
    top_score: float | None = None
    margin: float | None = None
    inference_ms: float | None = None
    load_ms: float | None = None
    device: str | None = None
    dtype: str | None = None
    model_id: str = MODEL_ID
    revision: str = MODEL_REVISION
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LfmPromptRouter:
    """Lazy, injected-testable wrapper around Liquid's routing head."""

    def __init__(
        self,
        config: LfmPromptRouterConfig | None = None,
        *,
        model: Any | None = None,
        tokenizer: Any | None = None,
        loader: Callable[[LfmPromptRouterConfig], tuple[Any, Any, str, str]]
        | None = None,
    ) -> None:
        self.config = config or LfmPromptRouterConfig()
        self._model = model
        self._tokenizer = tokenizer
        self._loader = loader or self._load_transformers
        self._device: str | None = "injected" if model is not None else None
        self._dtype: str | None = "injected" if model is not None else None
        self._load_ms: float | None = 0.0 if model is not None else None
        self._load_error: str | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    @staticmethod
    def route_options() -> tuple[str, ...]:
        return tuple(ROUTE_LANES.values())

    @staticmethod
    def _resolve_device_and_dtype(torch: Any, config: LfmPromptRouterConfig) -> tuple[str, Any, str]:
        if config.device == "auto":
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        else:
            device = config.device

        if config.dtype == "auto":
            # The pinned custom route() implementation creates its text/category
            # pooling tensors as float32.  Loading the model as float16 therefore
            # makes torch.bmm fail with mixed dtypes.
            dtype_name = "float32"
        else:
            dtype_name = config.dtype
        try:
            dtype = getattr(torch, dtype_name)
        except AttributeError as exc:
            raise ValueError(f"unsupported torch dtype: {dtype_name}") from exc
        return device, dtype, dtype_name

    @classmethod
    def _load_transformers(
        cls, config: LfmPromptRouterConfig
    ) -> tuple[Any, Any, str, str]:
        if not config.trust_remote_code:
            raise ValueError(
                "the Transformers backend requires pinned custom model code"
            )
        # Imports stay here so the default application has no torch/Transformers
        # dependency and importing agronomy_agent remains lightweight.
        import torch

        modules_cache = Path(
            config.modules_cache_dir
            or os.environ.get("AGRONOMY_LFM_MODULES_CACHE", "")
            or Path.cwd() / ".cache" / "lfm_transformers_modules"
        ).resolve()
        modules_cache.mkdir(parents=True, exist_ok=True)
        # Transformers reads this constant during module import.  Set the
        # environment first, then also update the imported module so the adapter
        # remains independent of an ambient HF_HOME from another project.
        os.environ["HF_MODULES_CACHE"] = str(modules_cache)
        from transformers import AutoModel, AutoTokenizer
        import transformers.dynamic_module_utils as dynamic_module_utils

        dynamic_module_utils.HF_MODULES_CACHE = str(modules_cache)

        device, dtype, dtype_name = cls._resolve_device_and_dtype(torch, config)
        source = config.model_path or config.model_id
        remote_kwargs: dict[str, Any] = {}
        if config.model_path is None:
            remote_kwargs.update(
                {
                    "revision": config.revision,
                    "code_revision": config.revision,
                }
            )
        common = {
            "local_files_only": True,
            "trust_remote_code": True,
            **remote_kwargs,
        }
        tokenizer = AutoTokenizer.from_pretrained(source, **common)
        model = AutoModel.from_pretrained(source, dtype=dtype, **common)
        model.eval()
        model.to(device)
        return model, tokenizer, device, dtype_name

    def load(self) -> bool:
        if self.loaded:
            return True
        if self._load_error is not None:
            return False
        started = time.perf_counter()
        try:
            model, tokenizer, device, dtype = self._loader(self.config)
            self._model = model
            self._tokenizer = tokenizer
            self._device = device
            self._dtype = dtype
            self._load_ms = (time.perf_counter() - started) * 1000.0
            return True
        except Exception as exc:  # fail closed across optional backends
            self._load_ms = (time.perf_counter() - started) * 1000.0
            self._load_error = f"{type(exc).__name__}: {exc}"
            return False

    @staticmethod
    def _normalize_raw_scores(raw: Any) -> tuple[RouteScore, ...]:
        if isinstance(raw, Mapping):
            candidates: Sequence[Any] = [
                {"route": key, "score": value} for key, value in raw.items()
            ]
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            candidates = raw
        else:
            raise TypeError(f"unexpected route result type: {type(raw).__name__}")

        normalized: list[RouteScore] = []
        option_to_route = {option: route for route, option in ROUTE_LANES.items()}
        for item in candidates:
            if isinstance(item, Mapping):
                raw_route = item.get("route", item.get("label", item.get("category")))
                raw_score = item.get("score", item.get("probability"))
            elif isinstance(item, Sequence) and len(item) >= 2:
                raw_route, raw_score = item[0], item[1]
            else:
                continue
            route_text = str(raw_route)
            route = option_to_route.get(route_text, route_text.split(":", 1)[0].strip())
            if route not in ROUTE_DESCRIPTIONS:
                continue
            normalized.append(
                RouteScore(
                    route=route,
                    description=ROUTE_DESCRIPTIONS[route],
                    score=float(raw_score),
                )
            )
        if not normalized:
            raise ValueError("model returned no recognized route scores")
        return tuple(sorted(normalized, key=lambda item: item.score, reverse=True))

    def route(self, prompt: str) -> LfmRouteResult:
        if not prompt.strip():
            return LfmRouteResult(
                available=False,
                selected_route=None,
                abstain_reason="empty_prompt",
                model_id=self.config.model_id,
                revision=self.config.revision,
            )
        if not self.load():
            return LfmRouteResult(
                available=False,
                selected_route=None,
                abstain_reason="model_unavailable",
                load_ms=self._load_ms,
                model_id=self.config.model_id,
                revision=self.config.revision,
                error=self._load_error,
            )

        started = time.perf_counter()
        try:
            raw = self._model.route(
                prompt,
                list(self.route_options()),
                tokenizer=self._tokenizer,
            )
            scores = self._normalize_raw_scores(raw)
            inference_ms = (time.perf_counter() - started) * 1000.0
            top_score = scores[0].score
            margin = top_score - scores[1].score if len(scores) > 1 else top_score
            reason = None
            if top_score < self.config.top_score_threshold:
                reason = "top_score_below_threshold"
            elif margin < self.config.margin_threshold:
                reason = "margin_below_threshold"
            abstained = reason is not None
            return LfmRouteResult(
                available=True,
                selected_route=None if abstained else scores[0].route,
                scores=scores,
                abstained=abstained,
                abstain_reason=reason,
                top_score=top_score,
                margin=margin,
                inference_ms=inference_ms,
                load_ms=self._load_ms,
                device=self._device,
                dtype=self._dtype,
                model_id=self.config.model_id,
                revision=self.config.revision,
            )
        except Exception as exc:
            return LfmRouteResult(
                available=False,
                selected_route=None,
                abstain_reason="inference_error",
                inference_ms=(time.perf_counter() - started) * 1000.0,
                load_ms=self._load_ms,
                device=self._device,
                dtype=self._dtype,
                model_id=self.config.model_id,
                revision=self.config.revision,
                error=f"{type(exc).__name__}: {exc}",
            )


def conservative_hybrid_route(
    current_route: str, lfm_result: LfmRouteResult
) -> tuple[str, str]:
    """Pre-registered hybrid policy.

    The encoder may repair only the deterministic router's generic conceptual
    fallback.  Existing safety-sensitive primary routes and all downstream
    route metadata remain untouched.
    """

    if current_route != "conceptual":
        reason = (
            "protected_current_route"
            if current_route in PROTECTED_CURRENT_ROUTES
            else "current_nonfallback_preserved"
        )
        return current_route, reason
    if not lfm_result.available or lfm_result.abstained or not lfm_result.selected_route:
        return current_route, "lfm_unavailable_or_abstained"
    if lfm_result.selected_route == "conceptual":
        return current_route, "lfm_agreed_with_fallback"
    return lfm_result.selected_route, "lfm_repaired_conceptual_fallback"
