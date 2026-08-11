#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=${1:-}
case "$VERSION" in
  ""|*[!A-Za-z0-9._-]*)
    printf 'Usage: %s VERSION\n' "$0" >&2
    printf 'VERSION may contain letters, numbers, dot, underscore, and hyphen.\n' >&2
    exit 2
    ;;
esac

IMAGE_REPOSITORY=${AGRONOMY_AGENT_IMAGE_REPOSITORY:-open-agronomy-agent}
IMAGE="$IMAGE_REPOSITORY:$VERSION"
RELEASE_DIR=${AGRONOMY_AGENT_RELEASE_DIR:-"$ROOT_DIR/outputs/releases/open-agronomy-agent-$VERSION"}
ARCHIVE="$RELEASE_DIR/open-agronomy-agent-$VERSION-linux-arm64.oci.tar"
PACKAGE_VALIDATION="$RELEASE_DIR/package_validation.json"
TRANSLATION_VALIDATION="$RELEASE_DIR/runtime_translation_validation.json"
ARCHIVE_VALIDATION="$RELEASE_DIR/oci_archive_validation.json"
RELEASE_MANIFEST="$RELEASE_DIR/release_manifest.json"
SBOM="$RELEASE_DIR/open_agronomy_agent.spdx.json"
SOURCE_READINESS="$RELEASE_DIR/source_advisory_readiness.json"
BACKEND_TEST_RECEIPT="$RELEASE_DIR/source_backend_pytest.xml"
FRONTEND_TEST_RECEIPT="$RELEASE_DIR/source_frontend_vitest.json"
CURRENT_READINESS_DIR="$ROOT_DIR/outputs/current_source_readiness_20260725"
CURRENT_PACKAGE_VALIDATION="$CURRENT_READINESS_DIR/package_validation.json"
CURRENT_SOURCE_READINESS="$CURRENT_READINESS_DIR/advisory_readiness.json"
CURRENT_SOURCE_READINESS_MARKDOWN="$ROOT_DIR/docs/current_source_readiness_20260725.md"
SOURCE_BACKEND_TEST_RECEIPT=${AGRONOMY_AGENT_BACKEND_TEST_RECEIPT:-"$CURRENT_READINESS_DIR/backend_pytest.xml"}
SOURCE_FRONTEND_TEST_RECEIPT=${AGRONOMY_AGENT_FRONTEND_TEST_RECEIPT:-"$CURRENT_READINESS_DIR/frontend_vitest.json"}
SIGNING_KEY=${AGRONOMY_AGENT_RELEASE_SIGNING_KEY:-}
ALLOW_UNSIGNED=${AGRONOMY_AGENT_ALLOW_UNSIGNED_RELEASE:-0}
RECLAIM_BUILDER=${AGRONOMY_AGENT_RELEASE_RECLAIM_BUILDER:-1}
IMAGE_BUILD_MODE=${AGRONOMY_AGENT_IMAGE_BUILD_MODE:-full}

if [ -z "$SIGNING_KEY" ] && [ "$ALLOW_UNSIGNED" != "1" ]; then
  printf 'A release signing key is required. Set AGRONOMY_AGENT_RELEASE_SIGNING_KEY to an Ed25519 private key.\n' >&2
  printf 'For an explicitly non-production rehearsal only, set AGRONOMY_AGENT_ALLOW_UNSIGNED_RELEASE=1.\n' >&2
  exit 1
fi

command -v container >/dev/null 2>&1 || {
  printf 'Apple Container is required to build the reference release.\n' >&2
  exit 1
}
for receipt in "$SOURCE_BACKEND_TEST_RECEIPT" "$SOURCE_FRONTEND_TEST_RECEIPT"; do
  if [ ! -f "$receipt" ]; then
    printf 'Release test receipt does not exist or is not a regular file: %s\n' "$receipt" >&2
    exit 1
  fi
done
if [ -e "$RELEASE_DIR" ]; then
  printf 'Refusing to overwrite immutable release path: %s\n' "$RELEASE_DIR" >&2
  printf 'Choose a new version or inspect and retire the existing path explicitly.\n' >&2
  exit 1
fi
mkdir -p "$RELEASE_DIR"

case "$IMAGE_BUILD_MODE" in
  full)
    AGRONOMY_AGENT_IMAGE="$IMAGE" \
    AGRONOMY_AGENT_RELEASE_VERSION="$VERSION" \
      "$ROOT_DIR/container/build-image.sh" apple
    ;;
  overlay)
    AGRONOMY_AGENT_IMAGE="$IMAGE" \
    AGRONOMY_AGENT_RELEASE_VERSION="$VERSION" \
      "$ROOT_DIR/container/build-overlay-image.sh" apple
    ;;
  prebuilt)
    if ! container image inspect "$IMAGE" >/dev/null 2>&1; then
      printf 'Requested prebuilt image is not available locally: %s\n' "$IMAGE" >&2
      exit 1
    fi
    ;;
  *)
    printf 'AGRONOMY_AGENT_IMAGE_BUILD_MODE must be full, overlay, or prebuilt.\n' >&2
    exit 2
    ;;
esac

PYTHONPATH="$ROOT_DIR/src" "$ROOT_DIR/.venv/bin/python" \
  "$ROOT_DIR/scripts/validate_edge_container_package.py" \
  --root "$ROOT_DIR" \
  --output "$PACKAGE_VALIDATION"
cp "$PACKAGE_VALIDATION" "$CURRENT_PACKAGE_VALIDATION"

PYTHONPATH="$ROOT_DIR/src" "$ROOT_DIR/.venv/bin/python" \
  "$ROOT_DIR/scripts/validate_edge_runtime_translation.py" \
  --root "$ROOT_DIR" \
  --image "$IMAGE" \
  --output "$TRANSLATION_VALIDATION"

PYTHONPATH="$ROOT_DIR/src" "$ROOT_DIR/.venv/bin/python" \
  "$ROOT_DIR/scripts/build_runtime_sbom.py" \
  --root "$ROOT_DIR" \
  --output "$SBOM"

PYTHONPATH="$ROOT_DIR/src" "$ROOT_DIR/.venv/bin/python" \
  "$ROOT_DIR/scripts/audit_conference_freeze_readiness.py" \
  --profile current-source \
  --output "$CURRENT_SOURCE_READINESS" \
  --markdown "$CURRENT_SOURCE_READINESS_MARKDOWN" \
  --allow-blocked

cp "$CURRENT_SOURCE_READINESS" "$SOURCE_READINESS"
cp "$SOURCE_BACKEND_TEST_RECEIPT" "$BACKEND_TEST_RECEIPT"
cp "$SOURCE_FRONTEND_TEST_RECEIPT" "$FRONTEND_TEST_RECEIPT"

if [ "$RECLAIM_BUILDER" = "1" ]; then
  if container builder stop >/dev/null 2>&1; then
    printf 'Deleting the stopped disposable Apple Container builder before release export.\n'
    container builder delete
  else
    printf 'Disposable Apple Container builder is already absent; continuing release export.\n'
  fi
fi

rm -f "$ARCHIVE"
container image save --platform linux/arm64 --output "$ARCHIVE" "$IMAGE"
RUNTIME_MANIFEST_SHA256=$(shasum -a 256 "$ROOT_DIR/container/runtime_manifest.json" | awk '{print $1}')

PYTHONPATH="$ROOT_DIR/src" "$ROOT_DIR/.venv/bin/python" \
  "$ROOT_DIR/scripts/validate_edge_oci_archive.py" \
  --archive "$ARCHIVE" \
  --version "$VERSION" \
  --runtime-manifest-sha256 "$RUNTIME_MANIFEST_SHA256" \
  --output "$ARCHIVE_VALIDATION"

PYTHONPATH="$ROOT_DIR/src" "$ROOT_DIR/.venv/bin/python" \
  "$ROOT_DIR/scripts/build_edge_container_release.py" \
  --root "$ROOT_DIR" \
  --version "$VERSION" \
  --image "$IMAGE" \
  --archive "$ARCHIVE" \
  --archive-validation "$ARCHIVE_VALIDATION" \
  --package-validation "$PACKAGE_VALIDATION" \
  --translation-validation "$TRANSLATION_VALIDATION" \
  --sbom "$SBOM" \
  --release-evidence "$SOURCE_READINESS" \
  --release-evidence "$BACKEND_TEST_RECEIPT" \
  --release-evidence "$FRONTEND_TEST_RECEIPT" \
  --output "$RELEASE_MANIFEST"

(
  cd "$RELEASE_DIR"
  shasum -a 256 \
    "$(basename "$ARCHIVE")" \
    "$(basename "$PACKAGE_VALIDATION")" \
    "$(basename "$TRANSLATION_VALIDATION")" \
    "$(basename "$ARCHIVE_VALIDATION")" \
    "$(basename "$SBOM")" \
    "$(basename "$SOURCE_READINESS")" \
    "$(basename "$BACKEND_TEST_RECEIPT")" \
    "$(basename "$FRONTEND_TEST_RECEIPT")" \
    "$(basename "$RELEASE_MANIFEST")" >SHA256SUMS
)

if [ -n "$SIGNING_KEY" ]; then
  PYTHONPATH="$ROOT_DIR/src" "$ROOT_DIR/.venv/bin/python" \
    "$ROOT_DIR/scripts/artifact_signature.py" sign \
    --manifest "$RELEASE_DIR/SHA256SUMS" \
    --private-key "$SIGNING_KEY" \
    --signature "$RELEASE_DIR/SHA256SUMS.sig"
  printf 'Signed release ready: %s\n' "$RELEASE_DIR"
else
  printf 'Unsigned rehearsal package ready: %s\n' "$RELEASE_DIR"
fi
printf 'Apple import: container image load --input %s\n' "$ARCHIVE"
printf 'Docker import: docker load --input %s\n' "$ARCHIVE"
