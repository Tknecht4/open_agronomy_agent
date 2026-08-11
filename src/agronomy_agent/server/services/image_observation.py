from __future__ import annotations

import json
from typing import Any, Callable
from urllib.request import Request, urlopen

from agronomy_agent.server.settings import ServerSettings


ImageObservationInput = dict[str, Any]


class LocalImageObservationAdapter:
    method = "local_quality_and_metadata_stub"

    def observe(self, payload: ImageObservationInput) -> dict[str, Any]:
        attachment_metadata = list(payload.get("attachment_metadata") or [])
        image_quality_flags = list(payload.get("image_quality_flags") or [])
        similar_examples = list(payload.get("similar_examples") or [])
        crop = payload.get("crop")
        region = payload.get("region")
        observations: list[dict[str, Any]] = []
        cannot_determine = {"growth_stage", "distribution_pattern", "diagnosis", "treatment"}
        reasons: list[str] = []

        if not attachment_metadata:
            reasons.append("no_image_attachment")
            cannot_determine.update({"crop", "visual_symptoms"})
        if not crop:
            cannot_determine.add("crop")
        if not region:
            cannot_determine.add("region")
        if any(
            flag in image_quality_flags
            for flag in ["low_resolution_image", "dimensions_unknown", "empty_attachment", "non_image_attachment"]
        ):
            reasons.append("image_quality_too_low_for_observation")
            cannot_determine.add("visual_symptoms")

        for attachment in attachment_metadata:
            image = attachment.get("image") or {}
            width = image.get("width")
            height = image.get("height")
            if attachment.get("image_like") and width and height:
                observations.append(
                    {
                        "type": "image_asset",
                        "text": f"Image asset received as {attachment.get('content_type')} with dimensions {width}x{height}.",
                        "evidence": {"attachment_id": attachment.get("attachment_id"), "width": width, "height": height},
                        "confidence": "metadata_only",
                    },
                )
            if "low_resolution_image" in (image.get("quality_flags") or []):
                observations.append(
                    {
                        "type": "quality_gate",
                        "text": "Image is below the local resolution threshold for reliable symptom observation.",
                        "evidence": {"attachment_id": attachment.get("attachment_id"), "quality_flags": image.get("quality_flags", [])},
                        "confidence": "high",
                    },
                )

        if similar_examples:
            observations.append(
                {
                    "type": "retrieval_context",
                    "text": "Similar workspace images were found using local fingerprint metadata filters.",
                    "evidence": {"top_attachment_id": similar_examples[0]["attachment_id"], "score": similar_examples[0]["score"]},
                    "confidence": "local_stub",
                },
            )

        abstain = bool(reasons)
        return {
            "visible_observations": observations,
            "cannot_determine": sorted(cannot_determine),
            "ood_gate": {
                "abstain": abstain,
                "reasons": sorted(set(reasons)),
                "method": self.method,
                "requires_expert_review": abstain,
            },
            "adapter": {"backend": "local", "method": self.method},
        }


class HttpVlmObservationAdapter:
    method = "http_vlm_observation_adapter"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.endpoint = endpoint.strip()
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._opener = opener
        if not self.endpoint:
            raise ValueError("VLM adapter endpoint is required")
        if timeout_seconds <= 0:
            raise ValueError("VLM adapter timeout must be positive")

    def observe(self, payload: ImageObservationInput) -> dict[str, Any]:
        request_payload = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        request = Request(self.endpoint, data=request_payload, headers=headers, method="POST")
        response = self._opener(request, timeout=self.timeout_seconds)
        close = getattr(response, "close", None)
        try:
            body = response.read()
        finally:
            if callable(close):
                close()
        raw = json.loads(body.decode("utf-8"))
        return normalize_image_observation_payload(raw, backend="http", method=self.method)


def build_image_observation_adapter(settings: ServerSettings) -> LocalImageObservationAdapter | HttpVlmObservationAdapter:
    if settings.vlm_observation_backend == "http":
        if not settings.vlm_observation_endpoint:
            raise ValueError("AGRONOMY_AGENT_VLM_OBSERVATION_ENDPOINT is required when VLM observation backend is http")
        return HttpVlmObservationAdapter(
            endpoint=settings.vlm_observation_endpoint,
            api_key=settings.vlm_observation_api_key,
            timeout_seconds=settings.vlm_observation_timeout_seconds,
        )
    return LocalImageObservationAdapter()


def normalize_image_observation_payload(raw: dict[str, Any], *, backend: str, method: str) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for item in raw.get("visible_observations") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        observations.append(
            {
                "type": str(item.get("type") or "visual_observation")[:64],
                "text": text[:600],
                "evidence": item.get("evidence") if isinstance(item.get("evidence"), dict) else {},
                "confidence": item.get("confidence", "adapter_reported"),
            },
        )
    cannot_determine = {str(item) for item in raw.get("cannot_determine") or [] if str(item).strip()}
    cannot_determine.update({"diagnosis", "treatment"})
    ood_gate_raw = raw.get("ood_gate") if isinstance(raw.get("ood_gate"), dict) else {}
    reasons = [str(item) for item in ood_gate_raw.get("reasons", []) if str(item).strip()]
    abstain = bool(ood_gate_raw.get("abstain", False))
    return {
        "visible_observations": observations[:8],
        "cannot_determine": sorted(cannot_determine),
        "ood_gate": {
            "abstain": abstain,
            "reasons": sorted(set(reasons)),
            "method": str(ood_gate_raw.get("method") or method),
            "requires_expert_review": bool(ood_gate_raw.get("requires_expert_review", abstain)),
        },
        "adapter": {"backend": backend, "method": method},
    }
