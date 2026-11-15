#!/usr/bin/env bash
# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
#
# One-command deployment of the Gemini 4 Periodic Element Router to Google Cloud Run.
# Least-privilege IAM roles recommended on the Cloud Run runtime service account:
#   - roles/aiplatform.user        (Gemini 4 generateContent / streamGenerateContent)
#   - roles/bigquery.dataEditor    (optional: streaming insert to gemini4_finops.router_telemetry)
#   - roles/storage.objectViewer   (optional: Cloud Storage gs:// binary Office inputs)
#
# Usage:
#   GOOGLE_CLOUD_PROJECT=your-gcp-project-id REGION=us-central1 ./deploy/deploy_cloud_run.sh

set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT before running}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-gemini4-periodic-router}"

echo "Deploying ${SERVICE_NAME} to Google Cloud Run (${PROJECT_ID} / ${REGION})..."
gcloud run deploy "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --source="." \
  --timeout=360 \
  --concurrency=40 \
  --cpu=2 \
  --memory=1Gi \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --no-allow-unauthenticated

SVC_URL="$(gcloud run services describe "${SERVICE_NAME}" --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')"
echo "Deployment complete: ${SVC_URL}"
echo "Verify live health check (use /health on Cloud Run since Google Frontend reserves /healthz):"
echo "  curl -sS -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \"${SVC_URL}/health\""
