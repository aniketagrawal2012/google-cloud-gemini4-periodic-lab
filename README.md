# Google Cloud Gemini 4 Periodic Table Lab (`Hydrogen` · `Carbon` · `Argon`)

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-38BDF8.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/pytest-6%2F6%20passing-10B981.svg)](tests/test_periodic_router.py)
[![Platform](https://img.shields.io/badge/Google%20Cloud-Gemini%20Enterprise%20Agent%20Platform-4285F4.svg)](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/get-started-with-gemini-4)

**188 live empirical experiments** characterizing Google Cloud's November 2026 **Gemini 4 Periodic Table** — **Gemini 4 Hydrogen (`gemini-4-hydrogen`)**, **Gemini 4 Carbon (`gemini-4-carbon`)**, and **Gemini 4 Argon (`gemini-4-argon`)** — alongside a **Gemini 3.8 Flash** baseline on the global **Gemini Enterprise Agent Platform (`v1beta1`)**, paired with a production-ready **Periodic Element Router & Pre-Flight Contract Guardrail** (`app/periodic_router.py`).

![The Periodic Table of Gemini 4 on Google Cloud](docs/figures/fig1_periodic_table_hero.gif)

---

## Key Architectural Insights (188 Live Global API Calls — Nov 14, 2026)

Every metric in this repository is recorded verbatim in [`results/live_benchmark_results.json`](results/live_benchmark_results.json) and visualized directly by [`benchmarks/generate_figures.py`](benchmarks/generate_figures.py). All three Gemini 4 models achieved **100% (8/8)** when matched to their intended reasoning tier.

| # | Architectural Insight | Live Empirical Evidence |
|---|---|---|
| **1** | **Workload-Specialized `LOW` Calibration** | On `gemini-4-argon` and `gemini-4-carbon`, `LOW` serves as an ultra-fast direct-answer mode (`0.0` thoughts, `5.01s` on Argon @ `$0.0105` promo) for low-latency non-reasoning tasks, while `MEDIUM`/`HIGH` unlock full reasoning (`100%` on `Carbon:MEDIUM` and `Argon:HIGH`). `gemini-4-hydrogen:LOW` keeps active chain-of-thought (`1,549.0` avg thoughts) and hits **`100.0%` (8/8)** in `11.43s` for **`$0.10059`**. |
| **2** | **`Carbon:MEDIUM` Frontier Efficiency Sweet Spot** | At its documented default `MEDIUM` setting, **`gemini-4-carbon:MEDIUM`** achieved **`8/8 (100%)`** using just `1,419.9` average thoughts — costing **`$0.24783` list / `$0.12391` under the Nov 2026 50% promo credit** (**2.9×–5.9× more economical** than escalating to `Hydrogen:XHIGH`). |
| **3** | **Hydrogen's 2.5× Decode Lead & Async `XHIGH` Guidance** | Steady-state visible SSE throughput reached **`154.3–165.6 tok/s`** on Hydrogen vs **`53.0–82.0 tok/s`** on Argon and **`82.2–88.5 tok/s`** on Carbon. Deep-verification tiers (`Hydrogen:XHIGH` with `48,841` thoughts / `303.55s`, `Carbon:HIGH` at `265.10s`) and buffered `Carbon:MEDIUM` (`86.33s` → `0.20s` burst) pair cleanly with `background=True` via the Interactions API. |
| **4** | **Argon's Enterprise Regional & 12-Month GA Lane** | Sharing the `$4/$20` tariff (and Nov-2026 50% promo credit: `$0.0464` on `MEDIUM`, `$0.2264` on `HIGH`), **`gemini-4-argon`** uniquely provides **single-region data residency** (`us-central1`, `europe-west4`, etc.) and a **12-month GA lifecycle guarantee (Oct 2027+)**. |
| **5** | **95% Implicit Durable Cache & 16,384-Token Blocks** | Above the 4,096-token minimum (`19,362`-token static `system_instruction`), Hydrogen locked onto **`16,384` cached tokens (`84.62%`, `4 × 4,096` blocks)** on Calls 5–6, reducing turn cost **76.6% (`$0.0306 → $0.0072`)** via the **95% cache discount (`$0.075/1M`)**. Keeping dynamic timestamps out of byte 0 preserves the full savings. |
| **6** | **Structured `+31` / `+4` Framing & Managed Sampling** | All three Gemini 4 elements share an exact **`+31` input / `+4` output** framing envelope vs `gemini-3.8-flash` (`R² = 1.0000`) and self-calibrate sampling internally per official docs (ignoring `temperature=0.0`), making `responseSchema` and Gen AI Evaluation Service the ideal repeatability primitives. |
| **7** | **Native Binary `.xlsx` & `.docx` Ingestion + OOXML Tip** | Raw binary `.xlsx` and `.docx` via `inlineData` passed **100% (`HTTP 200`)** on Hydrogen (`4.64s`/`4.23s`) and Carbon (`9.51s`/`7.74s`) with zero Python parsers, while Argon cleanly validates Office MIME with `HTTP 400`. Ensure synthetic `.xlsx` archives include standard `xl/styles.xml` and `xl/sharedStrings.xml`. |

---

## Experiment 2: 8-Task Multi-Step Evaluation Summary (88 Live Calls)

| Model | Thinking Level | Score | Accuracy | Avg Latency | Avg Thoughts | List Cost (USD) | Nov-2026 Promo (USD) |
|---|---|---:|---:|---:|---:|---:|---:|
| **`gemini-4-hydrogen`** | **`LOW`** ★ | **8/8** | **100.0%** | **11.43s** | 1,549.0 | **$0.10059** | $0.10059 |
| `gemini-4-hydrogen` | `MEDIUM` | 7/8 | 87.5% | 18.37s | 2,707.0 | $0.17016 | $0.17016 |
| `gemini-4-hydrogen` | `HIGH` (default) | **8/8** | **100.0%** | 18.19s | 2,608.8 | $0.16431 | $0.16431 |
| `gemini-4-hydrogen` | `XHIGH` (exclusive) | **8/8** | **100.0%** | 77.57s | 11,984.0 | $0.72746 | $0.72746 |
| `gemini-4-argon` | `LOW` (direct-answer) | 3/8 | 37.5% | **5.01s** | 0.0 | $0.02091 | $0.01045 |
| `gemini-4-argon` | `MEDIUM` (default) | 7/8 | 87.5% | 9.83s | 427.9 | $0.09277 | $0.04638 |
| **`gemini-4-argon`** | **`HIGH`** ★ (regional GA) | **8/8** | **100.0%** | 38.82s | 2,678.2 | $0.45281 | $0.22640 |
| `gemini-4-carbon` | `LOW` (direct-answer) | 3/8 | 37.5% | 10.22s | 0.0 | $0.02171 | $0.01085 |
| **`gemini-4-carbon`** | **`MEDIUM` (default)** ★ | **8/8** | **100.0%** | **27.49s** | 1,419.9 | **$0.24783** | **$0.12391** |
| `gemini-4-carbon` | `HIGH` | **8/8** | **100.0%** | 101.86s | 8,487.6 | $1.38059 | $0.69029 |
| `gemini-3.8-flash` | `MEDIUM` | 7/8 | 87.5% | 12.42s | 2,196.1 | $0.13851 | $0.06926 |

![Thinking-Level Calibration & Pareto Frontier](docs/figures/fig2_low_cliff_and_pareto_frontier.png)

---

## Repository Structure

```text
google-cloud-gemini4-periodic-lab/
├── app/
│   ├── __init__.py
│   └── periodic_router.py         # Empirically calibrated PeriodicElementRouter, contract guard, & cache auditor
├── benchmarks/
│   ├── run_all_experiments.py     # Checkpointed 5-experiment live Google Cloud v1beta1 benchmark suite
│   └── generate_figures.py        # Reproduces all 7 publication-grade visuals directly from live JSON
├── results/
│   └── live_benchmark_results.json # Complete raw telemetry from 188 live global GCP calls
├── docs/
│   ├── index.html                 # Full rich-media technical article (Medium-ready single source)
│   └── figures/                   # 3 animated GIFs + 4 high-DPI scientific PNGs
├── tests/
│   └── test_periodic_router.py    # 6 unit tests verifying contracts, routing, cache hygiene, & 95% pricing
├── pyproject.toml
└── LICENSE                        # Apache-2.0
```

---

## Quickstart & Reproduction

### 1. Run Unit Tests (No GCP Billing Required)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

### 2. Reproduce All 5 Live Experiments on Google Cloud
```bash
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
python3 -u benchmarks/run_all_experiments.py
# Or resume from saved per-experiment checkpoints:
python3 -u benchmarks/run_all_experiments.py --resume
```

### 3. Regenerate All 7 Visuals from `results/live_benchmark_results.json`
```bash
python3 -u benchmarks/generate_figures.py
```

---

## Official Google Cloud Documentation References

- [Get Started with Gemini 4](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/get-started-with-gemini-4)
- [Gemini 4 Hydrogen Model Card](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-hydrogen) & [Developer Guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-4-hydrogen)
- [Gemini 4 Carbon Model Card](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-carbon) & [Developer Guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-4-carbon)
- [Gemini 4 Argon Model Card](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-argon) & [Developer Guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-4-argon)
- [Gemini Thinking & `thinking_level` Reference](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking)
- [Context Caching Overview (Implicit Durable Caching)](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/context-cache/context-cache-overview)
- [Interactions API (`background=True` for Long Outputs)](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/interactions)
- [Model Versions & Lifecycle Schedule](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions)
- [Google Cloud Model Garden Pricing](https://cloud.google.com/model-garden/pricing)
- [Gen AI Evaluation Service Overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluation-overview)
- [Agent Engine Scale & Runtime](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale)
- [Google Agent Development Kit (ADK)](https://adk.dev/)

---

## License

Apache License 2.0 — see [LICENSE](LICENSE). Built by [Aniket Agrawal](https://www.linkedin.com/in/aniket-agrawal-a18990266/).
