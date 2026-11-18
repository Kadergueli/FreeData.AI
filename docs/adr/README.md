# Architecture Decision Records (ADRs)

This directory documents major architectural decisions evidenced in the FreeData.AI codebase.

| ID | Title | Status | Primary Evidence |
| :--- | :--- | :--- | :--- |
| [ADR-001](ADR-001-deterministic-engine-and-qa-gate.md) | Deterministic Financial/ML Engines & Zero-Fabrication QA Gate | Accepted | `src/business_engine.py`, `src/ai_agent.py`, `src/reports/qa_validator.py` |
| [ADR-002](ADR-002-modular-monolith-and-model-routing.md) | Modular Multi-Domain Monolith & Centralized Model Routing | Accepted | `api/server.py`, `src/domains.py`, `src/ai_infra.py` |
| [ADR-003](ADR-003-hybrid-rag-and-owner-isolation.md) | Hybrid BM25 + Vector RAG with Owner-Scoped Isolation | Accepted | `src/rag_engine.py`, `src/security.py`, `scripts/build_vector_store.py` |
| [ADR-004](ADR-004-provider-independent-monetization.md) | Provider-Independent Subscriptions & Backend Entitlements | Accepted | `src/monetization.py`, `src/entitlements.py`, `sql/11_subscriptions_and_usage_metering.sql` |
| [ADR-005](ADR-005-isolated-research-framework.md) | Separation of Experimental Research from Production Models | Accepted | `src/research/experiment_tracker.py`, `src/research/benchmarks.py` |

