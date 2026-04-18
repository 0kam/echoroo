# Quickstart: Annotation Feature (Revised)

**Branch**: `003-annotation`
**Date**: 2026-04-17 (revised from 2026-02-19)

## Prerequisites

1. Dev environment running (`./scripts/docker.sh dev`).
2. 001-administration feature implemented (Users, Projects, Roles).
3. 002-data-management feature implemented (Sites, Datasets, Recordings).
4. Detection-review models already exist at `apps/api/echoroo/models/annotation.py` — **must remain untouched**.

## Setup

### 1. Migrations

```bash
cd apps/api
uv run alembic upgrade head
```

This applies the new tables: `annotation_sets`, `annotation_set_species`, `annotation_segments`, `time_range_annotations`, `annotation_segment_notes`, `time_range_annotation_notes`, `evaluation_runs`, `evaluation_results`, plus the `notes.is_issue` column if absent.

### 2. No new dependencies

Backend: reuses existing Celery, SQLAlchemy, detector inference modules. Frontend: reuses existing waveform/audio components.

## API Endpoints (summary)

See `contracts/*.yaml` for the authoritative OpenAPI definitions.

**AnnotationSet**
- `POST   /api/v1/annotation-sets`
- `GET    /api/v1/annotation-sets` (filters: `project_id`, `dataset_id`, `status`)
- `GET    /api/v1/annotation-sets/{id}`
- `PATCH  /api/v1/annotation-sets/{id}`
- `DELETE /api/v1/annotation-sets/{id}`
- `POST   /api/v1/annotation-sets/{id}/sample` (dispatches Celery sampling job)
- `GET    /api/v1/annotation-sets/{id}/segments` (paginated)
- `POST   /api/v1/annotation-sets/{id}/palette` (body: `species_id`)
- `DELETE /api/v1/annotation-sets/{id}/palette/{species_id}`
- `POST   /api/v1/annotation-sets/{id}/evaluate` (body: `model_ids[]`)

**AnnotationSegment**
- `GET    /api/v1/segments/{id}`
- `PATCH  /api/v1/segments/{id}` (body: `status`, `is_empty`)
- `POST   /api/v1/segments/{id}/annotations` (create TimeRangeAnnotation)
- `POST   /api/v1/segments/{id}/notes`

**TimeRangeAnnotation**
- `PATCH  /api/v1/annotations/{id}`
- `DELETE /api/v1/annotations/{id}`
- `POST   /api/v1/annotations/{id}/notes`

**Evaluation**
- `GET    /api/v1/annotation-sets/{id}/evaluation-runs` (list history)
- `GET    /api/v1/evaluation-runs/{id}` (with per-species `EvaluationResult`s)

## End-to-End Quick Test

### 1. Create a set

```bash
curl -X POST http://localhost:8002/api/v1/annotation-sets \
  -H "Content-Type: application/json" -b "session=..." \
  -d '{
    "project_id": "<uuid>",
    "dataset_id": "<uuid>",
    "name": "Spring 2025 ground truth",
    "filter_date_range": {"start": "2025-04-01", "end": "2025-04-30"},
    "filter_time_of_day_range": {"start": "04:00", "end": "09:00"},
    "segment_length_sec": 30,
    "num_segments": 100
  }'
```

### 2. Trigger sampling

```bash
curl -X POST http://localhost:8002/api/v1/annotation-sets/<id>/sample -b "session=..."
```

Poll `GET /annotation-sets/<id>` until `status = ready`.

### 3. Populate palette

```bash
curl -X POST http://localhost:8002/api/v1/annotation-sets/<id>/palette \
  -H "Content-Type: application/json" -b "session=..." \
  -d '{"species_id": "<species_uuid>"}'
```

### 4. Annotate a segment

```bash
# List segments
curl "http://localhost:8002/api/v1/annotation-sets/<id>/segments?status=unannotated" -b "session=..."

# Create a time-range annotation
curl -X POST http://localhost:8002/api/v1/segments/<segment_id>/annotations \
  -H "Content-Type: application/json" -b "session=..." \
  -d '{
    "start_time_sec": 4.2,
    "end_time_sec": 5.1,
    "species_id": "<species_uuid>",
    "confidence": 0.9
  }'

# Or mark segment as empty
curl -X PATCH http://localhost:8002/api/v1/segments/<segment_id> \
  -H "Content-Type: application/json" -b "session=..." \
  -d '{"status": "annotated", "is_empty": true}'
```

### 5. Run cross-model evaluation

```bash
curl -X POST http://localhost:8002/api/v1/annotation-sets/<id>/evaluate \
  -H "Content-Type: application/json" -b "session=..." \
  -d '{"model_ids": ["birdnet", "perch", "<custom_model_uuid>"]}'
```

Poll `GET /evaluation-runs/<run_id>` until `status = completed`, then read `results[]` for per-model and per-species P/R/F1.

## Key Files to Implement (priority order)

### Backend
1. Models: `annotation_set.py`, `annotation_segment.py`, `time_range_annotation.py`, association tables, `evaluation_run.py`, `evaluation_result.py`.
2. Alembic migration.
3. Schemas (Pydantic).
4. Repositories.
5. Services: `annotation_sampling.py`, `annotation_set.py`, `annotation_segment.py`, `time_range_annotation.py`, `evaluation.py`.
6. Celery tasks: `annotation_sampling_tasks.py`, `evaluation_tasks.py` (on `worker-cpu` queue).
7. API routers.

### Frontend
1. API clients + TanStack Query hooks.
2. Routes under `(app)/projects/[id]/annotation-sets/`.
3. Components: `AnnotationSetForm`, `SegmentList`, `SegmentEditor` (waveform + drag), `SpeciesPalette`, `EvaluationDashboard`.

## Type Check / Tests

```bash
# Backend
cd apps/api
uv run ruff check .
uv run mypy .
uv run pytest tests/unit/test_overlap_metric.py -v
uv run pytest tests/contract -v
uv run pytest tests/integration -v

# Frontend
cd apps/web
npm run check
npm run test
```

## Environment Variables

None added.
