# Quickstart: Annotation Feature

**Branch**: `003-annotation`
**Date**: 2026-02-19

## Prerequisites

1. Development environment running (`./scripts/docker.sh dev`)
2. 001-administration feature implemented (Users, Projects, Roles)
3. 002-data-management feature implemented (Sites, Datasets, Recordings, Clips)

## Setup Steps

### 1. Install New Dependencies

No new backend or frontend dependencies required. All needed libraries are already installed from previous features.

### 2. Run Database Migrations

```bash
cd apps/api
uv run alembic upgrade head
```

### 3. Verify API Endpoints

After implementation, verify the following endpoints work:

**Tags:**
- `GET /api/v1/projects/{id}/tags` - List tags
- `POST /api/v1/projects/{id}/tags` - Create tag
- `GET /api/v1/projects/{id}/tags/{id}` - Get tag details
- `PATCH /api/v1/projects/{id}/tags/{id}` - Update tag
- `DELETE /api/v1/projects/{id}/tags/{id}` - Delete tag
- `GET /api/v1/projects/{id}/tags/gbif-suggest?q=...` - GBIF species search
- `GET /api/v1/projects/{id}/tags/statistics` - Tag usage stats

**Annotation Projects:**
- `GET /api/v1/projects/{id}/annotation-projects` - List
- `POST /api/v1/projects/{id}/annotation-projects` - Create
- `GET /api/v1/projects/{id}/annotation-projects/{id}` - Get with progress
- `PATCH /api/v1/projects/{id}/annotation-projects/{id}` - Update
- `DELETE /api/v1/projects/{id}/annotation-projects/{id}` - Delete
- `POST /api/v1/projects/{id}/annotation-projects/{id}/generate-tasks` - Generate tasks
- `GET /api/v1/projects/{id}/annotation-projects/{id}/export?format=json` - Export

**Annotation Tasks:**
- `GET /api/v1/projects/{id}/annotation-projects/{id}/tasks` - List tasks
- `GET /api/v1/projects/{id}/annotation-projects/{id}/tasks/{id}` - Get task
- `PATCH /api/v1/projects/{id}/annotation-projects/{id}/tasks/{id}` - Update task
- `POST /api/v1/projects/{id}/annotation-projects/{id}/tasks/{id}/complete` - Complete
- `GET /api/v1/projects/{id}/annotation-projects/{id}/tasks/next` - Next task

**Annotations:**
- `GET /api/v1/projects/{id}/annotation-tasks/{id}/clip-annotation` - Get/create clip annotation
- `POST /api/v1/projects/{id}/clip-annotations/{id}/tags` - Add clip tag
- `POST /api/v1/projects/{id}/clip-annotations/{id}/sound-events` - Create sound event
- `PATCH /api/v1/projects/{id}/sound-events/{id}` - Update sound event
- `DELETE /api/v1/projects/{id}/sound-events/{id}` - Delete sound event
- `POST /api/v1/projects/{id}/clip-annotations/{id}/review` - Review annotation

## Quick Test Workflow

### 1. Create Tags

```bash
# Create a species tag
curl -X POST http://localhost:8000/api/v1/projects/{project_id}/tags \
  -H "Content-Type: application/json" \
  -b "session=..." \
  -d '{
    "name": "Parus major",
    "category": "species",
    "scientific_name": "Parus major",
    "common_name": "Great Tit",
    "gbif_taxon_key": 9806309
  }'
```

### 2. Create an Annotation Project

```bash
curl -X POST http://localhost:8000/api/v1/projects/{project_id}/annotation-projects \
  -H "Content-Type: application/json" \
  -b "session=..." \
  -d '{
    "name": "Bird Detection 2026",
    "description": "Annotate bird calls in spring recordings",
    "instructions": "Mark all bird vocalizations with bounding boxes. Tag each with species if identifiable.",
    "dataset_ids": ["{dataset_id}"],
    "tag_ids": ["{tag_id}"]
  }'
```

### 3. Generate Tasks

```bash
curl -X POST http://localhost:8000/api/v1/projects/{project_id}/annotation-projects/{ap_id}/generate-tasks \
  -b "session=..."
```

### 4. Start Annotating

```bash
# Get next task
curl http://localhost:8000/api/v1/projects/{project_id}/annotation-projects/{ap_id}/tasks/next \
  -b "session=..."

# Create sound event on the clip
curl -X POST http://localhost:8000/api/v1/projects/{project_id}/clip-annotations/{ca_id}/sound-events \
  -H "Content-Type: application/json" \
  -b "session=..." \
  -d '{
    "geometry": {
      "type": "BoundingBox",
      "coordinates": [1.5, 2000, 3.0, 8000]
    },
    "tag_ids": ["{tag_id}"],
    "source": "human"
  }'

# Complete task
curl -X POST http://localhost:8000/api/v1/projects/{project_id}/annotation-projects/{ap_id}/tasks/{task_id}/complete \
  -b "session=..."
```

### 5. Export Annotations

```bash
curl "http://localhost:8000/api/v1/projects/{project_id}/annotation-projects/{ap_id}/export?format=csv" \
  -b "session=..." \
  --output annotations.csv
```

## Key Files to Implement

### Backend (Priority Order)

1. **Models** (apps/api/echoroo/models/)
   - `tag.py` - Tag model with GBIF fields
   - `annotation_project.py` - AnnotationProject + association tables
   - `annotation_task.py` - AnnotationTask model
   - `clip_annotation.py` - ClipAnnotation model
   - `sound_event_annotation.py` - SoundEventAnnotation model
   - `note.py` - Note model

2. **Schemas** (apps/api/echoroo/schemas/)
   - `tag.py` - Tag Pydantic schemas
   - `annotation_project.py` - AnnotationProject schemas
   - `annotation_task.py` - AnnotationTask schemas
   - `annotation.py` - ClipAnnotation + SoundEventAnnotation schemas
   - `note.py` - Note schemas

3. **Repositories** (apps/api/echoroo/repositories/)
   - `tag.py` - Tag data access
   - `annotation_project.py` - AnnotationProject data access
   - `annotation_task.py` - AnnotationTask data access
   - `clip_annotation.py` - ClipAnnotation data access
   - `sound_event_annotation.py` - SoundEventAnnotation data access
   - `note.py` - Note data access

4. **Services** (apps/api/echoroo/services/)
   - `tag.py` - Tag business logic + GBIF integration
   - `annotation_project.py` - AnnotationProject logic
   - `annotation_task.py` - Task management + assignment
   - `annotation.py` - Annotation CRUD + review workflow
   - `export.py` - Update with annotation export (JSON/CSV/AOEF)

5. **API Endpoints** (apps/api/echoroo/api/v1/)
   - `tags.py` - Tag CRUD + GBIF suggest
   - `annotation_projects.py` - Project CRUD + task generation + export
   - `annotation_tasks.py` - Task management
   - `annotations.py` - Annotation CRUD + review

6. **Workers** (apps/api/echoroo/workers/)
   - `annotation_tasks.py` - Celery task for batch task generation

### Frontend (Priority Order)

1. **API Clients** (apps/web/src/lib/api/)
   - `tags.ts` - Tag API
   - `annotation-projects.ts` - Annotation project API
   - `annotation-tasks.ts` - Task API
   - `annotations.ts` - Annotation API

2. **Components** (apps/web/src/lib/components/)
   - `annotation/AnnotationCanvas.svelte` - Bounding box drawing
   - `annotation/TagSelector.svelte` - Tag selection with GBIF
   - `annotation/TaskNavigator.svelte` - Task navigation
   - `annotation/ReviewPanel.svelte` - Review approve/reject
   - `annotation/AnnotationList.svelte` - Annotations sidebar
   - `annotation/AnnotationProjectList.svelte` - Project list
   - `annotation/AnnotationProjectForm.svelte` - Create/edit project

3. **Pages** (apps/web/src/routes/(app)/projects/[id]/)
   - `annotations/+page.svelte` - Annotation projects list
   - `annotations/[annotationProjectId]/+page.svelte` - Task list
   - `annotations/[annotationProjectId]/tasks/[taskId]/+page.svelte` - Annotation workspace
   - `annotations/[annotationProjectId]/review/+page.svelte` - Review interface

## Type Checking

After implementation, run type checks:

```bash
# Backend
cd apps/api
uv run mypy .

# Frontend
cd apps/web
npm run check
```

## Testing

Run tests after implementation:

```bash
# Backend
cd apps/api
uv run pytest tests/contract/test_tags.py -v
uv run pytest tests/contract/test_annotation_projects.py -v
uv run pytest tests/contract/test_annotation_tasks.py -v
uv run pytest tests/contract/test_annotations.py -v

# Frontend
cd apps/web
npm run test
```

## Environment Variables

No new environment variables required for this feature.
