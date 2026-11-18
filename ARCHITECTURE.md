# FreeData.AI — Architecture

## System Overview

```mermaid
flowchart LR
    UI[Flutter Web App\nChatScreen + ProjectsScreen] -->|HTTPS + X-User-Id / X-Premium-Key| API[FastAPI API\napi/server.py]
    API --> OBS[Observability Middleware\nX-Request-Id, Latency, Metrics]
    API --> CHAT[Chat Engine\nsrc/ai_agent.py]
    CHAT --> CTX[StudyContext\nsrc/study_context.py]
    CHAT --> BE[Deterministic Business Engine\nsrc/business_engine.py]
    API --> SB[Study Builder\nsrc/reports/study_builder.py]
    SB --> ORCH[ReportOrchestrator\nsrc/reports/orchestrator.py]
    ORCH --> ENG[Analytical & Provenance Engines\nsrc/reports/engines.py + sections.py]
    SB --> QA[QA Validator\nsrc/reports/qa_validator.py]
    ORCH --> PDF[PDFRenderer ReportLab\nsrc/reports/pdf_generator.py]
    API --> JOBS[ReportJobManager\nsrc/reports/jobs.py]
    API --> STORE[ProjectStore SQLite / SQL 10\nsrc/projects/store.py]
    API --> SUPA[(Supabase PostgreSQL + RAG)]
```

## Main Data Flows

1. **Chat & Context Persistence**: `ChatScreen` sends `message`, `history`, and `_latestStudyContext()` to `POST /api/v1/chat`. `extract_client_state()` updates `StudyContext` across all turns and returns `client_state["study_context"]`.
2. **Market Study & PDF Pipeline**: `POST /api/v1/reports/market-study[/pdf]` (or async `POST /api/v1/reports/jobs`) merges `StudyContext` into `build_market_study_dossier()`, runs `ReportOrchestrator`, executes `validate_market_study_report()`, blocks delivery (`422`) on critical QA failures, and renders institutional PDFs via `PDFRenderer`.
3. **Project & Version Management**: `ProjectStore` persists projects, `StudyContext`, conversations, messages, versioned studies (`v1`, `v2`, ...), QA results, and local PDF artifacts scoped by `owner_id`.

