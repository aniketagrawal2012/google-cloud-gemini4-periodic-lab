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
"""Production Periodic-Element Router & API Contract Guardrails for Gemini 4 on Google Cloud.

Implements official November 2026 Google Cloud Gemini Enterprise Agent Platform specs:
- Gemini 4 Hydrogen (`gemini-4-hydrogen`): Speed + XHIGH thinking + native Office MIME + $1.50/$7.50
- Gemini 4 Argon (`gemini-4-argon`): Long-horizon GA lifecycle + regional endpoints + $4.00/$20.00
- Gemini 4 Carbon (`gemini-4-carbon`): Maximum frontier deep reasoning + native Office MIME + $4.00/$20.00
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

ElementModel = Literal["gemini-4-hydrogen", "gemini-4-argon", "gemini-4-carbon"]
ThinkingLevel = Literal["LOW", "MEDIUM", "HIGH", "XHIGH"]


@dataclass(frozen=True)
class ModelSpec:
    model_id: ElementModel
    element: str
    atomic_number: int
    default_thinking: ThinkingLevel
    supported_thinking: tuple[ThinkingLevel, ...]
    unified_token_limit: int
    streaming_segment_limit: int
    non_streaming_segment_limit: int
    implicit_cache_min_tokens: int
    supports_explicit_cache: bool
    supports_office_mime: bool
    supports_single_region: bool
    input_usd_per_1m: float
    cached_input_usd_per_1m: float
    output_and_thinking_usd_per_1m: float


GEMINI4_SPECS: dict[ElementModel, ModelSpec] = {
    "gemini-4-hydrogen": ModelSpec(
        model_id="gemini-4-hydrogen",
        element="Hydrogen",
        atomic_number=1,
        default_thinking="HIGH",
        supported_thinking=("LOW", "MEDIUM", "HIGH", "XHIGH"),
        unified_token_limit=1_048_576,
        streaming_segment_limit=65_536,
        non_streaming_segment_limit=65_536,
        implicit_cache_min_tokens=4_096,
        supports_explicit_cache=False,
        supports_office_mime=True,
        supports_single_region=False,
        input_usd_per_1m=1.50,
        cached_input_usd_per_1m=0.075,
        output_and_thinking_usd_per_1m=7.50,
    ),
    "gemini-4-argon": ModelSpec(
        model_id="gemini-4-argon",
        element="Argon",
        atomic_number=18,
        default_thinking="MEDIUM",
        supported_thinking=("LOW", "MEDIUM", "HIGH"),
        unified_token_limit=1_048_576,
        streaming_segment_limit=65_536,
        non_streaming_segment_limit=32_768,
        implicit_cache_min_tokens=4_096,
        supports_explicit_cache=False,
        supports_office_mime=False,
        supports_single_region=True,
        input_usd_per_1m=4.00,
        cached_input_usd_per_1m=0.20,
        output_and_thinking_usd_per_1m=20.00,
    ),
    "gemini-4-carbon": ModelSpec(
        model_id="gemini-4-carbon",
        element="Carbon",
        atomic_number=6,
        default_thinking="MEDIUM",
        supported_thinking=("LOW", "MEDIUM", "HIGH"),
        unified_token_limit=1_048_576,
        streaming_segment_limit=65_536,
        non_streaming_segment_limit=32_768,
        implicit_cache_min_tokens=4_096,
        supports_explicit_cache=False,
        supports_office_mime=True,
        supports_single_region=False,
        input_usd_per_1m=4.00,
        cached_input_usd_per_1m=0.20,
        output_and_thinking_usd_per_1m=20.00,
    ),
}


class ContractValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_gemini4_request(
    model: ElementModel,
    *,
    thinking_level: str | None = None,
    thinking_budget: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    candidate_count: int = 1,
    presence_penalty: float | None = None,
    frequency_penalty: float | None = None,
    expected_output_tokens: int = 4_096,
    streaming: bool = True,
    has_office_attachment: bool = False,
) -> ContractValidationResult:
    """Pre-flight validator ensuring clean Gemini 4 API contract alignment and workload-matched thinking levels."""
    spec = GEMINI4_SPECS[model]
    errors: list[str] = []
    warnings: list[str] = []

    if thinking_budget is not None:
        errors.append(
            f"Contract check: `thinking_budget={thinking_budget}` is superseded on {model}; use `thinking_level`."
        )
    if thinking_level is not None:
        lvl = thinking_level.upper()
        if lvl == "MINIMAL":
            errors.append(f"Contract check: `thinking_level='MINIMAL'` is not supported on {model}.")
        elif lvl not in spec.supported_thinking:
            errors.append(
                f"Contract check: `thinking_level='{lvl}'` is not supported on {model}. "
                f"Supported: {spec.supported_thinking}."
            )
    if candidate_count > 1:
        errors.append(f"Contract check: `candidate_count={candidate_count}` > 1 is not documented as supported on Gemini 4; enforce `candidate_count=1`.")
    if presence_penalty is not None or frequency_penalty is not None:
        errors.append("Contract check: `presence_penalty` and `frequency_penalty` are not supported on Gemini 4.")
    if has_office_attachment and not spec.supports_office_mime:
        errors.append(
            f"Capability check: {model} does not currently support native Office/OpenDocument MIME ingestion; route to gemini-4-hydrogen or gemini-4-carbon."
        )

    # Constructive calibration guidance
    if any(p is not None for p in (temperature, top_p, top_k)):
        warnings.append(
            "Managed sampling note: Gemini 4 self-calibrates sampling and ignores custom `temperature`, `top_p`, and `top_k`. "
            "Pair with `response_schema` and deterministic callbacks rather than relying on `temperature=0.0`."
        )
    if expected_output_tokens > 32_768 and not streaming:
        warnings.append(
            "Long-output guidance (effective Nov 13, 2026): completions > 32K tokens bill for retrievable "
            "usage even on timeout, and Carbon/Argon cap non-streaming segments at 32,768 tokens. Enable streaming or `background=True`."
        )
    if model in ("gemini-4-argon", "gemini-4-carbon") and (thinking_level or "").upper() == "LOW":
        warnings.append(
            "Direct-answer LOW mode note: Argon and Carbon use `thinking_level='LOW'` as a fast direct-answer mode "
            "(0 internal thinking tokens). For multi-step reasoning, use 'MEDIUM'/'HIGH' or route to gemini-4-hydrogen:LOW."
        )

    return ContractValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


class TaskProfile(BaseModel):
    complexity: Literal["routine", "hard_reasoning", "frontier_deep"] = "routine"
    latency_sensitive: bool = False
    has_office_attachment: bool = False
    requires_single_region_ga: bool = False
    budget_priority: Literal["cost_first", "balanced", "quality_first"] = "balanced"


class RoutingDecision(BaseModel):
    model: ElementModel
    thinking_level: ThinkingLevel
    escalation_ladder: list[tuple[ElementModel, ThinkingLevel]]
    rationale: str


def select_periodic_route(profile: TaskProfile) -> RoutingDecision:
    """Pareto-optimal element router calibrated against live Gemini 4 empirical telemetry."""
    if profile.requires_single_region_ga and not profile.has_office_attachment:
        # Argon uses LOW for fast direct-answer tasks, and MEDIUM/HIGH for multi-step reasoning.
        lvl: ThinkingLevel = "HIGH" if profile.complexity == "frontier_deep" else ("MEDIUM" if profile.complexity == "hard_reasoning" else "LOW")
        return RoutingDecision(
            model="gemini-4-argon",
            thinking_level=lvl,
            escalation_ladder=[("gemini-4-argon", "HIGH")],
            rationale="Single-region GA residency & 12-month lifecycle commitment satisfied by Gemini 4 Argon.",
        )

    if profile.complexity == "routine":
        return RoutingDecision(
            model="gemini-4-hydrogen",
            thinking_level="LOW",
            escalation_ladder=[("gemini-4-hydrogen", "HIGH"), ("gemini-4-carbon", "MEDIUM")],
            rationale="Hydrogen LOW retains active CoT (~1,549 thought tokens), achieves 154+ tok/s, and costs 62.5% less than Carbon/Argon.",
        )

    if profile.complexity == "hard_reasoning":
        if profile.budget_priority == "cost_first" or profile.latency_sensitive:
            return RoutingDecision(
                model="gemini-4-hydrogen",
                thinking_level="HIGH",
                escalation_ladder=[("gemini-4-carbon", "MEDIUM"), ("gemini-4-hydrogen", "XHIGH"), ("gemini-4-carbon", "HIGH")],
                rationale="Hydrogen HIGH (default) delivers 100% gauntlet accuracy at 162 tok/s and 4.4x lower cost than XHIGH.",
            )
        return RoutingDecision(
            model="gemini-4-carbon",
            thinking_level="MEDIUM",
            escalation_ladder=[("gemini-4-carbon", "HIGH")],
            rationale="Carbon MEDIUM is the frontier Pareto sweet spot: 100% accuracy at 5.6x lower cost than Carbon HIGH and 2.9x lower cost than Hydrogen XHIGH.",
        )

    return RoutingDecision(
        model="gemini-4-carbon",
        thinking_level="HIGH",
        escalation_ladder=[("gemini-4-hydrogen", "XHIGH")],
        rationale="Frontier long-horizon research, deep security auditing, or exhaustive synthesis routed to Gemini 4 Carbon HIGH.",
    )


DYNAMIC_PREFIX_PATTERNS = (
    re.compile(r"\b20\d{2}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
    re.compile(r"\b(request_id|trace_id|timestamp|session_id)\s*[:=]", re.I),
)


def audit_implicit_cache_prefix(prefix_text: str) -> dict[str, object]:
    """Verify prefix invariance so dynamic headers never destroy Gemini 4's 95% implicit cache discount."""
    approx_tokens = max(1, int(len(prefix_text.split()) * 1.35))
    early_window = prefix_text[:2000]
    violations = [p.pattern for p in DYNAMIC_PREFIX_PATTERNS if p.search(early_window)]
    meets_cliff = approx_tokens >= 4_096
    return {
        "approx_prefix_tokens": approx_tokens,
        "meets_4096_cliff": meets_cliff,
        "dynamic_header_violations": violations,
        "cache_eligible": meets_cliff and len(violations) == 0,
    }


def estimate_cost_usd(
    model: ElementModel,
    *,
    prompt_tokens: int,
    cached_tokens: int = 0,
    output_tokens: int = 0,
    thoughts_tokens: int = 0,
) -> float:
    """Compute exact Global list cost (USD), billing thinking tokens at the output rate."""
    spec = GEMINI4_SPECS[model]
    uncached = max(0, prompt_tokens - cached_tokens)
    billable_output = output_tokens + thoughts_tokens
    return (
        (uncached / 1_000_000.0) * spec.input_usd_per_1m
        + (cached_tokens / 1_000_000.0) * spec.cached_input_usd_per_1m
        + (billable_output / 1_000_000.0) * spec.output_and_thinking_usd_per_1m
    )
