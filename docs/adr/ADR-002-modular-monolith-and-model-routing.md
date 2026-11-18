# ADR-002: Modular Multi-Domain Monolith & Centralized Model Routing

- **Status:** Accepted
- **Evidence in Repo:** `api/server.py`, `src/domains.py`, `src/ai_infra.py`, `src/orchestrator_ml_rag.py`

## Context
FreeData.AI expanded from agricultural market forecasting into 10 specialized domains (`general_ai`, `education`, `academic_research`, `business_entrepreneurship`, `finance`, `data_science`, `agriculture`, `tech_programming`, `productivity`, `chad_intelligence`) deployed on Render + Supabase + Firebase Hosting.

## Problem
Splitting 10 domains into separate microservices would multiply operational cost and latency without traffic justification, while calling one expensive LLM for every task would inflate API costs.

## Options Considered
1. Microservices per domain/engine.
2. Single FastAPI modular monolith with `DomainRegistry` and `ModelRouter`.

## Decision
Keep a modular FastAPI monolith (`api/server.py`) with `DomainRegistry` (`src/domains.py`) for domain-specific tool/knowledge scoping and `ModelRouter` (`src/ai_infra.py`) to route tasks between zero-cost deterministic ML (`ridge_kmeans_classifier`), lightweight LLM (`llama-3.1-8b-instant`), and premium reasoning LLM (`llama-3.3-70b-versatile`) with TTL caching and fallback.

## Consequences
- **Positive:** Low infrastructure overhead, single CI/CD pipeline (`.github/workflows/ci.yml`), and clear cost control by subscription tier.
- **Trade-off:** Heavy synchronous PDF/ML workloads share the web process unless offloaded via `ReportJobManager` (`src/reports/jobs.py`).

