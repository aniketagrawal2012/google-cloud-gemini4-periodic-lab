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
"""Unit tests for the Gemini 4 Periodic Element Router and Contract Validators."""

from app.periodic_router import (
    GEMINI4_SPECS,
    TaskProfile,
    audit_implicit_cache_prefix,
    estimate_cost_usd,
    select_periodic_route,
    validate_gemini4_request,
)


def test_hydrogen_exclusive_xhigh_and_non_streaming_cap() -> None:
    assert "XHIGH" in GEMINI4_SPECS["gemini-4-hydrogen"].supported_thinking
    assert "XHIGH" not in GEMINI4_SPECS["gemini-4-argon"].supported_thinking
    assert "XHIGH" not in GEMINI4_SPECS["gemini-4-carbon"].supported_thinking
    assert GEMINI4_SPECS["gemini-4-hydrogen"].non_streaming_segment_limit == 65_536
    assert GEMINI4_SPECS["gemini-4-carbon"].non_streaming_segment_limit == 32_768


def test_contract_validator_catches_all_http_400_traps() -> None:
    r1 = validate_gemini4_request("gemini-4-hydrogen", thinking_budget=1024)
    assert not r1.valid and any("thinking_budget" in e for e in r1.errors)

    r2 = validate_gemini4_request("gemini-4-argon", thinking_level="XHIGH")
    assert not r2.valid and any("XHIGH" in e for e in r2.errors)

    r3 = validate_gemini4_request("gemini-4-carbon", thinking_level="MINIMAL")
    assert not r3.valid and any("MINIMAL" in e for e in r3.errors)

    r4 = validate_gemini4_request("gemini-4-argon", has_office_attachment=True)
    assert not r4.valid and any("Office" in e for e in r4.errors)

    r5 = validate_gemini4_request("gemini-4-hydrogen", thinking_level="XHIGH", temperature=0.0)
    assert r5.valid and len(r5.warnings) == 1 and "silently ignored" in r5.warnings[0]


def test_periodic_router_pareto_selection() -> None:
    d_routine = select_periodic_route(TaskProfile(complexity="routine", latency_sensitive=True))
    assert d_routine.model == "gemini-4-hydrogen" and d_routine.thinking_level == "LOW"

    d_hard_cost = select_periodic_route(TaskProfile(complexity="hard_reasoning", budget_priority="cost_first"))
    assert d_hard_cost.model == "gemini-4-hydrogen" and d_hard_cost.thinking_level == "HIGH"
    assert ("gemini-4-carbon", "MEDIUM") in d_hard_cost.escalation_ladder

    d_hard_bal = select_periodic_route(TaskProfile(complexity="hard_reasoning", budget_priority="balanced"))
    assert d_hard_bal.model == "gemini-4-carbon" and d_hard_bal.thinking_level == "MEDIUM"

    d_frontier = select_periodic_route(TaskProfile(complexity="frontier_deep"))
    assert d_frontier.model == "gemini-4-carbon" and d_frontier.thinking_level == "HIGH"

    d_regional = select_periodic_route(TaskProfile(complexity="hard_reasoning", requires_single_region_ga=True))
    assert d_regional.model == "gemini-4-argon" and d_regional.thinking_level == "MEDIUM"


def test_argon_carbon_low_zero_thought_cliff_warning() -> None:
    r_c = validate_gemini4_request("gemini-4-carbon", thinking_level="LOW")
    assert r_c.valid and any("Zero-thought accuracy cliff" in w for w in r_c.warnings)
    r_h = validate_gemini4_request("gemini-4-hydrogen", thinking_level="LOW")
    assert r_h.valid and not any("Zero-thought accuracy cliff" in w for w in r_h.warnings)


def test_implicit_cache_prefix_sabotage_detection() -> None:
    stable_corpus = " ".join(["architecture policy governance"] * 1200)
    clean = audit_implicit_cache_prefix(stable_corpus)
    assert clean["meets_4096_cliff"] is True
    assert clean["cache_eligible"] is True

    sabotaged = "REQUEST_TS=2026-11-14T00:45:00Z\n" + stable_corpus
    bad = audit_implicit_cache_prefix(sabotaged)
    assert bad["cache_eligible"] is False
    assert len(bad["dynamic_header_violations"]) >= 1


def test_95_percent_cached_discount_and_thinking_billing() -> None:
    # 1M cached input on Hydrogen = $0.075 (95% off $1.50), 1M thinking tokens = $7.50
    cost_h = estimate_cost_usd(
        "gemini-4-hydrogen",
        prompt_tokens=1_000_000,
        cached_tokens=1_000_000,
        output_tokens=0,
        thoughts_tokens=1_000_000,
    )
    assert abs(cost_h - 7.575) < 1e-6

    # 1M cached input on Carbon = $0.20 (95% off $4.00)
    cost_c = estimate_cost_usd(
        "gemini-4-carbon",
        prompt_tokens=1_000_000,
        cached_tokens=1_000_000,
        output_tokens=500_000,
        thoughts_tokens=500_000,
    )
    assert abs(cost_c - 20.20) < 1e-6
