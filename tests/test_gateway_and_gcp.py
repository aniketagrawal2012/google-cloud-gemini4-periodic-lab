# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Integration and contract tests for Cloud Run FastAPI Gateway, Regional Resolver, OOXML, and ADK callback."""

from __future__ import annotations

import base64
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.adk_agent import periodic_before_model_callback
from app.gcp_client import build_gcs_office_part
from app.periodic_router import (
    build_multiturn_tool_continuation,
    resolve_gcp_endpoint,
    validate_ooxml_bytes,
)
from app.service import app

client = TestClient(app)


def _make_xlsx(include_styles_and_strings: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
        if include_styles_and_strings:
            zf.writestr("xl/styles.xml", "<styleSheet/>")
            zf.writestr("xl/sharedStrings.xml", "<sst/>")
    return buf.getvalue()


def test_regional_endpoint_resolver_honors_argon_residency() -> None:
    # Single-region London (europe-west2) honored natively on Argon
    ep_argon = resolve_gcp_endpoint(
        "gemini-4-argon",
        project_id="demo-gcp-proj",
        preferred_region="europe-west2",
    )
    assert ep_argon.effective_region == "europe-west2"
    assert ep_argon.single_region_enforced is True
    assert ep_argon.endpoint_url.startswith("https://europe-west2-aiplatform.googleapis.com/v1beta1/")

    # Multi-region `eu` uses unified aiplatform.googleapis.com hostname on all 3 elements
    ep_hydro_eu = resolve_gcp_endpoint(
        "gemini-4-hydrogen",
        project_id="demo-gcp-proj",
        preferred_region="eu",
    )
    assert ep_hydro_eu.effective_region == "eu"
    assert ep_hydro_eu.single_region_enforced is False
    assert ep_hydro_eu.endpoint_url == (
        "https://aiplatform.googleapis.com/v1beta1/projects/demo-gcp-proj/locations/eu"
        "/publishers/google/models/gemini-4-hydrogen:generateContent"
    )

    # Requesting legacy us-central1 cleanly maps to `us` multi-region residency
    ep_hydro_us = resolve_gcp_endpoint(
        "gemini-4-hydrogen",
        project_id="demo-gcp-proj",
        preferred_region="us-central1",
    )
    assert ep_hydro_us.effective_region == "us"
    assert ep_hydro_us.endpoint_url.startswith("https://aiplatform.googleapis.com/v1beta1/")


def test_ooxml_validator_catches_missing_styles_and_shared_strings() -> None:
    good = validate_ooxml_bytes(_make_xlsx(include_styles_and_strings=True), "xlsx")
    assert good.valid is True
    assert good.missing_required_parts == []

    minimal = validate_ooxml_bytes(_make_xlsx(include_styles_and_strings=False), "xlsx")
    assert minimal.valid is False
    assert "xl/styles.xml" in minimal.missing_required_parts
    assert "xl/sharedStrings.xml" in minimal.missing_required_parts

    corrupt = validate_ooxml_bytes(b"not-a-zip", "docx")
    assert corrupt.valid is False


def test_multiturn_tool_continuation_preserves_thought_signature() -> None:
    prior = [{"role": "user", "parts": [{"text": "Lookup CUD rate"}]}]
    model_content = {
        "role": "model",
        "parts": [
            {
                "functionCall": {"name": "get_spanner_cud_rate", "args": {"region": "us-central1"}},
                "thoughtSignature": "A" * 512,
            }
        ],
    }
    updated, sig_len = build_multiturn_tool_continuation(
        prior_contents=prior,
        model_response_content=model_content,
        function_name="get_spanner_cud_rate",
        function_response_payload={"effective_hourly_usd_per_node": 0.432},
    )
    assert sig_len == 512
    assert len(updated) == 3
    assert updated[1]["parts"][0]["thoughtSignature"] == "A" * 512
    assert updated[2]["parts"][0]["functionResponse"]["name"] == "get_spanner_cud_rate"


def test_build_gcs_office_part_infers_mime_and_rejects_http() -> None:
    part = build_gcs_office_part("gs://finops-audit-bucket/q4_report.xlsx")
    assert part["fileData"]["fileUri"] == "gs://finops-audit-bucket/q4_report.xlsx"
    assert "spreadsheetml" in part["fileData"]["mimeType"]

    with pytest.raises(ValueError, match="gs://"):
        build_gcs_office_part("https://example.com/report.xlsx")


def test_fastapi_gateway_healthz_and_route_headers() -> None:
    r_health = client.get("/healthz")
    assert r_health.status_code == 200
    body = r_health.json()
    assert body["status"] == "ok"
    assert set(body["elements"].keys()) == {"gemini-4-hydrogen", "gemini-4-carbon", "gemini-4-argon"}

    # Regulated single-region UK workload -> Argon on europe-west2
    r_uk = client.post(
        "/v1/route",
        json={
            "profile": {
                "complexity": "hard_reasoning",
                "requires_single_region_ga": True,
                "has_office_attachment": False,
            },
            "preferred_region": "europe-west2",
            "project_id": "demo-gcp-proj",
        },
    )
    assert r_uk.status_code == 200
    assert r_uk.headers["X-Gemini4-Element"] == "gemini-4-argon"
    assert r_uk.headers["X-Gemini4-Thinking-Level"] == "MEDIUM"
    assert r_uk.headers["X-Gemini4-Endpoint-Region"] == "europe-west2"
    assert r_uk.json()["endpoint"]["single_region_enforced"] is True

    # Frontier balanced reasoning with Office attachment -> Carbon:MEDIUM on global
    r_carbon = client.post(
        "/v1/route",
        json={
            "profile": {
                "complexity": "hard_reasoning",
                "budget_priority": "balanced",
                "has_office_attachment": True,
            },
            "project_id": "demo-gcp-proj",
        },
    )
    assert r_carbon.status_code == 200
    assert r_carbon.headers["X-Gemini4-Element"] == "gemini-4-carbon"
    assert r_carbon.headers["X-Gemini4-Thinking-Level"] == "MEDIUM"


def test_fastapi_gateway_cache_and_ooxml_audits() -> None:
    static_prefix = "cloud finops policy reference " * 1200
    r_cache = client.post("/v1/audit/cache-prefix", json={"system_instruction": static_prefix})
    assert r_cache.status_code == 200
    assert r_cache.json()["cache_eligible"] is True

    good_b64 = base64.b64encode(_make_xlsx(True)).decode("ascii")
    r_ooxml = client.post("/v1/audit/ooxml", json={"kind": "xlsx", "base64_content": good_b64})
    assert r_ooxml.status_code == 200
    assert r_ooxml.json()["valid"] is True


def test_adk_before_model_callback_dynamic_lanes() -> None:
    res_fast = periodic_before_model_callback(
        session_state={"complexity": "routine", "has_office_attachment": True}
    )
    assert res_fast["model"] == "gemini-4-hydrogen"
    assert res_fast["thinking_level"] == "LOW"
    assert res_fast["contract_valid"] is True

    res_ga = periodic_before_model_callback(
        session_state={"complexity": "frontier_deep", "requires_single_region_ga": True}
    )
    assert res_ga["model"] == "gemini-4-argon"
    assert res_ga["thinking_level"] == "HIGH"
    assert res_ga["contract_valid"] is True
