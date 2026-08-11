#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

LOG_DIR="outputs/corpus_ingest"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/national_environment_ingest.log"

{
  echo "started=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "phase=canada_national_environment"
  python scripts/ingest_document_sources.py \
    --source-id statcan_ecological_land_classification_2017 \
    --source-id cansis_national_ecological_framework \
    --download-timeout 240 \
    --max-words 220 \
    --overlap-words 35 \
    --fail-on-source-error

  echo "phase=us_nrcs_edit_all_mlras_json"
  python scripts/ingest_nrcs_esd_json.py \
    --all-mlras \
    --timeout 75 \
    --attempts 2 \
    --workers "${NRCS_ESD_WORKERS:-8}" \
    --max-words 220 \
    --overlap-words 35 \
    --retry-missing

  echo "phase=us_nrcs_edit_compact_projection"
  python scripts/build_compact_nrcs_esd_corpus.py --chunks-per-site "${NRCS_ESD_COMPACT_CHUNKS_PER_SITE:-4}"

  if [[ "${RUN_SUPPLEMENTAL_CANADA:-0}" == "1" ]]; then
    echo "phase=canada_supplemental_environment"
    python scripts/ingest_document_sources.py \
      --source-id ecozones_canada_narrative_descriptions \
      --source-id ontario_ecodistricts_part2 \
      --download-timeout 30 \
      --max-words 220 \
      --overlap-words 35 || true
  fi

  echo "phase=coverage_audit"
  python scripts/audit_corpus_expansion.py
  echo "finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} 2>&1 | tee "$LOG_FILE"
