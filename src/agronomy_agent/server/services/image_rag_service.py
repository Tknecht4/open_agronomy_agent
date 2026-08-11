from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def image_quality_payload(
    *,
    attachments: list[dict[str, Any]],
    question: str,
    crop: str | None,
    region: str | None,
    observation_adapter: Any,
    similar_examples: list[dict[str, Any]] | None = None,
    image_retrieval_eval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    flags = ["image_processor_not_configured"]
    if not attachments:
        flags.append("no_image_attachment")
    attachment_summaries: list[dict[str, Any]] = []
    for attachment in attachments:
        content_type = str(attachment.get("content_type") or "")
        modality = str(attachment.get("modality") or "")
        is_image_like = content_type.startswith("image/") or modality in {"image", "multimodal"}
        if not is_image_like:
            flags.append("non_image_attachment")
        if int(attachment.get("size_bytes") or 0) == 0:
            flags.append("empty_attachment")
        image_metadata = (attachment.get("metadata") or {}).get("image") or {}
        flags.extend(str(flag) for flag in image_metadata.get("quality_flags", []) or [])
        attachment_summaries.append(
            {
                "attachment_id": attachment["id"],
                "filename": attachment["filename"],
                "content_type": content_type,
                "modality": modality,
                "size_bytes": attachment.get("size_bytes", 0),
                "parse_status": attachment.get("parse_status"),
                "metadata": attachment.get("metadata", {}),
                "image_like": is_image_like,
                "image": image_metadata,
            },
        )
    flags = sorted(set(flags))
    adapter_payload = observation_adapter.observe(
        {
            "question": question,
            "crop": crop,
            "region": region,
            "attachment_count": len(attachments),
            "attachment_metadata": attachment_summaries,
            "image_quality_flags": flags,
            "similar_examples": similar_examples or [],
            "guardrails": {"not_a_diagnosis": True, "no_treatment_or_product_recommendation": True},
        },
    )
    cannot_determine = set(adapter_payload["cannot_determine"])
    cannot_determine.update({"diagnosis", "treatment"})
    return {
        "question": question,
        "crop": crop,
        "region": region,
        "attachment_count": len(attachments),
        "attachment_metadata": attachment_summaries,
        "visible_observations": adapter_payload["visible_observations"],
        "similar_examples": similar_examples or [],
        "image_retrieval_eval": image_retrieval_eval
        or {
            "metric_set": "phase4.image_embedding_retrieval.v1",
            "query_count": 0,
            "candidate_count": 0,
            "recall_at_k": 0.0,
            "top_k": 0,
            "ood_abstention_rate": 1.0,
            "status": "not_run",
        },
        "image_quality_flags": flags,
        "not_a_diagnosis": True,
        "cannot_determine": sorted(cannot_determine),
        "ood_gate": adapter_payload["ood_gate"],
        "adapter": adapter_payload.get("adapter", {"backend": "unknown"}),
        "uncertainty": "Image observations are research-preview signals only and cannot establish diagnosis, treatment, product, or rate decisions.",
    }


def image_embedding_search(
    *,
    query_attachments: list[dict[str, Any]],
    candidate_embeddings: list[dict[str, Any]],
    crop: str | None,
    region: str | None,
    limit: int = 5,
) -> dict[str, Any]:
    query_images = [
        attachment
        for attachment in query_attachments
        if str(attachment.get("content_type") or "").startswith("image/") or attachment.get("modality") in {"image", "multimodal"}
    ]
    query_vectors = [
        (((attachment.get("metadata") or {}).get("image") or {}).get("fingerprint") or {}).get("vector")
        for attachment in query_images
    ]
    query_vectors = [item for item in query_vectors if isinstance(item, list) and item]
    if not query_vectors:
        return {
            "examples": [],
            "eval_summary": {
                "metric_set": "phase4.image_embedding_retrieval.v1",
                "query_count": len(query_images),
                "candidate_count": 0,
                "recall_at_k": 0.0,
                "top_k": limit,
                "ood_abstention_rate": 1.0,
                "status": "no_query_embedding",
            },
        }
    query_ids = {attachment["id"] for attachment in query_images}
    crop_filter = crop.strip().lower() if crop else None
    region_filter = region.strip().lower() if region else None
    examples: list[dict[str, Any]] = []
    for embedding in candidate_embeddings:
        attachment_id = embedding.get("attachment_id")
        if attachment_id in query_ids:
            continue
        metadata = embedding.get("metadata") or {}
        filters = metadata.get("filters") or {}
        if crop_filter and filters.get("crop") != crop_filter:
            continue
        if region_filter and filters.get("region") != region_filter:
            continue
        vector = embedding.get("vector") or []
        score = max(_vector_similarity(query_vector, vector) for query_vector in query_vectors)
        image = (embedding.get("attachment_metadata") or {}).get("image") or {}
        examples.append(
            {
                "attachment_id": attachment_id,
                "filename": embedding.get("filename"),
                "content_type": embedding.get("content_type"),
                "score": score,
                "encoder": embedding.get("encoder_name"),
                "encoder_version": embedding.get("encoder_version"),
                "embedding_id": embedding.get("id"),
                "metadata_filters": filters,
                "image": {
                    "width": image.get("width"),
                    "height": image.get("height"),
                    "quality_flags": image.get("quality_flags", []),
                },
            },
        )
    examples = sorted(examples, key=lambda item: item["score"], reverse=True)[:limit]
    relevant = [item for item in examples if item["score"] >= 0.8]
    return {
        "examples": examples,
        "eval_summary": {
            "metric_set": "phase4.image_embedding_retrieval.v1",
            "query_count": len(query_vectors),
            "candidate_count": len([item for item in candidate_embeddings if item.get("attachment_id") not in query_ids]),
            "recall_at_k": round(len(relevant) / max(1, len(query_vectors)), 4),
            "top_k": limit,
            "top_score": examples[0]["score"] if examples else 0.0,
            "ood_abstention_rate": 0.0 if examples else 1.0,
            "status": "ok" if examples else "no_matching_candidates",
        },
    }


def run_image_observation_job(
    *,
    store: Any,
    observation_adapter: Any,
    job_id: str,
    worker_name: str = "local_worker",
) -> dict[str, Any]:
    job = store.get_phase4_image_job(job_id)
    if not job:
        raise ValueError(f"image job not found: {job_id}")
    store.update_phase4_image_job(
        job_id=job_id,
        status="running",
        result={**job.get("result", {}), "worker": worker_name},
        started_at=_now_iso(),
    )
    try:
        workspace = store.get_phase4_workspace(job["workspace_id"])
        if not workspace:
            raise ValueError("workspace not found")
        attachments = []
        for attachment_id in job.get("attachment_ids", []):
            attachment = store.get_phase4_attachment(str(attachment_id))
            if not attachment or attachment["workspace_id"] != workspace["id"]:
                raise ValueError(f"attachment not found: {attachment_id}")
            attachments.append(attachment)
        image_search = image_embedding_search(
            query_attachments=attachments,
            candidate_embeddings=store.list_phase4_image_embeddings(workspace["id"]),
            crop=job.get("crop"),
            region=job.get("region"),
        )
        payload = image_quality_payload(
            attachments=attachments,
            question=job["question"],
            crop=job.get("crop"),
            region=job.get("region"),
            observation_adapter=observation_adapter,
            similar_examples=image_search["examples"],
            image_retrieval_eval=image_search["eval_summary"],
        )
        if job.get("thread_id"):
            thread = store.get_phase4_thread(job["thread_id"])
            if not thread or thread["workspace_id"] != workspace["id"]:
                raise ValueError("thread not found")
            store.append_phase4_trace_event(thread=thread, event_type="image_observation", actor="worker", payload=payload)
    except Exception as exc:
        return store.update_phase4_image_job(
            job_id=job_id,
            status="failed",
            result={"worker": worker_name, "unhandled_error": exc.__class__.__name__},
            error_message=str(exc),
            finished_at=_now_iso(),
        ) or {}
    return store.update_phase4_image_job(
        job_id=job_id,
        status="completed",
        result={"worker": worker_name, "image_observation": payload},
        error_message=None,
        finished_at=_now_iso(),
    ) or {}


def run_queued_image_jobs(
    *,
    store: Any,
    observation_adapter: Any,
    limit: int = 1,
    worker_name: str = "local_worker",
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be > 0")
    jobs = store.list_phase4_queued_image_jobs(limit=limit)
    return run_image_job_ids(
        store=store,
        observation_adapter=observation_adapter,
        job_ids=[job["id"] for job in jobs],
        requested_limit=limit,
        worker_name=worker_name,
        queue_name="image",
    )


def run_image_job_ids(
    *,
    store: Any,
    observation_adapter: Any,
    job_ids: list[str],
    requested_limit: int,
    worker_name: str = "local_worker",
    queue_name: str = "image",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for job_id in job_ids:
        try:
            result = run_image_observation_job(
                store=store,
                observation_adapter=observation_adapter,
                job_id=job_id,
                worker_name=worker_name,
            )
        except Exception as exc:
            result = store.update_phase4_image_job(
                job_id=job_id,
                status="failed",
                result={"worker": worker_name, "unhandled_error": exc.__class__.__name__},
                error_message=str(exc),
                finished_at=_now_iso(),
            ) or {"id": job_id, "status": "failed"}
        results.append(result)
    return {
        "queue": queue_name,
        "worker": worker_name,
        "requested_limit": requested_limit,
        "processed": len(results),
        "completed": sum(1 for item in results if item.get("status") == "completed"),
        "failed": sum(1 for item in results if item.get("status") == "failed"),
        "job_ids": [item.get("id") for item in results],
    }


def _vector_similarity(left: list[Any], right: list[Any]) -> float:
    left_numbers = [float(value) for value in left if isinstance(value, (int, float))]
    right_numbers = [float(value) for value in right if isinstance(value, (int, float))]
    if not left_numbers or len(left_numbers) != len(right_numbers):
        return 0.0
    distance = sum((a - b) ** 2 for a, b in zip(left_numbers, right_numbers)) ** 0.5
    scale = (sum(a**2 for a in left_numbers) ** 0.5) + (sum(b**2 for b in right_numbers) ** 0.5) + 1.0
    return round(max(0.0, 1.0 - distance / scale), 4)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
