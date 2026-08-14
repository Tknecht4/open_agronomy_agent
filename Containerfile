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
    AGRONOMY_AGENT_MODEL_CONFIG=configs/model_gemma4_e2b_interface_v2.yaml \
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

COPY requirements-container.txt pyproject.toml LICENSE THIRD_PARTY_NOTICES.md ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements-container.txt \
    && pip install --no-cache-dir --no-deps .

COPY configs ./configs
COPY data/seed ./data/seed
COPY data/manifests ./data/manifests
COPY data/eval ./data/eval
COPY data/snapshots ./data/snapshots
COPY data/derived/rag ./data/derived/rag
COPY data/derived/geo_cache ./data/derived/geo_cache
COPY data/derived/geo_layers/bc_agriculture_capability_manifest.json \
     data/derived/geo_layers/sk_thematic_soil_manifest.json \
     data/derived/geo_layers/sk_detailed_soil_manifest.json \
     data/derived/geo_layers/ca_soil_erosion_risk_manifest.json \
     data/derived/geo_layers/pei_detailed_soil_manifest.json \
     data/derived/geo_layers/ns_pictou_detailed_soil_manifest.json \
     data/derived/geo_layers/ab_detailed_soil_manifest.json \
     data/derived/geo_layers/mb_detailed_soil_manifest.json \
     ./data/derived/geo_layers/
COPY docs/public ./docs/public
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
      org.opencontainers.image.licenses="Apache-2.0" \
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
