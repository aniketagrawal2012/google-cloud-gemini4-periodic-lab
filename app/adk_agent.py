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
"""Google Agent Development Kit (ADK) Dynamic Periodic-Element Routing Pattern.

Demonstrates how a production ADK agent dynamically selects Gemini 4 Hydrogen,
Carbon, or Argon per turn via `before_model_callback`, honoring:
- Single-region data residency -> Gemini 4 Argon (`europe-west2` London / `asia-southeast1` Singapore); multi-region `us`/`eu` across all 3 elements
- Native Cloud Storage Office `.xlsx`/`.docx` attachments -> Hydrogen or Carbon
- Static byte-0 prefix hygiene -> protects the 95% implicit cache discount
"""

from __future__ import annotations

from typing import Any

from app.periodic_router import (
    RoutingDecision,
    TaskProfile,
    audit_implicit_cache_prefix,
    select_periodic_route,
    validate_gemini4_request,
)


def periodic_before_model_callback(
    *,
    session_state: dict[str, Any],
    system_instruction: str = "",
) -> dict[str, Any]:
    """Drop-in ADK `before_model_callback` planner returning dynamic model & thinking config.

    Expects optional keys in `session_state`:
      - `complexity`: "routine" | "hard_reasoning" | "frontier_deep"
      - `budget_priority`: "cost_first" | "balanced" | "quality_first"
      - `has_office_attachment`: bool
      - `requires_single_region_ga`: bool
      - `latency_sensitive`: bool
    """
    profile = TaskProfile(
        complexity=session_state.get("complexity", "routine"),
        budget_priority=session_state.get("budget_priority", "balanced"),
        has_office_attachment=bool(session_state.get("has_office_attachment", False)),
        requires_single_region_ga=bool(session_state.get("requires_single_region_ga", False)),
        latency_sensitive=bool(session_state.get("latency_sensitive", False)),
    )
    decision: RoutingDecision = select_periodic_route(profile)
    guard = validate_gemini4_request(
        decision.model,
        thinking_level=decision.thinking_level,
        has_office_attachment=profile.has_office_attachment,
    )
    cache_check = (
        audit_implicit_cache_prefix(system_instruction)
        if system_instruction
        else {"cache_eligible": False, "reason": "no_system_instruction"}
    )
    return {
        "model": decision.model,
        "thinking_level": decision.thinking_level,
        "escalation_ladder": decision.escalation_ladder,
        "rationale": decision.rationale,
        "contract_valid": guard.valid,
        "contract_warnings": guard.warnings,
        "cache_audit": cache_check,
    }


def build_adk_periodic_agent(default_model: str = "gemini-4-hydrogen") -> Any:
    """Instantiate an ADK `LlmAgent` when `google-adk` is installed in the runtime."""
    try:
        from google.adk.agents import LlmAgent  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "Install `google-adk` (`pip install google-adk`) to instantiate LlmAgent directly; "
            "`periodic_before_model_callback` works standalone with zero extra dependencies."
        ) from exc

    return LlmAgent(
        name="gemini4_periodic_finops_agent",
        model=default_model,
        instruction=(
            "You are a Google Cloud FinOps & SRE Reliability Architect. "
            "Always ground tool responses accurately, preserve structured JSON schemas, "
            "and reconcile numeric figures with zero estimation drift."
        ),
        description="Multi-element Gemini 4 enterprise agent routing across Hydrogen, Carbon, and Argon.",
    )
