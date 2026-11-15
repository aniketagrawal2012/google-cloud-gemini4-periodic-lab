#!/usr/bin/env bash
# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
#
# Quickstart curl examples against the local or Cloud Run Gemini 4 Periodic Router Gateway.
# Start the server first: `make gateway`

set -euo pipefail
BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"

echo "1. Health & Element Capabilities:"
curl -s "${BASE_URL}/health" | python3 -m json.tool

echo -e "\n2. Plan Regulated UK Single-Region GA Route (Argon on europe-west2):"
curl -s -i -X POST "${BASE_URL}/v1/route" \
  -H "Content-Type: application/json" \
  -d '{
    "profile": {
      "complexity": "hard_reasoning",
      "requires_single_region_ga": true,
      "has_office_attachment": false
    },
    "preferred_region": "europe-west2",
    "project_id": "your-gcp-project-id"
  }'

echo -e "\n\n3. Plan Frontier Reasoning + Native Binary Office Route (Carbon:MEDIUM):"
curl -s -i -X POST "${BASE_URL}/v1/route" \
  -H "Content-Type: application/json" \
  -d '{
    "profile": {
      "complexity": "hard_reasoning",
      "budget_priority": "balanced",
      "has_office_attachment": true
    },
    "project_id": "your-gcp-project-id"
  }'
