FROM node:20-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/public ./public
COPY frontend/src ./src
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    AGRONOMY_AGENT_DB_PATH=/state/db/open-agronomy.sqlite3 \
    AGRONOMY_AGENT_ARTIFACT_ROOT=/state/artifacts \
    AGRONOMY_AGENT_STATIC_DIR=/app/frontend/dist \
    AGRONOMY_AGENT_MODEL_CONFIG=configs/model_gemma4_e2b_interface_v1.yaml \
    AGRONOMY_AGENT_MODEL_BACKEND=mlx_http \
    AGRONOMY_AGENT_MODEL_REQUEST_ID=default_model \
    AGRONOMY_AGENT_MODEL_IDENTITY_RECEIPT=/model-host/model-host.identity.json \
    AGRONOMY_AGENT_MODEL_IDENTITY_REQUIRED=true \
    AGRONOMY_AGENT_MODEL_TIMEOUT_SECONDS=240 \
    AGRONOMY_AGENT_ALLOW_LOCAL_DEV_AUTH=true \
    AGRONOMY_AGENT_DB_BACKEND=sqlite \
    AGRONOMY_AGENT_OBJECT_STORE_BACKEND=local \
    AGRONOMY_AGENT_JOB_QUEUE_BACKEND=local \
    AGRONOMY_AGENT_RATE_LIMIT_BACKEND=memory \
    AGRONOMY_AGENT_GEO_CACHE_DIR=/state/cache/geo \
    AGRONOMY_AGENT_AGNO_INDEX_CACHE_DIR=/state/cache/agno_lexical_index \
    AGRONOMY_AGENT_TOOL_CACHE_ROOT=/state/cache/public_tools

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 agronomy \
    && useradd --uid 10001 --gid agronomy --home-dir /app --shell /usr/sbin/nologin agronomy

COPY requirements-container.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements-container.txt \
    && pip install --no-cache-dir --no-deps .

COPY configs ./configs
COPY plans ./plans
COPY data/seed ./data/seed
COPY data/manifests ./data/manifests
COPY data/eval ./data/eval
COPY data/evals/canadian_applied_guidance_admission_eval_contract_20260726.json ./data/evals/canadian_applied_guidance_admission_eval_contract_20260726.json
COPY data/snapshots ./data/snapshots
COPY data/derived/rag ./data/derived/rag
COPY data/derived/geo_cache ./data/derived/geo_cache
COPY data/derived/geo_layers ./data/derived/geo_layers
COPY docs/canadian_corpus_v8_coverage_20260720.md \
     docs/canadian_agronomy_corpus_promotion_audit_v8_20260720.json \
     docs/canadian_agronomy_corpus_promotion_audit_v8_20260720.md \
     docs/canadian_v8_promotion_full_path_gate.md \
     docs/canadian_crop_health_indices_v7_direct_semantic_review_20260719.json \
     docs/canadian_crop_health_indices_v7_direct_semantic_review_20260719.md \
     docs/canadian_conference_transfer_gate_20260720.md \
     docs/canadian_conference_source_validation_v1_rc8_20260721.json \
     docs/canadian_conference_source_validation_v1_rc8_20260721.md \
     docs/canadian_ab_nutrient_planning_v6_direct_semantic_review_20260719.json \
     docs/canadian_ab_nutrient_planning_v6_direct_semantic_review_20260719.md \
     docs/canadian_geospatial_sources_validation_20260721.json \
     docs/canadian_geospatial_sources_coverage_20260721.md \
     docs/canadian_applied_guidance_rights_audit_20260721.md \
     docs/canadian_agronomy_corpus_promotion_audit_v13_20260725.json \
     docs/canadian_agronomy_corpus_promotion_audit_v13_20260725.md \
     docs/canada_agronomy_ontario_context_v1_audit_20260725.md \
     docs/conference_freeze_knowledge_gap_matrix_20260725.md \
     docs/runtime_knowledge_sufficiency_audit_20260725.md \
     docs/french_applied_guidance_source_disposition_20260726.md \
     docs/applied_guidance_source_preflight_registry_20260726.md \
     docs/provincial_applied_guidance_admission_queue_20260724.md \
     docs/canadian_conference_semantic_review_v3_20260725.json \
     docs/canadian_conference_semantic_review_v3_20260725.md \
     ./docs/
COPY docs/open_agronomy_agent_whitepaper_20260709 ./docs/open_agronomy_agent_whitepaper_20260709
COPY docs/alberta_applied_guidance_validation_20260725 ./docs/alberta_applied_guidance_validation_20260725
COPY docs/bc_aem_nutrient_application_plan_validation_20260727 ./docs/bc_aem_nutrient_application_plan_validation_20260727
COPY docs/manitoba_applied_guidance_validation_20260725 ./docs/manitoba_applied_guidance_validation_20260725
COPY docs/manitoba_fertilizer_check_stamp_validation_20260726 ./docs/manitoba_fertilizer_check_stamp_validation_20260726
COPY docs/manitoba_stored_grain_monitoring_validation_20260726 ./docs/manitoba_stored_grain_monitoring_validation_20260726
COPY docs/french_applied_guidance_validation_20260725 ./docs/french_applied_guidance_validation_20260725
COPY outputs/knowledge_freeze_readiness_20260725/runtime_corpus_audit_final_mvp.json \
     outputs/knowledge_freeze_readiness_20260725/conference_freeze_gap_matrix.json \
     outputs/knowledge_freeze_readiness_20260725/runtime_knowledge_sufficiency.json \
     outputs/knowledge_freeze_readiness_20260725/backend_pytest.xml \
     outputs/knowledge_freeze_readiness_20260725/frontend_vitest.json \
     ./outputs/knowledge_freeze_readiness_20260725/
COPY outputs/tool_smoke/ppls_adapter_modes_latest.json \
     outputs/tool_smoke/keyed_public_adapters_latest.json \
     outputs/tool_smoke/public_adapter_regional_matrix_latest.json \
     ./outputs/tool_smoke/
COPY outputs/evals/aiagribench_proxy_iter17_full_live_precision_economics_cleanup ./outputs/evals/aiagribench_proxy_iter17_full_live_precision_economics_cleanup
COPY outputs/evals/expert_review_807_blinded_semantic_20260718 ./outputs/evals/expert_review_807_blinded_semantic_20260718
COPY outputs/evals/canadian_semantic_reserve_v1_qwen2b ./outputs/evals/canadian_semantic_reserve_v1_qwen2b
COPY outputs/evals/public_domain_coverage_full_live_1056_current_rescore_contract_repairs_final ./outputs/evals/public_domain_coverage_full_live_1056_current_rescore_contract_repairs_final
COPY outputs/evals/public_claim_stress_focus_full_live_20260710_submission_hygiene_rescore ./outputs/evals/public_claim_stress_focus_full_live_20260710_submission_hygiene_rescore
COPY outputs/evals/public_shadow_heldout ./outputs/evals/public_shadow_heldout
COPY outputs/evals/agentic_gap_matrix ./outputs/evals/agentic_gap_matrix
COPY outputs/evals/general_agent_semantic_control_v5_240/agronomic_rag_20260715T031940Z ./outputs/evals/general_agent_semantic_control_v5_240/agronomic_rag_20260715T031940Z
COPY outputs/evals/canadian_conference_transfer_gate_gemma4_generalized_v5/agronomic_rag_20260720T224916Z ./outputs/evals/canadian_conference_transfer_gate_gemma4_generalized_v5/agronomic_rag_20260720T224916Z
COPY outputs/evals/canadian_conference_preflight_v2_rc20_final_20260725 ./outputs/evals/canadian_conference_preflight_v2_rc20_final_20260725
COPY outputs/evals/canadian_conference_transfer_gate_v2_rc20_release_candidate_v2_gemma4_20260725/agronomic_rag_20260725T035257Z ./outputs/evals/canadian_conference_transfer_gate_v2_rc20_release_candidate_v2_gemma4_20260725/agronomic_rag_20260725T035257Z
COPY scripts ./scripts
COPY container ./container
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

RUN mkdir -p /state /app/data/derived/geo_cache \
    && chmod 755 /app/container/entrypoint.sh \
    && chmod -R a+rX /app

ARG RUNTIME_MANIFEST_SHA256=unrecorded
ARG RELEASE_VERSION=development
LABEL org.opencontainers.image.title="Open Agronomy Agent" \
      org.opencontainers.image.description="Local-first Canadian agronomy agent and map workspace" \
      org.opencontainers.image.source="https://github.com/open-agronomy/open-agronomy-agent" \
      org.opencontainers.image.licenses="NOASSERTION" \
      org.opencontainers.image.version="${RELEASE_VERSION}" \
      io.openagronomy.runtime-manifest-sha256="${RUNTIME_MANIFEST_SHA256}"

EXPOSE 8080
VOLUME ["/state"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
    CMD if [ "${AGRONOMY_AGENT_FIELD_LAN:-false}" = "true" ]; then \
          curl --insecure --fail --silent https://127.0.0.1:8080/health >/dev/null; \
        else \
          curl --fail --silent http://127.0.0.1:8080/health >/dev/null; \
        fi || exit 1

ENTRYPOINT ["/app/container/entrypoint.sh"]
CMD ["uvicorn", "agronomy_agent.server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
