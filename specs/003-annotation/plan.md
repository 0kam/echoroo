# Implementation Plan: Audio Event Annotation

**Branch**: `003-annotation` | **Date**: 2026-02-19 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-annotation/spec.md`

## Summary

This feature implements the annotation workflow for Echoroo v2, including annotation projects, task management, bounding box and clip-level annotations, hierarchical tags with GBIF species integration, review workflow, and multi-format export (JSON/CSV/AOEF). The implementation follows existing Clean Architecture patterns with FastAPI backend and SvelteKit frontend.

## Technical Context

**Language/Version**: Python 3.11 (Backend), TypeScript 5.x (Frontend)
**Primary Dependencies**: FastAPI, SQLAlchemy 2.0, Pydantic, SvelteKit, Svelte 5, TanStack Query, Tailwind CSS, wavesurfer.js
**Storage**: PostgreSQL 16+ with pgvector extension
**Testing**: pytest (contract/integration/unit), vitest (frontend)
**Target Platform**: Linux server (Docker), modern web browsers
**Project Type**: Web application (frontend + backend)
**Performance Goals**:
- 100 clips/hour annotation speed (SC-001)
- Bounding box drawing response < 500ms (SC-002)
- Task list load < 2s for 1000 tasks (SC-003)
- Export < 1 minute for 10,000 annotations (SC-005)

**Constraints**:
- Annotations must support both human and model sources
- GBIF integration for species tag autocomplete
- Batch task generation via Celery for large datasets
- Auto-save with debounced 500ms interval

**Scale/Scope**:
- Thousands of tasks per annotation project
- Hundreds of sound events per clip
- Dozens of tags per project

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Clean Architecture ✅ PASS
- **API Layer**: FastAPI routers in `apps/api/echoroo/api/v1/` for tags, annotation-projects, annotation-tasks, annotations
- **Service Layer**: Business logic in `apps/api/echoroo/services/` (TagService, AnnotationProjectService, AnnotationTaskService, AnnotationService)
- **Repository Layer**: Data access in `apps/api/echoroo/repositories/` (TagRepository, AnnotationProjectRepository, etc.)
- **Domain Models**: SQLAlchemy models in `apps/api/echoroo/models/`
- Dependencies injected via FastAPI's `Depends()`

### II. Test-Driven Development ✅ WILL COMPLY
- Contract tests for all API endpoints (test_tags.py, test_annotation_projects.py, test_annotation_tasks.py, test_annotations.py)
- Integration tests for annotation workflow and review workflow
- Unit tests for geometry validation, GBIF integration, export formatting

### III. Type Safety ✅ WILL COMPLY
- Pydantic schemas for all request/response validation
- SQLAlchemy 2.0 type hints for all models
- mypy strict mode validation
- TypeScript strict mode in frontend
- Geometry types validated via Pydantic model validators

### IV. ML Pipeline Architecture ✅ WILL COMPLY
- Batch task generation via Celery task
- Large exports (>1000 annotations) via Celery task
- Progress updates for long-running operations

### V. API Versioning ✅ WILL COMPLY
- All endpoints under `/api/v1/`
- Breaking changes will increment version
- Backward compatible within v1

### Security Requirements ✅ WILL COMPLY
- JWT token validation for all endpoints
- Role-based access: project Admin/Member can annotate, Admin can review
- Pydantic validation for all inputs including geometry JSON

## Project Structure

### Documentation (this feature)

```text
specs/003-annotation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── tags.yaml
│   ├── annotation-projects.yaml
│   ├── annotation-tasks.yaml
│   └── annotations.yaml
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
apps/api/
├── echoroo/
│   ├── api/v1/
│   │   ├── tags.py                    # Tag CRUD + GBIF suggest
│   │   ├── annotation_projects.py     # Project CRUD + task generation + export
│   │   ├── annotation_tasks.py        # Task management + navigation
│   │   └── annotations.py            # ClipAnnotation + SoundEvent CRUD + review
│   ├── models/
│   │   ├── tag.py                     # Tag model
│   │   ├── annotation_project.py      # AnnotationProject + association tables
│   │   ├── annotation_task.py         # AnnotationTask model
│   │   ├── clip_annotation.py         # ClipAnnotation model
│   │   ├── sound_event_annotation.py  # SoundEventAnnotation model
│   │   └── note.py                    # Note model
│   ├── schemas/
│   │   ├── tag.py                     # Tag Pydantic schemas
│   │   ├── annotation_project.py      # AnnotationProject schemas
│   │   ├── annotation_task.py         # AnnotationTask schemas
│   │   ├── annotation.py             # ClipAnnotation + SoundEvent schemas
│   │   └── note.py                    # Note schemas
│   ├── services/
│   │   ├── tag.py                     # Tag logic + GBIF
│   │   ├── annotation_project.py      # Project logic
│   │   ├── annotation_task.py         # Task management
│   │   └── annotation.py             # Annotation CRUD + review
│   ├── repositories/
│   │   ├── tag.py                     # Tag data access
│   │   ├── annotation_project.py      # Project data access
│   │   ├── annotation_task.py         # Task data access
│   │   ├── clip_annotation.py         # ClipAnnotation data access
│   │   ├── sound_event_annotation.py  # SoundEvent data access
│   │   └── note.py                    # Note data access
│   └── workers/
│       └── annotation_tasks.py        # Celery: batch task generation
├── alembic/
│   └── versions/                      # New migrations
└── tests/
    ├── contract/
    │   ├── test_tags.py
    │   ├── test_annotation_projects.py
    │   ├── test_annotation_tasks.py
    │   └── test_annotations.py
    └── integration/
        ├── test_annotation_workflow.py
        └── test_review_workflow.py

apps/web/
├── src/
│   ├── lib/
│   │   ├── api/
│   │   │   ├── tags.ts                # Tag API client
│   │   │   ├── annotation-projects.ts # Annotation project API
│   │   │   ├── annotation-tasks.ts    # Task API
│   │   │   └── annotations.ts         # Annotation API
│   │   ├── components/
│   │   │   └── annotation/
│   │   │       ├── AnnotationCanvas.svelte      # Bounding box drawing
│   │   │       ├── TagSelector.svelte           # Tag autocomplete + GBIF
│   │   │       ├── TaskNavigator.svelte         # Previous/Next task nav
│   │   │       ├── ReviewPanel.svelte           # Approve/reject UI
│   │   │       ├── AnnotationList.svelte        # Sidebar annotations list
│   │   │       ├── AnnotationProjectList.svelte # Project list view
│   │   │       └── AnnotationProjectForm.svelte # Create/edit project form
│   │   └── types/
│   │       └── annotation.ts          # TypeScript types
│   └── routes/
│       └── (app)/
│           └── projects/
│               └── [id]/
│                   └── annotations/
│                       ├── +page.svelte                           # Project list
│                       ├── [annotationProjectId]/
│                       │   ├── +page.svelte                       # Task list
│                       │   ├── tasks/
│                       │   │   └── [taskId]/
│                       │   │       └── +page.svelte               # Annotation workspace
│                       │   └── review/
│                       │       └── +page.svelte                   # Review interface
│                       └── tags/
│                           └── +page.svelte                       # Tag management
└── tests/
    └── *.test.ts
```

**Structure Decision**: Web application structure following existing patterns from 001-administration and 002-data-management. Backend follows Clean Architecture with API/Service/Repository layers. Frontend uses SvelteKit route groups with shared annotation components.

## Complexity Tracking

> No constitution violations requiring justification.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | N/A | N/A |
