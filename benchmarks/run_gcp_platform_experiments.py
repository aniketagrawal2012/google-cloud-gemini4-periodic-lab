#!/usr/bin/env python3
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
"""Experiment 6: Live Google Cloud Platform Integration Benchmark Suite.

Executes 4 production-realistic GCP platform experiments against live Google Cloud APIs:
  6A. Official Global, Multi-Region (`us`, `eu`), & Single-Region (`europe-west2`, `asia-southeast1`) Data Residency Matrix
  6B. Cloud Storage (`gs://`) Native Binary `.xlsx` & `.docx` Ingestion (`fileData.fileUri`)
  6C. Strict `responseSchema` JSON Determinism Proof (15 calls) + Live Google Search Grounding (3 calls)
  6D. Multi-Turn Function Calling + `thoughtSignature` Continuity + Live BigQuery FinOps Analytics

Usage:
    GOOGLE_CLOUD_PROJECT=your-gcp-project-id \
    GCS_STAGING_BUCKET=your-gcs-bucket \
      python3 benchmarks/run_gcp_platform_experiments.py
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow importing shared OOXML builders & pricing from run_all_experiments.py
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_all_experiments import (  # noqa: E402
    PRICING_LIST_USD_PER_1M,
    build_standards_compliant_docx_bytes,
    build_standards_compliant_xlsx_bytes,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "results" / "gcp_platform_experiments.json"
EXP1_5_RESULTS_PATH = REPO_ROOT / "results" / "live_benchmark_results.json"


def get_access_token() -> str:
    cmd = ["gcloud", "auth", "print-access-token"]
    account = os.environ.get("GOOGLE_CLOUD_ACCOUNT")
    if account:
        cmd.append(f"--account={account}")
    return subprocess.check_output(cmd, text=True).strip()


def make_credentials(token: str) -> Any:
    from google.oauth2.credentials import Credentials

    return Credentials(token=token)


def compute_list_cost(model: str, usage: dict[str, Any]) -> float:
    rates = PRICING_LIST_USD_PER_1M.get(model, PRICING_LIST_USD_PER_1M["gemini-4-carbon"])
    prompt_tok = int(usage.get("promptTokenCount", 0) or 0)
    cached_tok = int(usage.get("cachedContentTokenCount", 0) or 0)
    cand_tok = int(usage.get("candidatesTokenCount", 0) or 0)
    thought_tok = int(usage.get("thoughtsTokenCount", 0) or 0)
    uncached = max(0, prompt_tok - cached_tok)
    return (
        (uncached / 1_000_000.0) * rates["input"]
        + (cached_tok / 1_000_000.0) * rates["cached_input"]
        + ((cand_tok + thought_tok) / 1_000_000.0) * rates["output"]
    )


def call_gemini_region(
    project: str,
    token: str,
    location: str,
    model: str,
    payload: dict[str, Any],
    timeout_s: int = 120,
) -> dict[str, Any]:
    """Call Gemini 4 on global, multi-region (`us`, `eu`), or single-region Google Cloud endpoints.

    Note: Per Google Cloud's official endpoint routing, `global`, `us`, and `eu` use the unified
    `aiplatform.googleapis.com` hostname, whereas single regions (`europe-west2`, `asia-southeast1`)
    use `{region}-aiplatform.googleapis.com`.
    """
    if location in ("global", "us", "eu"):
        host = "https://aiplatform.googleapis.com"
    else:
        host = f"https://{location}-aiplatform.googleapis.com"
    url = (
        f"{host}/v1beta1/projects/{project}/locations/{location}"
        f"/publishers/google/models/{model}:generateContent"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
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
            return {
                "http_status": resp.status,
                "latency_s": latency_s,
                "usage": usage,
                "list_cost_usd": round(compute_list_cost(model, usage), 6),
                "raw": raw,
            }
    except urllib.error.HTTPError as e:
        latency_s = round(time.perf_counter() - t0, 3)
        body = e.read().decode("utf-8", errors="replace")
        try:
            err_msg = json.loads(body).get("error", {}).get("message", body[:240])
        except Exception:
            err_msg = body[:240]
        return {
            "http_status": e.code,
            "latency_s": latency_s,
            "error_message": err_msg[:260],
        }


def extract_text(raw: dict[str, Any]) -> str:
    parts = raw.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


# ---------------------------------------------------------------------------
# 6A: Global vs Single-Region Data Residency Matrix
# ---------------------------------------------------------------------------
def run_exp6a_regional_residency(project: str, token: str) -> dict[str, Any]:
    print("\n=== [EXP 6A] Official Global, Multi-Region (us/eu) & Single-Region Residency Matrix ===")
    locations = ["global", "us", "eu", "europe-west2", "asia-southeast1"]
    models = ["gemini-4-hydrogen", "gemini-4-carbon", "gemini-4-argon"]
    prompt = (
        "In one concise sentence, state which Google Cloud service provides "
        "externally consistent global relational transactions using TrueTime."
    )
    matrix: dict[str, dict[str, Any]] = {}
    calls = 0

    for model in models:
        matrix[model] = {}
        for loc in locations:
            # 3 latency samples for supported lanes, 1 verification call if non-200
            runs = []
            for idx in range(3):
                payload = {
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "thinkingConfig": {"thinkingLevel": "LOW"},
                        "maxOutputTokens": 128,
                    },
                }
                res = call_gemini_region(project, token, loc, model, payload)
                calls += 1
                entry = {
                    "run": idx + 1,
                    "http_status": res["http_status"],
                    "latency_s": res["latency_s"],
                }
                if res["http_status"] == 200:
                    txt = extract_text(res["raw"])
                    entry["mentions_spanner"] = "spanner" in txt.lower()
                    entry["thoughts_tokens"] = int(res["usage"].get("thoughtsTokenCount", 0) or 0)
                    entry["output_tokens"] = int(res["usage"].get("candidatesTokenCount", 0) or 0)
                    entry["list_cost_usd"] = res["list_cost_usd"]
                    runs.append(entry)
                else:
                    entry["error_summary"] = res.get("error_message", "").replace(project, "PROJECT_ID")
                    runs.append(entry)
                    break  # Cleanly proven unsupported in this region; no need to retry

            ok_runs = [r for r in runs if r["http_status"] == 200]
            summary = {
                "supported": len(ok_runs) > 0,
                "http_status": runs[0]["http_status"],
                "sample_count": len(runs),
                "mean_latency_s": round(statistics.mean(r["latency_s"] for r in ok_runs), 3) if ok_runs else None,
                "median_latency_s": round(statistics.median(r["latency_s"] for r in ok_runs), 3) if ok_runs else None,
                "min_latency_s": round(min(r["latency_s"] for r in ok_runs), 3) if ok_runs else None,
                "accuracy_pct": round(100.0 * sum(1 for r in ok_runs if r.get("mentions_spanner")) / len(ok_runs), 1) if ok_runs else None,
                "runs": runs,
            }
            matrix[model][loc] = summary
            print(
                f"  {model:18s} @ {loc:13s} | HTTP {summary['http_status']} | "
                f"supported={str(summary['supported']):5s} | mean={summary['mean_latency_s']}s | p50={summary['median_latency_s']}s"
            )
    return {"total_calls": calls, "matrix": matrix}


# ---------------------------------------------------------------------------
# 6B: Cloud Storage (gs://) Native Binary .xlsx & .docx Ingestion
# ---------------------------------------------------------------------------
def run_exp6b_gcs_office_uri(project: str, token: str, bucket_name: str) -> dict[str, Any]:
    print("\n=== [EXP 6B] Cloud Storage (gs://) Native Binary .xlsx & .docx Ingestion ===")
    from google.cloud import storage

    client = storage.Client(project=project, credentials=make_credentials(token))
    bucket = client.bucket(bucket_name)
    run_id = uuid.uuid4().hex[:8]
    prefix = f"gemini4_periodic_lab_tmp/{run_id}"

    blobs_info = {
        "xlsx": (
            f"{prefix}/q4_cloud_audit.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            build_standards_compliant_xlsx_bytes(),
        ),
        "docx": (
            f"{prefix}/q4_cloud_audit.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            build_standards_compliant_docx_bytes(),
        ),
    }

    uploaded_blobs = []
    results: dict[str, Any] = {}
    calls = 0
    prompt = (
        "Audit the attached Cloud FinOps document from Google Cloud Storage. "
        "Calculate: (1) true sum of US-Central + EU-West + APAC-East, "
        "(2) variance against Reported_Subtotal, and "
        "(3) final adjusted total after applying Unapplied_CUD_Rebate_Credit. "
        "Return strict JSON with integer keys: true_subtotal, variance, final_adjusted_total."
    )

    try:
        for kind, (blob_path, mime, data) in blobs_info.items():
            blob = bucket.blob(blob_path)
            blob.upload_from_string(data, content_type=mime)
            uploaded_blobs.append(blob)
            print(f"  Uploaded {kind} ({len(data)} bytes) to gs://<STAGING_BUCKET>/{blob_path}")

        for model in ["gemini-4-hydrogen", "gemini-4-carbon", "gemini-4-argon"]:
            results[model] = {}
            for kind, (blob_path, mime, data) in blobs_info.items():
                gs_uri = f"gs://{bucket_name}/{blob_path}"
                payload = {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"fileData": {"mimeType": mime, "fileUri": gs_uri}},
                                {"text": prompt},
                            ],
                        }
                    ],
                    "generationConfig": {
                        "thinkingConfig": {"thinkingLevel": "LOW" if model == "gemini-4-hydrogen" else "MEDIUM"},
                        "responseMimeType": "application/json",
                        "responseSchema": {
                            "type": "OBJECT",
                            "properties": {
                                "true_subtotal": {"type": "INTEGER"},
                                "variance": {"type": "INTEGER"},
                                "final_adjusted_total": {"type": "INTEGER"},
                            },
                            "required": ["true_subtotal", "variance", "final_adjusted_total"],
                        },
                    },
                }
                res = call_gemini_region(project, token, "global", model, payload)
                calls += 1
                entry: dict[str, Any] = {
                    "http_status": res["http_status"],
                    "latency_s": res["latency_s"],
                    "file_bytes": len(data),
                    "gcs_uri_pattern": f"gs://<YOUR_BUCKET>/q4_cloud_audit.{kind}",
                }
                if res["http_status"] == 200:
                    txt = extract_text(res["raw"])
                    try:
                        parsed = json.loads(txt)
                    except Exception:
                        parsed = {}
                    passed = (
                        parsed.get("true_subtotal") == 305000
                        and abs(int(parsed.get("variance", 0) or 0)) == 10000
                        and parsed.get("final_adjusted_total") == 300500
                    )
                    entry.update(
                        {
                            "passed": passed,
                            "parsed_json": parsed,
                            "prompt_tokens": int(res["usage"].get("promptTokenCount", 0) or 0),
                            "thoughts_tokens": int(res["usage"].get("thoughtsTokenCount", 0) or 0),
                            "list_cost_usd": res["list_cost_usd"],
                        }
                    )
                else:
                    entry["passed"] = False
                    entry["error_summary"] = res.get("error_message", "").replace(bucket_name, "<YOUR_BUCKET>").replace(project, "PROJECT_ID")

                results[model][kind] = entry
                print(
                    f"  {model:18s} | gs://.{kind} | HTTP {entry['http_status']} | "
                    f"passed={entry.get('passed')} | lat={entry['latency_s']}s | cost=${entry.get('list_cost_usd', 0):.5f}"
                )
    finally:
        for blob in uploaded_blobs:
            try:
                blob.delete()
            except Exception:
                pass
        print("  Cleaned up temporary GCS staging objects.")

    return {"total_calls": calls, "results": results}


# ---------------------------------------------------------------------------
# 6C: Strict responseSchema Determinism Proof + Live Google Search Grounding
# ---------------------------------------------------------------------------
def run_exp6c_schema_and_grounding(project: str, token: str) -> dict[str, Any]:
    print("\n=== [EXP 6C] Strict responseSchema Determinism (15 calls) + Google Search Grounding (3 calls) ===")
    triage_prompt = (
        "Incident telemetry: Cloud Run gateway in us-central1 shows p99 latency rising from 180ms to 62,400ms "
        "strictly on requests routed to `gemini-4-hydrogen:XHIGH` with 38K output tokens, causing 14% client "
        "socket resets at the 60s default ingress proxy timeout. Healthy traffic on `gemini-4-hydrogen:LOW` "
        "(86% of requests) has 0% errors. Classify this incident strictly using the JSON schema."
    )
    triage_schema = {
        "type": "OBJECT",
        "properties": {
            "severity": {"type": "STRING", "enum": ["SEV1", "SEV2", "SEV3"]},
            "primary_root_cause": {
                "type": "STRING",
                "enum": ["PROXY_TIMEOUT_ON_LONG_REASONING", "MODEL_OUTAGE", "IAM_DENIED", "QUOTA_EXHAUSTION"],
            },
            "recommended_action": {
                "type": "STRING",
                "enum": ["ENABLE_ASYNC_INTERACTIONS_BACKGROUND", "ROLLBACK_MODEL_VERSION", "INCREASE_QUOTA", "ROTATE_KEYS"],
            },
            "affected_traffic_pct": {"type": "INTEGER"},
        },
        "required": ["severity", "primary_root_cause", "recommended_action", "affected_traffic_pct"],
    }

    schema_results: dict[str, Any] = {}
    calls = 0

    for model, lvl in [
        ("gemini-4-hydrogen", "LOW"),
        ("gemini-4-carbon", "MEDIUM"),
        ("gemini-4-argon", "MEDIUM"),
    ]:
        outputs = []
        latencies = []
        valid_json = 0
        exact_core_matches = 0
        for run_idx in range(5):
            payload = {
                "contents": [{"role": "user", "parts": [{"text": triage_prompt}]}],
                "generationConfig": {
                    "thinkingConfig": {"thinkingLevel": lvl},
                    "responseMimeType": "application/json",
                    "responseSchema": triage_schema,
                },
            }
            res = call_gemini_region(project, token, "global", model, payload)
            calls += 1
            if res["http_status"] == 200:
                latencies.append(res["latency_s"])
                try:
                    parsed = json.loads(extract_text(res["raw"]))
                    valid_json += 1
                    core_tuple = (
                        parsed.get("primary_root_cause"),
                        parsed.get("recommended_action"),
                        parsed.get("affected_traffic_pct"),
                    )
                    if core_tuple == (
                        "PROXY_TIMEOUT_ON_LONG_REASONING",
                        "ENABLE_ASYNC_INTERACTIONS_BACKGROUND",
                        14,
                    ):
                        exact_core_matches += 1
                    outputs.append(parsed)
                except Exception:
                    outputs.append({"parse_error": True})
        unique_decisions = len({json.dumps(o, sort_keys=True) for o in outputs})
        unique_core = len({(o.get("primary_root_cause"), o.get("recommended_action"), o.get("affected_traffic_pct")) for o in outputs if isinstance(o, dict)})
        schema_results[model] = {
            "thinking_level": lvl,
            "runs": 5,
            "valid_schema_pct": round(100.0 * valid_json / 5, 1),
            "exact_core_decision_pct": round(100.0 * exact_core_matches / 5, 1),
            "unique_full_json_count": unique_decisions,
            "unique_core_action_count": unique_core,
            "mean_latency_s": round(statistics.mean(latencies), 3) if latencies else None,
            "sample_output": outputs[0] if outputs else None,
        }
        print(
            f"  [Schema] {model:18s}:{lvl:6s} | schema={schema_results[model]['valid_schema_pct']}% | "
            f"exact_core={schema_results[model]['exact_core_decision_pct']}% | unique_core={unique_core}/5 | lat={schema_results[model]['mean_latency_s']}s"
        )

    # Part 2: Native Google Search Grounding
    grounding_prompt = (
        "What is the official Google Cloud Model Garden list price per 1M input and output tokens "
        "for Gemini 4 Hydrogen, and what implicit context caching discount percentage does Gemini 4 offer? "
        "Cite official Google Cloud sources."
    )
    grounding_results: dict[str, Any] = {}
    for model, lvl in [
        ("gemini-4-hydrogen", "LOW"),
        ("gemini-4-carbon", "MEDIUM"),
        ("gemini-4-argon", "MEDIUM"),
    ]:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": grounding_prompt}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {
                "thinkingConfig": {"thinkingLevel": lvl},
                "maxOutputTokens": 512,
            },
        }
        res = call_gemini_region(project, token, "global", model, payload)
        calls += 1
        entry: dict[str, Any] = {
            "thinking_level": lvl,
            "http_status": res["http_status"],
            "latency_s": res["latency_s"],
        }
        if res["http_status"] == 200:
            cand = res["raw"].get("candidates", [{}])[0]
            gm = cand.get("groundingMetadata", {})
            queries = gm.get("webSearchQueries", [])
            chunks = gm.get("groundingChunks", [])
            domains = []
            for c in chunks:
                title = c.get("web", {}).get("title", "")
                if title and title not in domains:
                    domains.append(title)
            entry.update(
                {
                    "search_queries_count": len(queries),
                    "search_queries": queries[:4],
                    "grounding_chunks_count": len(chunks),
                    "cited_sources": domains[:5],
                    "list_cost_usd": res["list_cost_usd"],
                    "answer_preview": extract_text(res["raw"])[:220],
                }
            )
        else:
            entry["error_summary"] = res.get("error_message", "").replace(project, "PROJECT_ID")
        grounding_results[model] = entry
        print(
            f"  [Search] {model:18s}:{lvl:6s} | HTTP {entry['http_status']} | "
            f"queries={entry.get('search_queries_count', 0)} | chunks={entry.get('grounding_chunks_count', 0)} | lat={entry['latency_s']}s"
        )

    return {
        "total_calls": calls,
        "response_schema_determinism": schema_results,
        "google_search_grounding": grounding_results,
    }


# ---------------------------------------------------------------------------
# 6D: Multi-Turn Function Calling + thoughtSignature + Live BigQuery Analytics
# ---------------------------------------------------------------------------
def run_exp6d_tools_and_bigquery(project: str, token: str) -> dict[str, Any]:
    print("\n=== [EXP 6D] Multi-Turn Function Calling (thoughtSignature) + Live BigQuery Telemetry ===")
    tools = [
        {
            "functionDeclarations": [
                {
                    "name": "get_spanner_cud_rate",
                    "description": "Retrieve the live Committed Use Discount hourly rate for Cloud Spanner nodes.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "region": {"type": "STRING", "description": "GCP region name, e.g. us-central1"},
                            "commit_years": {"type": "INTEGER", "description": "1 or 3 year CUD"},
                        },
                        "required": ["region", "commit_years"],
                    },
                }
            ]
        }
    ]
    user_turn1 = (
        "Look up the 3-year Cloud Spanner CUD hourly rate in `us-central1` using the tool, "
        "then compute the exact monthly cost for 2 nodes running 730 hours/month (rounded to 2 decimals)."
    )

    tool_results: dict[str, Any] = {}
    calls = 0
    for model, lvl in [
        ("gemini-4-hydrogen", "LOW"),
        ("gemini-4-carbon", "MEDIUM"),
        ("gemini-4-argon", "MEDIUM"),
    ]:
        # Turn 1: Expect functionCall + thoughtSignature
        p1 = {
            "contents": [{"role": "user", "parts": [{"text": user_turn1}]}],
            "tools": tools,
            "generationConfig": {"thinkingConfig": {"thinkingLevel": lvl}},
        }
        r1 = call_gemini_region(project, token, "global", model, p1)
        calls += 1
        if r1["http_status"] != 200:
            tool_results[model] = {"passed": False, "turn1_http": r1["http_status"]}
            continue

        model_content = r1["raw"]["candidates"][0]["content"]
        parts = model_content.get("parts", [])
        fc_part = next((p for p in parts if "functionCall" in p), None)
        sig_lens = [len(p.get("thoughtSignature", "")) for p in parts if p.get("thoughtSignature")]
        has_sig = len(sig_lens) > 0

        if not fc_part:
            tool_results[model] = {"passed": False, "turn1_http": 200, "called_tool": False}
            continue

        fc_name = fc_part["functionCall"]["name"]
        fc_args = fc_part["functionCall"].get("args", {})

        # Turn 2: Echo model_content VERBATIM (preserving thoughtSignature!) + functionResponse
        # Effective rate: $0.432/node-hr * 2 nodes * 730 hrs = $630.72
        p2 = {
            "contents": [
                {"role": "user", "parts": [{"text": user_turn1}]},
                model_content,
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": fc_name,
                                "response": {
                                    "region": fc_args.get("region", "us-central1"),
                                    "commit_years": fc_args.get("commit_years", 3),
                                    "discount_pct": 52,
                                    "effective_hourly_usd_per_node": 0.432,
                                },
                            }
                        }
                    ],
                },
            ],
            "tools": tools,
            "generationConfig": {"thinkingConfig": {"thinkingLevel": lvl}},
        }
        r2 = call_gemini_region(project, token, "global", model, p2)
        calls += 1
        final_txt = extract_text(r2["raw"]) if r2["http_status"] == 200 else ""
        passed = r2["http_status"] == 200 and ("630.72" in final_txt)
        tool_results[model] = {
            "thinking_level": lvl,
            "turn1_http": r1["http_status"],
            "turn2_http": r2["http_status"],
            "called_tool": fc_name,
            "tool_args": fc_args,
            "thought_signature_present": has_sig,
            "thought_signature_bytes": max(sig_lens) if sig_lens else 0,
            "turn1_latency_s": r1["latency_s"],
            "turn2_latency_s": r2["latency_s"],
            "total_roundtrip_s": round(r1["latency_s"] + r2["latency_s"], 3),
            "total_list_cost_usd": round(r1["list_cost_usd"] + r2.get("list_cost_usd", 0.0), 6),
            "passed_exact_630_72": passed,
            "final_answer_preview": final_txt[:180],
        }
        print(
            f"  [ToolLoop] {model:18s}:{lvl:6s} | tool={fc_name} | thoughtSig={tool_results[model]['thought_signature_bytes']}B | "
            f"pass($630.72)={passed} | roundtrip={tool_results[model]['total_roundtrip_s']}s"
        )

    # Part 2: Real Live BigQuery FinOps Telemetry Load + SQL Verification
    from google.cloud import bigquery

    bq_client = bigquery.Client(project=project, credentials=make_credentials(token))
    ds_name = f"gemini4_periodic_lab_tmp_{uuid.uuid4().hex[:6]}"
    ds_ref = bigquery.Dataset(f"{project}.{ds_name}")
    ds_ref.location = "US"
    bq_verification: dict[str, Any] = {}

    try:
        bq_client.create_dataset(ds_ref, exists_ok=True)
        table_id = f"{project}.{ds_name}.exp2_gauntlet_telemetry"

        exp_data = json.loads(EXP1_5_RESULTS_PATH.read_text())
        run_ts = exp_data["metadata"]["timestamp_utc"]
        rows = []
        for t in exp_data["exp2_frontier_gauntlet"]["records"]:
            rows.append(
                {
                    "run_timestamp": run_ts,
                    "model": t["model"],
                    "thinking_level": t["thinking_level"],
                    "task_id": t["task_id"],
                    "domain": t.get("domain", ""),
                    "passed": bool(t["passed"]),
                    "latency_s": float(t["latency_s"]),
                    "prompt_tokens": int(t.get("prompt_tokens", 0) or 0),
                    "thoughts_tokens": int(t.get("thoughts_tokens", 0) or 0),
                    "output_tokens": int(t.get("output_tokens", 0) or 0),
                    "list_cost_usd": float(t.get("list_cost_usd", 0.0) or 0.0),
                    "promo_cost_usd": float(t.get("promo_cost_usd", 0.0) or 0.0),
                }
            )

        job_cfg = bigquery.LoadJobConfig(
            autodetect=True,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        t_load = time.perf_counter()
        load_job = bq_client.load_table_from_json(rows, table_id, job_config=job_cfg)
        load_job.result()
        load_ms = round((time.perf_counter() - t_load) * 1000, 1)

        sql = f"""
        SELECT
          model,
          thinking_level,
          COUNT(*) AS total_tasks,
          COUNTIF(passed) AS passed_tasks,
          ROUND(100.0 * COUNTIF(passed) / COUNT(*), 1) AS accuracy_pct,
          ROUND(AVG(latency_s), 2) AS avg_latency_s,
          ROUND(AVG(thoughts_tokens), 1) AS avg_thoughts,
          ROUND(SUM(list_cost_usd), 4) AS total_list_usd,
          ROUND(SAFE_DIVIDE(SUM(list_cost_usd), NULLIF(COUNTIF(passed), 0)), 4) AS usd_per_correct_answer
        FROM `{table_id}`
        GROUP BY model, thinking_level
        ORDER BY accuracy_pct DESC, usd_per_correct_answer ASC
        """
        t_q = time.perf_counter()
        query_job = bq_client.query(sql)
        sql_rows = [dict(r) for r in query_job.result()]
        query_ms = round((time.perf_counter() - t_q) * 1000, 1)

        bq_verification = {
            "status": "VERIFIED_LIVE",
            "rows_loaded": len(rows),
            "load_duration_ms": load_ms,
            "query_duration_ms": query_ms,
            "total_bytes_processed": int(query_job.total_bytes_processed or 0),
            "top_pareto_leaderboard": sql_rows[:6],
            "all_configs_count": len(sql_rows),
        }
        print(
            f"  [BigQuery] LIVE SQL VERIFIED: {len(rows)} rows loaded ({load_ms}ms), "
            f"query={query_ms}ms, top_value={sql_rows[0]['model']}:{sql_rows[0]['thinking_level']} "
            f"(${sql_rows[0]['usd_per_correct_answer']}/correct @ {sql_rows[0]['accuracy_pct']}%)"
        )
    finally:
        try:
            bq_client.delete_dataset(f"{project}.{ds_name}", delete_contents=True, not_found_ok=True)
            print("  Cleaned up temporary BigQuery staging dataset.")
        except Exception:
            pass

    return {
        "total_calls": calls,
        "multiturn_thought_signature": tool_results,
        "bigquery_finops_analytics": bq_verification,
    }


def main() -> None:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    bucket = os.environ.get("GCS_STAGING_BUCKET")
    if not project or not bucket:
        raise SystemExit("Set GOOGLE_CLOUD_PROJECT and GCS_STAGING_BUCKET environment variables.")

    token = get_access_token()
    t0 = time.perf_counter()

    exp6a = run_exp6a_regional_residency(project, token)
    exp6b = run_exp6b_gcs_office_uri(project, token, bucket)
    exp6c = run_exp6c_schema_and_grounding(project, token)
    exp6d = run_exp6d_tools_and_bigquery(project, token)

    total_calls = (
        exp6a["total_calls"]
        + exp6b["total_calls"]
        + exp6c["total_calls"]
        + exp6d["total_calls"]
    )
    payload = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform": "Google Cloud Gemini Enterprise Agent Platform + Cloud Storage + BigQuery",
        "total_exp6_live_calls": total_calls,
        "cumulative_suite_live_calls": 188 + total_calls,
        "duration_s": round(time.perf_counter() - t0, 2),
        "experiments": {
            "exp6a_regional_residency": exp6a,
            "exp6b_gcs_office_uri": exp6b,
            "exp6c_schema_and_grounding": exp6c,
            "exp6d_tools_and_bigquery": exp6d,
        },
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2))
    print(f"\nDONE! Saved {total_calls} new live GCP platform calls (cumulative {188 + total_calls}) to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
