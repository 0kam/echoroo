# Echoroo v2 Architecture

## Overview

Echoroo is a web-based bioacoustic analysis platform for audio annotation, species detection, and machine learning model development. This document outlines the architecture for the complete rebuild using modern, stable technologies.

## Technology Stack

### Frontend
| Technology | Purpose | Reason |
|------------|---------|--------|
| **SvelteKit** | Full-stack framework | Stable, fast, minimal boilerplate, compiler-based optimization |
| **Svelte 5** | UI framework | Runes for intuitive state management, no virtual DOM |
| **TanStack Query (Svelte)** | Server state | Caching, background updates, optimistic updates |
| **Tailwind CSS** | Styling | Utility-first, design system consistency |
| **Melt UI** | Accessible components | Headless, accessible primitives for Svelte |
| **wavesurfer.js** | Audio visualization | Spectrogram rendering, waveforms, playback |

### Backend
| Technology | Purpose | Reason |
|------------|---------|--------|
| **FastAPI** | API framework | Async, type-safe, OpenAPI generation, Python ML ecosystem |
| **SQLAlchemy 2.0** | ORM | Async support, type hints, mature |
| **PostgreSQL 16+** | Database | Robust, pgvector for embeddings |
| **pgvector** | Vector search | HNSW index, integrated with PostgreSQL |
| **Celery + Redis** | Task queue | Background jobs for heavy ML tasks |
| **Redis** | Cache/Broker | Model caching, task queue broker |

### ML/Audio
| Technology | Purpose |
|------------|---------|
| **PyTorch** | Deep learning framework |
| **TensorFlow** | BirdNET compatibility |
| **BirdNET** | Bird species classification |
| **Perch** | Audio embeddings |
| **TorchAudio** | Audio processing |

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        SvelteKit Frontend                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │ Annotation  │  │  Project    │  │   Search    │  │   Admin     │    │
│  │   Module    │  │  Module     │  │   Module    │  │   Module    │    │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘    │
│         └─────────────────┴─────────────────┴─────────────────┘         │
│                              TanStack Query                              │
│                              Svelte Stores                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ REST API / WebSocket
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         FastAPI Backend                                  │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        API Layer                                  │   │
│  │  /api/v1/recordings  /api/v1/clips  /api/v1/annotations  ...    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      Service Layer                                │   │
│  │  RecordingService  ClipService  AnnotationService  MLService     │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     Repository Layer                              │   │
│  │  RecordingRepo  ClipRepo  AnnotationRepo  EmbeddingRepo          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
         │                              │                        │
         ▼                              ▼                        ▼
┌─────────────────┐          ┌──────────────────┐       ┌───────────────┐
│   PostgreSQL    │          │      Redis       │       │ Celery Worker │
│   + pgvector    │          │  Cache/Broker    │       │   (GPU)       │
└─────────────────┘          └──────────────────┘       └───────────────┘
```

## Directory Structure

```
echoroo/
├── apps/
│   ├── web/                    # SvelteKit frontend
│   │   ├── src/
│   │   │   ├── lib/
│   │   │   │   ├── components/ # Svelte components
│   │   │   │   ├── stores/     # Svelte stores
│   │   │   │   ├── api/        # API client
│   │   │   │   └── utils/      # Utilities
│   │   │   ├── routes/         # SvelteKit routes
│   │   │   └── app.html
│   │   ├── static/
│   │   ├── svelte.config.js
│   │   └── package.json
│   │
│   └── api/                    # FastAPI backend
│       ├── src/echoroo/
│       │   ├── api/            # API endpoints
│       │   │   └── v1/         # Versioned API
│       │   ├── services/       # Business logic
│       │   ├── repositories/   # Data access
│       │   ├── models/         # SQLAlchemy models
│       │   ├── schemas/        # Pydantic schemas
│       │   ├── ml/             # ML inference
│       │   ├── workers/        # Celery tasks
│       │   └── core/           # Config, deps
│       ├── tests/
│       ├── alembic/            # Migrations
│       └── pyproject.toml
│
├── packages/                   # Shared code (if needed)
│   └── types/                  # Shared TypeScript types
│
├── docker/
│   ├── Dockerfile.api
│   ├── Dockerfile.web
│   └── Dockerfile.worker
│
├── scripts/
│   └── docker.sh
│
├── old/                        # Legacy code (reference only)
│
├── compose.dev.yaml
├── compose.prod.yaml
└── README.md
```

## Core Entities (Simplified Schema)

### Primary Entities

```
Recording
├── id: UUID
├── filename: string
├── path: string
├── duration: float
├── sample_rate: int
├── channels: int
├── datetime: timestamp?
├── site_id: UUID?
└── metadata: jsonb

Clip
├── id: UUID
├── recording_id: UUID (FK)
├── start_time: float
├── end_time: float
└── embedding: vector(1024)?

Annotation
├── id: UUID
├── clip_id: UUID (FK)
├── tag_id: UUID (FK)
├── geometry: jsonb           # {type: "BoundingBox", coordinates: [...]}
├── confidence: float?
├── source: enum              # HUMAN, MODEL
├── created_by: UUID (FK)
└── created_at: timestamp

Tag
├── id: UUID
├── name: string
├── category: enum            # SPECIES, SOUND_TYPE, QUALITY
└── parent_id: UUID? (FK)     # Hierarchical tags

Project
├── id: UUID
├── name: string
├── description: text?
└── settings: jsonb

Dataset
├── id: UUID
├── name: string
├── project_id: UUID (FK)
└── recordings: Recording[] (M2M)
```

### ML Entities

```
FoundationModel
├── id: UUID
├── name: string              # "birdnet", "perch"
├── version: string
└── config: jsonb

ModelRun
├── id: UUID
├── model_id: UUID (FK)
├── dataset_id: UUID (FK)
├── status: enum              # PENDING, RUNNING, COMPLETED, FAILED
├── started_at: timestamp?
├── completed_at: timestamp?
└── config: jsonb

Prediction
├── id: UUID
├── run_id: UUID (FK)
├── clip_id: UUID (FK)
├── tag_id: UUID (FK)
├── confidence: float
└── embedding: vector(1024)?

SearchSession
├── id: UUID
├── project_id: UUID (FK)
├── target_tags: UUID[] (FK)
├── reference_clips: UUID[] (FK)
├── iteration: int
└── status: enum
```

## Key Design Principles

### 1. Clean Architecture
- **API Layer**: HTTP handling, validation, authentication
- **Service Layer**: Business logic, orchestration
- **Repository Layer**: Data access abstraction
- **Domain Models**: Pure business entities

### 2. Async-First
- All I/O operations are async
- Database queries use async SQLAlchemy
- Background tasks for heavy operations

### 3. Type Safety
- Pydantic for request/response validation
- SQLAlchemy 2.0 type hints
- TypeScript strict mode in frontend

### 4. Task Queue for Heavy Operations
All long-running tasks go through Celery:
- Species detection runs
- Embedding generation
- Model training
- Batch inference
- Export operations

### 5. WebSocket for Progress
Real-time progress updates via WebSocket:
- Task progress notifications
- Annotation sync across users

## API Design

### Versioning
All API endpoints are versioned: `/api/v1/...`

### RESTful Conventions
```
GET    /api/v1/recordings          # List recordings
POST   /api/v1/recordings          # Create recording
GET    /api/v1/recordings/{id}     # Get recording
PATCH  /api/v1/recordings/{id}     # Update recording
DELETE /api/v1/recordings/{id}     # Delete recording

GET    /api/v1/recordings/{id}/clips       # List clips for recording
POST   /api/v1/recordings/{id}/clips       # Create clip
```

### Pagination
```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "pages": 5
}
```

### Error Responses
```json
{
  "detail": "Recording not found",
  "code": "RECORDING_NOT_FOUND",
  "status": 404
}
```

## Frontend Modules

### 1. Annotation Module
Core annotation functionality:
- Spectrogram visualization (wavesurfer.js)
- Geometry drawing (BoundingBox, TimeInterval, etc.)
- Tag management
- Keyboard shortcuts
- Multi-user sync

### 2. Project Module
Project and dataset management:
- Create/manage projects
- Upload recordings
- Dataset organization

### 3. Search Module
ML-powered search:
- Reference sound selection
- Active learning workflow
- Similar sound search

### 4. Admin Module
System administration:
- User management
- Model configuration
- System settings

## Migration Strategy

### Phase 1: Foundation
1. Set up monorepo structure
2. Initialize SvelteKit project
3. Initialize FastAPI project with clean architecture
4. Design and implement new database schema
5. Set up Docker development environment

### Phase 2: Core Features
1. Recording/Clip management
2. Basic annotation interface
3. Authentication system
4. File upload/storage

### Phase 3: ML Integration
1. Celery task queue setup
2. Species detection pipeline
3. Embedding generation
4. Vector search

### Phase 4: Advanced Features
1. Active learning workflow
2. Custom model training
3. Evaluation framework
4. Export functionality

### Phase 5: Polish
1. Performance optimization
2. Error handling improvements
3. Documentation
4. Testing

## Development Guidelines

### Code Style
- **Python**: Black, isort, ruff
- **TypeScript/Svelte**: Prettier, ESLint
- **Commits**: Conventional commits

### Testing
- Unit tests for services and utilities
- Integration tests for API endpoints
- E2E tests for critical workflows

### Documentation
- OpenAPI spec auto-generated
- Component documentation in Storybook
- Architecture decisions in ADRs
