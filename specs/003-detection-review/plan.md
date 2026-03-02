# Implementation Plan: Detection Review

**Branch**: `003-detection-review` | **Date**: 2026-03-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-detection-review/spec.md`
**Replaces**: Old `003-annotation` (AnnotationProject, AnnotationTask, ClipAnnotation, SoundEventAnnotation)

## Summary

This feature implements the core detection review workflow for Echoroo v2, replacing the old Whombat-derived annotation system. The new architecture centers around recording-level time-segment Annotations (not clip-based), ConfirmedRegions for tracking reviewed time spans (enabling negative data), and DetectionRuns for ML traceability. The frontend delivers a Species List View as the primary entry point and a card-based Detection Review UI with mini spectrograms, playback, and drag-to-select time range confirmation. The feature also includes detection export (CSV + ML training dataset) and navigation restructuring.

## Technical Context

**Language/Version**: Python 3.11 (Backend), TypeScript 5.x (Frontend)
**Primary Dependencies**: FastAPI, SQLAlchemy 2.0, Pydantic, SvelteKit, Svelte 5, TanStack Query, Tailwind CSS, wavesurfer.js
**Storage**: PostgreSQL 16+ with pgvector extension
**Testing**: pytest (contract/integration), vitest (frontend)
**Target Platform**: Linux server (Docker), modern web browsers
**Project Type**: Web application (frontend + backend)
**Performance Goals**:
- Species List View load < 1 second (10,000 annotations)
- Detection Review card grid load < 2 seconds (100 cards)
- Confirm/Reject operation < 500ms
- Mini spectrogram render < 1 second
- Audio playback start < 500ms
- CSV export < 5 seconds for 10,000 annotations

**Constraints**:
- Must coexist with old annotation tables (gradual deprecation)
- ML pipeline integration is out of scope (data model and API only)
- Audio files are on server filesystem (not uploaded through browser)

**Scale/Scope**:
- Tens of thousands of annotations per project
- Hundreds of species per project
- Dozens of datasets per project

## Constitution Check

### I. Clean Architecture PASS
- **API Layer**: FastAPI endpoints in `apps/api/echoroo/api/v1/` for detections, confirmed_regions, detection_runs
- **Service Layer**: Business logic in `apps/api/echoroo/services/` (DetectionService, ConfirmedRegionService, DetectionRunService, DetectionExportService)
- **Repository Layer**: Data access in `apps/api/echoroo/repositories/` (AnnotationRepository, ConfirmedRegionRepository, DetectionRunRepository)
- **Domain Models**: SQLAlchemy models in `apps/api/echoroo/models/`
- Dependencies injected via FastAPI `Depends()`

### II. Test-Driven Development WILL COMPLY
- Contract tests for all new API endpoints
- Integration tests for review workflow
- Unit tests for aggregation queries and export logic

### III. Type Safety WILL COMPLY
- Pydantic schemas for all request/response validation
- SQLAlchemy 2.0 type hints
- TypeScript strict mode in frontend

### IV. ML Pipeline Architecture WILL COMPLY
- DetectionRun model provides ML traceability
- Annotation model supports multiple sources (birdnet, perch_search, human)
- Export service generates ML-ready training datasets

### V. API Versioning WILL COMPLY
- All new endpoints under `/api/v1/`
- Backward compatible (old annotation endpoints remain functional)

## Project Structure

### Documentation (this feature)

```text
specs/003-detection-review/
├── spec.md              # Feature specification
├── plan.md              # This file
└── tasks.md             # Implementation tasks
```

### Source Code (new and modified files)

```text
apps/api/
├── echoroo/
│   ├── api/v1/
│   │   ├── detections.py          # Detection (Annotation) API endpoints (NEW)
│   │   ├── confirmed_regions.py   # ConfirmedRegion API endpoints (NEW)
│   │   └── detection_runs.py      # DetectionRun API endpoints (NEW)
│   ├── models/
│   │   ├── annotation.py          # Annotation model (NEW - replaces old annotation models)
│   │   ├── confirmed_region.py    # ConfirmedRegion model (NEW)
│   │   ├── detection_run.py       # DetectionRun model (NEW)
│   │   ├── enums.py               # New enums (DetectionSource, DetectionStatus, DetectionRunStatus)
│   │   └── __init__.py            # Register new models
│   ├── schemas/
│   │   ├── detection.py           # Annotation/Detection Pydantic schemas (NEW)
│   │   ├── confirmed_region.py    # ConfirmedRegion schemas (NEW)
│   │   └── detection_run.py       # DetectionRun schemas (NEW)
│   ├── services/
│   │   ├── detection.py           # Detection business logic (NEW)
│   │   ├── confirmed_region.py    # ConfirmedRegion business logic (NEW)
│   │   ├── detection_run.py       # DetectionRun business logic (NEW)
│   │   └── detection_export.py    # Detection + ML export services (NEW)
│   └── repositories/
│       ├── annotation.py          # Annotation data access (NEW)
│       ├── confirmed_region.py    # ConfirmedRegion data access (NEW)
│       └── detection_run.py       # DetectionRun data access (NEW)
├── alembic/
│   └── versions/                  # New migrations for annotation, confirmed_region, detection_run tables
└── tests/
    ├── contract/
    │   ├── test_detections.py     # Detection API tests (NEW)
    │   ├── test_confirmed_regions.py  # ConfirmedRegion API tests (NEW)
    │   └── test_detection_runs.py # DetectionRun API tests (NEW)
    └── integration/
        ├── test_review_workflow.py # End-to-end review flow (NEW)
        └── test_detection_export.py # Export tests (NEW)

apps/web/
├── src/
│   ├── lib/
│   │   ├── api/
│   │   │   ├── detections.ts      # Detection API client (NEW)
│   │   │   └── detection-export.ts # Export API client (NEW)
│   │   ├── components/
│   │   │   └── detection/         # Detection review components (NEW directory)
│   │   │       ├── SpeciesListView.svelte       # Species summary list
│   │   │       ├── SpeciesListItem.svelte       # Single species row
│   │   │       ├── DetectionReviewGrid.svelte   # Card grid for review
│   │   │       ├── DetectionCard.svelte         # Single detection card
│   │   │       ├── MiniSpectrogram.svelte       # Compact spectrogram with highlight
│   │   │       ├── TimeRangeSelector.svelte     # Drag-to-select time range
│   │   │       ├── ReviewActions.svelte         # Confirm/Reject buttons
│   │   │       ├── SpeciesCorrector.svelte      # Change species (misidentification fix)
│   │   │       ├── DetectionFilters.svelte      # Status/confidence/dataset filters
│   │   │       └── DetectionExportDialog.svelte # Export dialog
│   │   └── types/
│   │       └── detection.ts       # Detection TypeScript types (NEW)
│   └── routes/
│       └── (app)/
│           └── projects/
│               └── [id]/
│                   ├── +layout.svelte             # MODIFY: Update navigation to 5 items
│                   ├── detections/                 # NEW route group
│                   │   ├── +page.svelte            # Species List View
│                   │   └── [tagId]/
│                   │       └── +page.svelte        # Detection Review for species
│                   ├── data/                       # NEW: Unified Sites & Data view
│                   │   └── +page.svelte            # Sites & Data combined view
│                   └── reports/                    # NEW route group
│                       └── +page.svelte            # Export options page
```

## Data Model Design

### New Tables

#### annotations (replaces old annotation hierarchy)

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | UUID | NOT NULL | Primary key |
| recording_id | UUID FK | NOT NULL | Parent recording |
| tag_id | UUID FK | NULL | Species tag (nullable for untagged detections) |
| detection_run_id | UUID FK | NULL | Source ML run (NULL for human annotations) |
| source | DetectionSource | NOT NULL | birdnet / perch_search / human |
| status | DetectionStatus | NOT NULL | unreviewed / confirmed / rejected |
| confidence | Float | NULL | ML confidence 0.0-1.0 |
| start_time | Float | NOT NULL | Start offset in seconds within recording |
| end_time | Float | NOT NULL | End offset in seconds within recording |
| freq_low | Float | NULL | Low frequency bound (Hz), optional |
| freq_high | Float | NULL | High frequency bound (Hz), optional |
| reviewed_by_id | UUID FK | NULL | User who reviewed |
| reviewed_at | DateTime | NULL | Review timestamp |
| created_at | DateTime | NOT NULL | Created timestamp |
| updated_at | DateTime | NOT NULL | Updated timestamp |

**Note**: Table name is `annotations` (new). Old tables (`clip_annotations`, `sound_event_annotations`, `annotation_projects`, `annotation_tasks`) remain for backward compatibility but are not used by this feature.

#### confirmed_regions

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | UUID | NOT NULL | Primary key |
| recording_id | UUID FK | NOT NULL | Parent recording |
| start_time | Float | NOT NULL | Start offset in seconds |
| end_time | Float | NOT NULL | End offset in seconds |
| reviewed_by_id | UUID FK | NOT NULL | User who reviewed this region |
| created_at | DateTime | NOT NULL | Created timestamp |
| updated_at | DateTime | NOT NULL | Updated timestamp |

#### detection_runs

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | UUID | NOT NULL | Primary key |
| project_id | UUID FK | NOT NULL | Parent project |
| dataset_id | UUID FK | NULL | Dataset processed (NULL for project-wide) |
| model_name | String(100) | NOT NULL | ML model name (e.g., "birdnet") |
| model_version | String(50) | NOT NULL | Model version |
| parameters | JSONB | NULL | Run parameters |
| status | DetectionRunStatus | NOT NULL | pending / running / completed / failed |
| annotation_count | Integer | NOT NULL | Number of annotations generated |
| started_at | DateTime | NULL | Run start time |
| completed_at | DateTime | NULL | Run completion time |
| error_message | Text | NULL | Error details on failure |
| created_at | DateTime | NOT NULL | Created timestamp |
| updated_at | DateTime | NOT NULL | Updated timestamp |

### New Enums

```python
class DetectionSource(str, Enum):
    BIRDNET = "birdnet"
    PERCH_SEARCH = "perch_search"
    HUMAN = "human"

class DetectionStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"

class DetectionRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
```

### Key API Endpoints

#### Detection (Annotation) API — `/api/v1/projects/{project_id}/detections`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List detections with filters (tag_id, status, confidence range, dataset_id, recording_id) |
| GET | `/species-summary` | Species-level aggregation for Species List View |
| GET | `/{id}` | Get single detection |
| POST | `/` | Create detection (for human annotations) |
| PATCH | `/{id}` | Update detection (status, tag_id) |
| POST | `/{id}/confirm` | Confirm detection with time range (creates ConfirmedRegion) |
| POST | `/{id}/reject` | Reject detection |
| POST | `/{id}/change-species` | Change species tag and optionally confirm |
| DELETE | `/{id}` | Delete detection |

#### ConfirmedRegion API — `/api/v1/projects/{project_id}/confirmed-regions`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List confirmed regions (by recording_id) |
| POST | `/` | Create confirmed region |
| DELETE | `/{id}` | Delete confirmed region |

#### DetectionRun API — `/api/v1/projects/{project_id}/detection-runs`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List detection runs |
| GET | `/{id}` | Get detection run details |
| POST | `/` | Create detection run (internal, for ML pipeline) |
| PATCH | `/{id}` | Update detection run status |

#### Export API — `/api/v1/projects/{project_id}/detections/export`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/csv` | Export detections as CSV |
| GET | `/ml-dataset` | Export ML training dataset (ZIP) |

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | N/A | N/A |