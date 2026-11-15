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
"""Production Cloud Run FastAPI Gateway for the Gemini 4 Periodic Element Router."""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

from app.gcp_client import PeriodicGCPClient
from app.periodic_router import (
    GEMINI4_SPECS,
    TaskProfile,
    audit_implicit_cache_prefix,
    resolve_gcp_endpoint,
    select_periodic_route,
    validate_gemini4_request,
    validate_ooxml_bytes,
)

app = FastAPI(
    title="Google Cloud Gemini 4 Periodic Element Router",
    description=(
        "Empirically calibrated routing gateway across Gemini 4 Hydrogen, Carbon, and Argon "
        "with contract guardrails, 95% cache prefix auditing, regional residency resolution, "
        "and OOXML pre-flight checks."
    ),
    version="2.0.0",
)


class RoutePlanRequest(BaseModel):
    profile: TaskProfile
    preferred_region: str = Field(
        default="global",
        description="Official Gemini 4 locations: global, us, eu (all elements) or europe-west2, asia-southeast1 (Argon single-region)",
    )
    project_id: str = Field(default="your-gcp-project-id")
    streaming: bool = True
    expected_output_tokens: int = 4_096


class CacheAuditRequest(BaseModel):
    system_instruction: str


class OOXMLAuditRequest(BaseModel):
    kind: Literal["xlsx", "docx"]
    base64_content: str


class GenerateRequest(BaseModel):
    prompt: str
    profile: TaskProfile = Field(default_factory=TaskProfile)
    preferred_region: str = "global"
    system_instruction: str | None = None
    gcs_attachment_uri: str | None = None
    gcs_mime_type: str | None = None
    response_schema: dict[str, Any] | None = None
    enable_google_search: bool = False


@app.get("/")
@app.get("/health")
@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "gemini4-periodic-router",
        "elements": {
            m: {
                "element": s.element,
                "default_thinking": s.default_thinking,
                "single_region_ga": s.supports_single_region,
                "native_office_mime": s.supports_office_mime,
            }
            for m, s in GEMINI4_SPECS.items()
        },
    }


@app.post("/v1/route")
def plan_route(req: RoutePlanRequest, response: Response) -> dict[str, Any]:
    """Deterministically plan the optimal Gemini 4 element, thinking level, and GCP endpoint."""
    decision = select_periodic_route(req.profile)
    guard = validate_gemini4_request(
        decision.model,
        thinking_level=decision.thinking_level,
        expected_output_tokens=req.expected_output_tokens,
        streaming=req.streaming,
        has_office_attachment=req.profile.has_office_attachment,
    )
    endpoint = resolve_gcp_endpoint(
        decision.model,
        project_id=req.project_id,
        preferred_region=req.preferred_region,
        streaming=req.streaming,
    )
    response.headers["X-Gemini4-Element"] = decision.model
    response.headers["X-Gemini4-Thinking-Level"] = decision.thinking_level
    response.headers["X-Gemini4-Endpoint-Region"] = endpoint.effective_region
    return {
        "decision": decision.model_dump(),
        "contract_validation": guard.model_dump(),
        "endpoint": endpoint.model_dump(),
    }


@app.post("/v1/audit/cache-prefix")
def audit_cache(req: CacheAuditRequest) -> dict[str, Any]:
    """Audit a static systemInstruction prefix for 95% implicit cache eligibility."""
    return audit_implicit_cache_prefix(req.system_instruction)


@app.post("/v1/audit/ooxml")
def audit_ooxml(req: OOXMLAuditRequest) -> dict[str, Any]:
    """Validate binary .xlsx / .docx OOXML parts prior to native Hydrogen/Carbon ingestion."""
    try:
        raw = base64.b64decode(req.base64_content, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 payload: {exc}") from exc
    return validate_ooxml_bytes(raw, req.kind).model_dump()


@app.post("/v1/generate")
def routed_generate(req: GenerateRequest, response: Response) -> dict[str, Any]:
    """Route and execute a live Gemini 4 request on Google Cloud with FinOps headers."""
    profile = req.profile.model_copy(
        update={"has_office_attachment": req.profile.has_office_attachment or bool(req.gcs_attachment_uri)}
    )
    decision = select_periodic_route(profile)
    guard = validate_gemini4_request(
        decision.model,
        thinking_level=decision.thinking_level,
        has_office_attachment=profile.has_office_attachment,
    )
    if not guard.valid:
        raise HTTPException(status_code=400, detail={"contract_errors": guard.errors})

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise HTTPException(
            status_code=503,
            detail="GOOGLE_CLOUD_PROJECT is not configured on this gateway instance; use POST /v1/route for dry-run planning.",
        )

    client = PeriodicGCPClient(project_id=project_id)
    result = client.generate(
        model=decision.model,
        thinking_level=decision.thinking_level,
        prompt=req.prompt,
        preferred_region=req.preferred_region,
        system_instruction=req.system_instruction,
        gcs_attachment_uri=req.gcs_attachment_uri,
        gcs_mime_type=req.gcs_mime_type,
        response_schema=req.response_schema,
        enable_google_search=req.enable_google_search,
    )
    response.headers["X-Gemini4-Element"] = decision.model
    response.headers["X-Gemini4-Thinking-Level"] = decision.thinking_level
    response.headers["X-Gemini4-Endpoint-Region"] = result["endpoint"]["effective_region"]
    response.headers["X-Estimated-Cost-USD"] = str(result["telemetry"]["estimated_list_cost_usd"])
    return {
        "decision": decision.model_dump(),
        "guard_warnings": guard.warnings,
        **result,
    }
