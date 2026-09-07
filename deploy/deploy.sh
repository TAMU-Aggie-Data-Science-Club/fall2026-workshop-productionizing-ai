#!/usr/bin/env bash
set -euo pipefail

# Build and deploy Nimbus to one public Cloud Run service. The service is the
# participant-facing backend proxy: browser -> Nimbus -> managed model API.
# This script deliberately assumes the secret and runtime service account have
# already been created by the cloud owner.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

command -v gcloud >/dev/null 2>&1 || {
  echo "gcloud CLI is required. Install it or run this from Cloud Shell." >&2
  exit 1
}
command -v git >/dev/null 2>&1 || {
  echo "git is required so the image can be tagged." >&2
  exit 1
}

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${NIMBUS_SERVICE:-nimbus}"
REPOSITORY="${NIMBUS_REPOSITORY:-nimbus}"
RUNTIME_SA="${NIMBUS_RUNTIME_SERVICE_ACCOUNT:?Set NIMBUS_RUNTIME_SERVICE_ACCOUNT}"
ADMIN_SECRET="${NIMBUS_ADMIN_SECRET:-nimbus-admin-token}"
API_STYLE="${NIMBUS_GOOGLE_API_STYLE:-gemini}"
MIN_INSTANCES="${NIMBUS_MIN_INSTANCES:-1}"
MAX_INSTANCES="${NIMBUS_MAX_INSTANCES:-1}"
CONCURRENCY="${NIMBUS_CONCURRENCY:-80}"
# The app's admission limit must NOT default to Cloud Run's. They are different
# controls and they have to differ: Cloud Run decides how many requests reach
# the container, the app decides how many reach the model. If the platform limit
# is the lower of the two, requests wait in Cloud Run's queue where nothing can
# measure them -- `app queue wait` reads 0.00s and the capacity incident has no
# signature at all.
APP_CONCURRENCY="${NIMBUS_MAX_CONCURRENT:-2}"

if [ "${CONCURRENCY}" -le "${APP_CONCURRENCY}" ]; then
  echo "WARNING: Cloud Run --concurrency (${CONCURRENCY}) is not above the app's" >&2
  echo "         admission limit (${APP_CONCURRENCY}). The platform will queue" >&2
  echo "         before the app does, and queue wait will measure as zero." >&2
fi
CPU="${NIMBUS_CPU:-1}"
MEMORY="${NIMBUS_MEMORY:-1Gi}"
IMAGE_TAG="${NIMBUS_IMAGE_TAG:-$(git rev-parse --short HEAD)-$(date -u +%Y%m%d%H%M%S)}"
IMAGE="${NIMBUS_IMAGE:-${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/nimbus:${IMAGE_TAG}}"

case "${PROJECT_ID}" in
  replace-with-*|"")
    echo "GOOGLE_CLOUD_PROJECT still contains the example value." >&2
    exit 1
    ;;
esac

case "${RUNTIME_SA}" in
  *replace-with-project-id*)
    echo "NIMBUS_RUNTIME_SERVICE_ACCOUNT still contains the example value." >&2
    exit 1
    ;;
esac

case "${API_STYLE}" in
  gemini|mistral|openai) ;;
  *)
    echo "NIMBUS_GOOGLE_API_STYLE must be gemini, mistral or openai." >&2
    exit 1
    ;;
esac

if [ "${API_STYLE}" = "openai" ] && [ -z "${NIMBUS_GOOGLE_MODEL_ID:-}" ]; then
  echo "NIMBUS_GOOGLE_MODEL_ID is required for the openai endpoint style." >&2
  exit 1
fi

# Model selection. NIMBUS_GOOGLE_MODEL_ID pins BOTH tiers to one model, so it is
# only forwarded when the operator actually set it -- otherwise the two tiers
# come from the per-tier variables and routing stays a real lever.
MODEL_ENV=""
if [ -n "${NIMBUS_GOOGLE_MODEL_ID:-}" ]; then
  MODEL_ENV="${MODEL_ENV}@NIMBUS_GOOGLE_MODEL_ID=${NIMBUS_GOOGLE_MODEL_ID}"
fi
if [ -n "${NIMBUS_GOOGLE_MODEL_SMALL:-}" ]; then
  MODEL_ENV="${MODEL_ENV}@NIMBUS_GOOGLE_MODEL_SMALL=${NIMBUS_GOOGLE_MODEL_SMALL}"
fi
if [ -n "${NIMBUS_GOOGLE_MODEL_LARGE:-}" ]; then
  MODEL_ENV="${MODEL_ENV}@NIMBUS_GOOGLE_MODEL_LARGE=${NIMBUS_GOOGLE_MODEL_LARGE}"
fi

# Gemini 2.5 spends the output-token budget on thinking before it answers. At
# the workshop's default cap that returns NO text while latency and cost still
# read as healthy, so the budget is forwarded explicitly rather than left to a
# default anyone could change without noticing.
if [ "${API_STYLE}" = "gemini" ]; then
  MODEL_ENV="${MODEL_ENV}@NIMBUS_GEMINI_THINKING_BUDGET=${NIMBUS_GEMINI_THINKING_BUDGET:-0}"
fi

# Per-team incident injection, when the caller sets it. Never echoed anywhere a
# participant can read.
INCIDENT_ENV=""
# The public half of the incident: the symptom a user would report. Safe to
# serve, and required, because the catalog that holds the story is
# facilitator-only and the service cannot read it.
for public in NIMBUS_INCIDENT_TITLE NIMBUS_INCIDENT_BRIEF NIMBUS_INCIDENT_IMPACT \
             NIMBUS_TRAFFIC_REQUESTS NIMBUS_TRAFFIC_RATE NIMBUS_TRAFFIC_CONCURRENCY; do
  eval "value=\${${public}:-}"
  if [ -n "${value}" ]; then
    INCIDENT_ENV="${INCIDENT_ENV}@${public}=${value}"
  fi
done

if [ -n "${NIMBUS_INCIDENT_STAGE_DELAY:-}" ]; then
  INCIDENT_ENV="${INCIDENT_ENV}@NIMBUS_INCIDENT_STAGE_DELAY=${NIMBUS_INCIDENT_STAGE_DELAY}"
fi
if [ -n "${NIMBUS_INCIDENT_PROVIDER_FAULT:-}" ]; then
  INCIDENT_ENV="${INCIDENT_ENV}@NIMBUS_INCIDENT_PROVIDER_FAULT=${NIMBUS_INCIDENT_PROVIDER_FAULT}"
fi

# An explicit digest is the reviewed artifact, regardless of local tree state.
# Otherwise build once under a unique tag and resolve it to an immutable digest.
if [ -n "${NIMBUS_IMAGE:-}" ]; then
  case "${IMAGE}" in
    *@sha256:*) ;;
    *) echo "NIMBUS_IMAGE must be an immutable @sha256 digest." >&2; exit 1 ;;
  esac
  gcloud artifacts docker images describe "${IMAGE}" --project="${PROJECT_ID}" >/dev/null
else
  if [ "${NIMBUS_SKIP_BUILD:-0}" = "1" ]; then
    echo "NIMBUS_SKIP_BUILD requires an explicit NIMBUS_IMAGE digest." >&2
    exit 1
  fi
  gcloud artifacts repositories describe "${REPOSITORY}" \
    --project="${PROJECT_ID}" --location="${REGION}" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "${REPOSITORY}" \
    --project="${PROJECT_ID}" --location="${REGION}" --repository-format=docker
  gcloud builds submit . --project="${PROJECT_ID}" --tag="${IMAGE}"
  DIGEST="$(gcloud artifacts docker images describe "${IMAGE}" \
    --project="${PROJECT_ID}" --format='value(image_summary.digest)')"
  case "${DIGEST}" in sha256:*) ;; *) echo "Image digest not returned" >&2; exit 1 ;; esac
  IMAGE="${IMAGE%:*}@${DIGEST}"
fi
printf 'NIMBUS_IMAGE=%s\n' "${IMAGE}"
if [ "${NIMBUS_BUILD_ONLY:-0}" = "1" ]; then
  exit 0
fi

gcloud run deploy "${SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --service-account="${RUNTIME_SA}" \
  --port=8080 \
  --cpu="${CPU}" \
  --memory="${MEMORY}" \
  --concurrency="${CONCURRENCY}" \
  --min="${MIN_INSTANCES}" \
  --max="${MAX_INSTANCES}" \
  --timeout=3600 \
  --allow-unauthenticated \
  --set-env-vars="^@^NIMBUS_MODEL_BACKEND=google@NIMBUS_GOOGLE_API_STYLE=${API_STYLE}@GOOGLE_CLOUD_PROJECT=${PROJECT_ID}@GOOGLE_CLOUD_LOCATION=${REGION}@NIMBUS_RESPONSE_CACHE=${NIMBUS_RESPONSE_CACHE:-true}@NIMBUS_PREFIX_CACHE=${NIMBUS_PREFIX_CACHE:-false}@NIMBUS_SEMANTIC_CACHE=${NIMBUS_SEMANTIC_CACHE:-false}@NIMBUS_SYSTEM_PROMPT=${NIMBUS_SYSTEM_PROMPT:-TRIMMED}@NIMBUS_RETRIEVE_K=${NIMBUS_RETRIEVE_K:-3}@NIMBUS_MAX_TOKENS=${NIMBUS_MAX_TOKENS:-32}@NIMBUS_MAX_CONCURRENT=${APP_CONCURRENCY}@NIMBUS_SHED_ABOVE_QUEUE=${NIMBUS_SHED_ABOVE_QUEUE:-4}@NIMBUS_MODEL_TIER=${NIMBUS_MODEL_TIER:-large}@NIMBUS_ROUTE_EASY=${NIMBUS_ROUTE_EASY:-false}@NIMBUS_SEMANTIC_CACHE_THRESHOLD=${NIMBUS_SEMANTIC_CACHE_THRESHOLD:-0.92}@NIMBUS_REQUIRE_HYPOTHESIS=${NIMBUS_REQUIRE_HYPOTHESIS:-false}${MODEL_ENV}${INCIDENT_ENV}" \
  --update-secrets="NIMBUS_ADMIN_TOKEN=${ADMIN_SECRET}:latest"

SERVICE_URL="$(gcloud run services describe "${SERVICE}" \
  --project="${PROJECT_ID}" --region="${REGION}" \
  --format='value(status.url)')"

printf 'Nimbus URL: %s\n' "${SERVICE_URL}"
