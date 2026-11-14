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
"""Google Cloud Gemini 4 REST, Cloud Storage (`gs://`), and BigQuery FinOps Client."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.periodic_router import (
    ElementModel,
    ThinkingLevel,
    estimate_cost_usd,
    resolve_gcp_endpoint,
)

logger = logging.getLogger("gemini4.periodic.client")

OFFICE_MIME_TYPES: dict[str, str] = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".odp": "application/vnd.oasis.opendocument.presentation",
}


class TelemetryEvent(BaseModel):
    """Structured telemetry event compatible with Cloud Logging and BigQuery FinOps tables."""

    event_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model: ElementModel
    thinking_level: ThinkingLevel
    endpoint_region: str
    http_status: int
    latency_s: float
    prompt_tokens: int = 0
    cached_tokens: int = 0
    thoughts_tokens: int = 0
    output_tokens: int = 0
    estimated_list_cost_usd: float = 0.0
    used_gcs_uri: bool = False
    used_google_search: bool = False
    used_response_schema: bool = False
    thought_signature_bytes: int = 0


def build_gcs_office_part(gcs_uri: str, mime_type: str | None = None) -> dict[str, Any]:
    """Construct a native Gemini 4 `fileData` part referencing a Cloud Storage `gs://` URI."""
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Expected a Cloud Storage URI starting with 'gs://', got: {gcs_uri!r}")
    resolved_mime = mime_type
    if not resolved_mime:
        lower = gcs_uri.lower()
        for ext, mtype in OFFICE_MIME_TYPES.items():
            if lower.endswith(ext):
                resolved_mime = mtype
                break
    if not resolved_mime:
        raise ValueError(f"Could not infer Office MIME type for {gcs_uri!r}; pass `mime_type` explicitly.")
    return {"fileData": {"mimeType": resolved_mime, "fileUri": gcs_uri}}


class PeriodicGCPClient:
    """Thin production REST client for Gemini 4 on Google Cloud with BigQuery telemetry emission."""

    def __init__(
        self,
        project_id: str | None = None,
        *,
        bq_telemetry_table: str | None = None,
        token_provider: Any | None = None,
    ) -> None:
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        self.bq_telemetry_table = bq_telemetry_table or os.environ.get("BIGQUERY_TELEMETRY_TABLE")
        self._token_provider = token_provider
        self._cached_token = ""
        self._token_ts = 0.0

    def _get_bearer_token(self) -> str:
        if self._token_provider is not None:
            return str(self._token_provider())
        if self._cached_token and (time.time() - self._token_ts) < 1800:
            return self._cached_token
        try:
            import google.auth
            import google.auth.transport.requests

            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            creds.refresh(google.auth.transport.requests.Request())
            if creds.token:
                self._cached_token = creds.token
                self._token_ts = time.time()
                return self._cached_token
        except Exception:
            pass
        self._cached_token = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"], text=True
        ).strip()
        self._token_ts = time.time()
        return self._cached_token

    def generate(
        self,
        *,
        model: ElementModel,
        thinking_level: ThinkingLevel,
        prompt: str,
        preferred_region: str = "global",
        system_instruction: str | None = None,
        gcs_attachment_uri: str | None = None,
        gcs_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
        enable_google_search: bool = False,
        timeout_s: int = 180,
    ) -> dict[str, Any]:
        """Execute a live Gemini 4 call with automatic regional resolution and FinOps telemetry."""
        if not self.project_id:
            raise ValueError("Set GOOGLE_CLOUD_PROJECT or pass `project_id` to PeriodicGCPClient.")

        ep = resolve_gcp_endpoint(
            model,
            project_id=self.project_id,
            preferred_region=preferred_region,
            streaming=False,
        )

        parts: list[dict[str, Any]] = []
        if gcs_attachment_uri:
            parts.append(build_gcs_office_part(gcs_attachment_uri, gcs_mime_type))
        parts.append({"text": prompt})

        gen_cfg: dict[str, Any] = {"thinkingConfig": {"thinkingLevel": thinking_level}}
        if response_schema:
            gen_cfg["responseMimeType"] = "application/json"
            gen_cfg["responseSchema"] = response_schema

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": gen_cfg,
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if enable_google_search:
            payload["tools"] = [{"googleSearch": {}}]

        req = urllib.request.Request(
            ep.endpoint_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._get_bearer_token()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                latency_s = round(time.perf_counter() - t0, 3)
                usage = raw.get("usageMetadata", {})
                prompt_tok = int(usage.get("promptTokenCount", 0) or 0)
                cached_tok = int(usage.get("cachedContentTokenCount", 0) or 0)
                thought_tok = int(usage.get("thoughtsTokenCount", 0) or 0)
                out_tok = int(usage.get("candidatesTokenCount", 0) or 0)
                cost = round(
                    estimate_cost_usd(
                        model,
                        prompt_tokens=prompt_tok,
                        cached_tokens=cached_tok,
                        output_tokens=out_tok,
                        thoughts_tokens=thought_tok,
                    ),
                    6,
                )
                cand_parts = raw.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in cand_parts if not p.get("thought"))
                sig_bytes = max((len(p.get("thoughtSignature", "")) for p in cand_parts), default=0)

                event = TelemetryEvent(
                    model=model,
                    thinking_level=thinking_level,
                    endpoint_region=ep.effective_region,
                    http_status=resp.status,
                    latency_s=latency_s,
                    prompt_tokens=prompt_tok,
                    cached_tokens=cached_tok,
                    thoughts_tokens=thought_tok,
                    output_tokens=out_tok,
                    estimated_list_cost_usd=cost,
                    used_gcs_uri=bool(gcs_attachment_uri),
                    used_google_search=enable_google_search,
                    used_response_schema=bool(response_schema),
                    thought_signature_bytes=sig_bytes,
                )
                self._emit_telemetry(event)
                return {
                    "text": text,
                    "endpoint": ep.model_dump(),
                    "telemetry": event.model_dump(),
                    "grounding_metadata": raw.get("candidates", [{}])[0].get("groundingMetadata"),
                }
        except urllib.error.HTTPError as e:
            latency_s = round(time.perf_counter() - t0, 3)
            body = e.read().decode("utf-8", errors="replace")
            event = TelemetryEvent(
                model=model,
                thinking_level=thinking_level,
                endpoint_region=ep.effective_region,
                http_status=e.code,
                latency_s=latency_s,
                used_gcs_uri=bool(gcs_attachment_uri),
                used_google_search=enable_google_search,
                used_response_schema=bool(response_schema),
            )
            self._emit_telemetry(event)
            raise RuntimeError(f"Gemini 4 HTTP {e.code} on {ep.effective_region}: {body[:300]}") from e

    def _emit_telemetry(self, event: TelemetryEvent) -> None:
        logger.info("gemini4_telemetry %s", event.model_dump_json())
        if not self.bq_telemetry_table:
            return
        try:
            from google.cloud import bigquery

            bq = bigquery.Client(project=self.project_id)
            errors = bq.insert_rows_json(self.bq_telemetry_table, [event.model_dump()])
            if errors:
                logger.warning("BigQuery telemetry insert errors: %s", errors)
        except Exception as exc:
            logger.debug("BigQuery telemetry sink skipped: %s", exc)
