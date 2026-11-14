#!/usr/bin/env bash
# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
#
# One-command deployment of the Gemini 4 Periodic Element Router to Google Cloud Run.
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

echo "Deployment complete. Test with:"
echo "  gcloud run services proxy ${SERVICE_NAME} --region=${REGION} --project=${PROJECT_ID}"
