-- Copyright 2026 Google LLC
-- Licensed under the Apache License, Version 2.0
--
-- Production BigQuery FinOps & Reliability Telemetry DDL for Gemini 4 Periodic Router.
-- Verified live on Google Cloud BigQuery in Experiment 6D.
-- Replace `your-gcp-project.gemini4_finops` with your target project and dataset.

CREATE SCHEMA IF NOT EXISTS `your-gcp-project.gemini4_finops`
OPTIONS (location = 'US');

CREATE TABLE IF NOT EXISTS `your-gcp-project.gemini4_finops.router_telemetry` (
  event_timestamp TIMESTAMP NOT NULL,
  model STRING NOT NULL,
  thinking_level STRING NOT NULL,
  endpoint_region STRING NOT NULL,
  task_id STRING,
  domain STRING,
  http_status INT64 NOT NULL,
  passed BOOL,
  latency_s FLOAT64 NOT NULL,
  prompt_tokens INT64 DEFAULT 0,
  cached_tokens INT64 DEFAULT 0,
  thoughts_tokens INT64 DEFAULT 0,
  output_tokens INT64 DEFAULT 0,
  list_cost_usd FLOAT64 NOT NULL,
  promo_cost_usd FLOAT64,
  used_gcs_uri BOOL DEFAULT FALSE,
  used_google_search BOOL DEFAULT FALSE,
  used_response_schema BOOL DEFAULT FALSE,
  thought_signature_bytes INT64 DEFAULT 0
)
PARTITION BY DATE(event_timestamp)
CLUSTER BY model, thinking_level, endpoint_region;

-- View 1: Pareto Cost-Per-Correct-Answer Leaderboard across Elements & Thinking Tiers
CREATE OR REPLACE VIEW `your-gcp-project.gemini4_finops.v_pareto_cost_per_correct_answer` AS
SELECT
  model,
  thinking_level,
  COUNT(*) AS total_tasks,
  COUNTIF(passed) AS passed_tasks,
  ROUND(100.0 * COUNTIF(passed) / COUNT(*), 1) AS accuracy_pct,
  ROUND(AVG(latency_s), 2) AS avg_latency_s,
  ROUND(AVG(thoughts_tokens), 1) AS avg_thoughts_tokens,
  ROUND(SUM(list_cost_usd), 4) AS total_list_usd,
  ROUND(SAFE_DIVIDE(SUM(list_cost_usd), NULLIF(COUNTIF(passed), 0)), 4) AS usd_per_correct_answer
FROM `your-gcp-project.gemini4_finops.router_telemetry`
WHERE passed IS NOT NULL
GROUP BY model, thinking_level
ORDER BY accuracy_pct DESC, usd_per_correct_answer ASC;

-- View 2: 95% Implicit Durable Cache ROI & Prefix Hygiene Monitor
CREATE OR REPLACE VIEW `your-gcp-project.gemini4_finops.v_implicit_cache_roi_by_element` AS
SELECT
  model,
  COUNT(*) AS total_calls,
  SUM(prompt_tokens) AS total_prompt_tokens,
  SUM(cached_tokens) AS total_cached_tokens,
  ROUND(100.0 * SAFE_DIVIDE(SUM(cached_tokens), NULLIF(SUM(prompt_tokens), 0)), 2) AS effective_cache_hit_pct,
  ROUND(SUM(list_cost_usd), 4) AS actual_spend_usd
FROM `your-gcp-project.gemini4_finops.router_telemetry`
WHERE prompt_tokens >= 4096
GROUP BY model
ORDER BY effective_cache_hit_pct DESC;

-- View 3: Single-Region Data Residency & Latency SLA Tracker (Argon vs Global)
CREATE OR REPLACE VIEW `your-gcp-project.gemini4_finops.v_regional_residency_sla` AS
SELECT
  model,
  endpoint_region,
  COUNT(*) AS total_requests,
  ROUND(100.0 * COUNTIF(http_status = 200) / COUNT(*), 2) AS success_rate_pct,
  ROUND(APPROX_QUANTILES(latency_s, 100)[OFFSET(50)], 3) AS p50_latency_s,
  ROUND(APPROX_QUANTILES(latency_s, 100)[OFFSET(95)], 3) AS p95_latency_s
FROM `your-gcp-project.gemini4_finops.router_telemetry`
GROUP BY model, endpoint_region
ORDER BY model, endpoint_region;
