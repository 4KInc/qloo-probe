#!/usr/bin/env bash
# Deploy the public demo to Cloud Run.
#
# Two safeguards learned the hard way on a previous project:
#   * the target project is stated explicitly and never inherited from the
#     gcloud default, because building into the wrong project is silent;
#   * --set-env-vars REPLACES rather than merges, so every variable the live
#     service needs is listed here in one place.
set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT explicitly, do not rely on the gcloud default}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-travels-well}"
: "${QLOO_API_KEY:?QLOO_API_KEY must be set in the deploying shell}"

DEFAULT_PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
if [ "$DEFAULT_PROJECT" != "$GOOGLE_CLOUD_PROJECT" ]; then
  echo "note: gcloud default is '$DEFAULT_PROJECT', deploying to '$GOOGLE_CLOUD_PROJECT'"
fi

echo "deploying $SERVICE to $GOOGLE_CLOUD_PROJECT / $REGION"
gcloud run deploy "$SERVICE" \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --region "$REGION" \
  --source . \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --concurrency 40 \
  --max-instances 3 \
  --timeout 120 \
  --set-env-vars "QLOO_API_KEY=${QLOO_API_KEY},QLOO_BASE=${QLOO_BASE:-https://hackathon.api.qloo.com}"

URL="$(gcloud run services describe "$SERVICE" --project "$GOOGLE_CLOUD_PROJECT" \
       --region "$REGION" --format 'value(status.url)')"
echo
echo "live at: $URL"
echo "checking it answers cold..."
curl -fsS "$URL/healthz" && echo
curl -fsS "$URL/api/run?preset=films-br" >/dev/null && echo "preset path OK"
