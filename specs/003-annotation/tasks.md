# Tasks: Audio Event Annotation

> **STALE — DO NOT IMPLEMENT FROM THIS FILE.**
> This task list was generated from the previous Whombat-derived design. The spec
> was revised on 2026-04-17 (see `spec.md`, `plan.md`, `data-model.md`,
> `research.md`, `contracts/`). Regenerate this file with `/speckit.tasks`
> before using.

**Input**: Design documents from `/specs/003-annotation/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Included per constitution requirement (TDD is NON-NEGOTIABLE).

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Backend**: `apps/api/echoroo/` (FastAPI)
- **Frontend**: `apps/web/src/` (SvelteKit)
- **Tests**: `apps/api/tests/` (pytest), `apps/web/tests/` (vitest)

---

## Phase 1: Setup

**Purpose**: Enum definitions, database models, schemas, and migrations for all annotation entities

- [x] T001 [P] Add annotation enums (TagCategory, AnnotationProjectVisibility, AnnotationTaskStatus, ReviewStatus, AnnotationSource, GeometryType) to `apps/api/echoroo/models/enums.py`
- [x] T002 [P] Create Tag model with hierarchical structure and GBIF fields in `apps/api/echoroo/models/tag.py`
- [x] T003 [P] Create AnnotationProject model with association tables (annotation_project_datasets, annotation_project_tags) in `apps/api/echoroo/models/annotation_project.py`
- [x] T004 [P] Create AnnotationTask model with status tracking and priority in `apps/api/echoroo/models/annotation_task.py`
- [x] T005 [P] Create ClipAnnotation model with review fields and tag association table (clip_annotation_tags) in `apps/api/echoroo/models/clip_annotation.py`
- [x] T006 [P] Create SoundEventAnnotation model with JSONB geometry and tag association table (sound_event_annotation_tags) in `apps/api/echoroo/models/sound_event_annotation.py`
- [x] T007 [P] Create Note model with polymorphic FK (clip_annotation_id OR sound_event_annotation_id) in `apps/api/echoroo/models/note.py`
- [x] T008 Register all new models in `apps/api/echoroo/models/__init__.py`
- [ ] T009 Generate Alembic migration for all annotation tables in `apps/api/alembic/versions/`
- [x] T010 [P] Create Tag Pydantic schemas (TagCreate, TagUpdate, TagResponse, TagDetailResponse, TagListResponse, GBIFSuggestion, TagStatistic) in `apps/api/echoroo/schemas/tag.py`
- [x] T011 [P] Create AnnotationProject Pydantic schemas (AnnotationProjectCreate, AnnotationProjectUpdate, AnnotationProjectResponse, AnnotationProjectDetailResponse, AnnotationProjectListResponse, AnnotationProgress, TaskGenerationResponse) in `apps/api/echoroo/schemas/annotation_project.py`
- [x] T012 [P] Create AnnotationTask Pydantic schemas (AnnotationTaskUpdate, AnnotationTaskResponse, AnnotationTaskDetailResponse, AnnotationTaskListResponse, TaskCompletionResponse) in `apps/api/echoroo/schemas/annotation_task.py`
- [x] T013 [P] Create Annotation Pydantic schemas (SoundEventAnnotationCreate, SoundEventAnnotationUpdate, SoundEventAnnotationResponse, ClipAnnotationDetailResponse, ReviewRequest) in `apps/api/echoroo/schemas/annotation.py`
- [x] T014 [P] Create Note Pydantic schemas (NoteCreate, NoteResponse) in `apps/api/echoroo/schemas/note.py`
- [x] T015 [P] Create TypeScript types for all annotation entities in `apps/web/src/lib/types/annotation.ts`

**Checkpoint**: All models, schemas, migrations, and types are ready. Backend and frontend have shared type definitions.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core repositories used across multiple user stories

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T016 [P] Implement TagRepository (get_by_id, list_by_project, create, update, delete, get_statistics) in `apps/api/echoroo/repositories/tag.py`
- [x] T017 [P] Implement AnnotationProjectRepository (get_by_id, list_by_project, create, update, delete, get_progress) in `apps/api/echoroo/repositories/annotation_project.py`
- [x] T018 [P] Implement AnnotationTaskRepository (get_by_id, list_by_project, get_next, create_batch, update, count_by_status) in `apps/api/echoroo/repositories/annotation_task.py`
- [x] T019 [P] Implement ClipAnnotationRepository (get_by_id, get_by_task_id, create, add_tag, remove_tag, update_review) in `apps/api/echoroo/repositories/clip_annotation.py`
- [x] T020 [P] Implement SoundEventAnnotationRepository (get_by_id, list_by_clip_annotation, create, update, delete, add_tag, remove_tag) in `apps/api/echoroo/repositories/sound_event_annotation.py`
- [x] T021 [P] Implement NoteRepository (create, list_by_clip_annotation, list_by_sound_event) in `apps/api/echoroo/repositories/note.py`

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Annotation Project Creation (Priority: P1) 🎯 MVP

**Goal**: Researchers can create annotation projects with target tags, datasets, and annotation instructions. Progress tracking shows completed/total tasks.

**Independent Test**: Create a project, associate datasets and tags, verify progress shows 0/0 tasks initially.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T022 [P] [US1] Contract tests for annotation project CRUD (list, create, get with progress, update, delete) in `apps/api/tests/contract/test_annotation_projects.py`

### Backend Implementation for User Story 1

- [x] T023 [US1] Implement AnnotationProjectService (create with dataset/tag association, get_with_progress, update, delete, list) in `apps/api/echoroo/services/annotation_project.py`
- [x] T024 [US1] Implement annotation project API endpoints (GET/POST list, GET/PATCH/DELETE detail) in `apps/api/echoroo/api/v1/annotation_projects.py`
- [x] T025 [US1] Register annotation_projects router in `apps/api/echoroo/api/v1/__init__.py`

### Frontend Implementation for User Story 1

- [x] T026 [P] [US1] Create annotation projects API client in `apps/web/src/lib/api/annotation-projects.ts`
- [x] T027 [P] [US1] Create AnnotationProjectForm component (name, description, instructions, dataset picker, tag picker, visibility) in `apps/web/src/lib/components/annotation/AnnotationProjectForm.svelte`
- [x] T028 [P] [US1] Create AnnotationProjectList component (list with progress bars) in `apps/web/src/lib/components/annotation/AnnotationProjectList.svelte`
- [x] T029 [US1] Create annotation projects list page in `apps/web/src/routes/(app)/projects/[id]/annotations/+page.svelte`

**Checkpoint**: User Story 1 is fully functional - annotation projects can be created, managed, and viewed with progress tracking

---

## Phase 4: User Story 2 - Annotation Task Execution (Priority: P1)

**Goal**: Annotators can execute assigned tasks - view spectrogram, draw bounding boxes, tag sound events, complete tasks and move to next.

**Independent Test**: Open a task, draw a bounding box on the spectrogram, tag it with a species, complete the task and verify next task loads.

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T030 [P] [US2] Contract tests for annotation task endpoints (list, get, update, complete, next) in `apps/api/tests/contract/test_annotation_tasks.py`
- [x] T031 [P] [US2] Contract tests for clip annotation and sound event CRUD (get/create clip annotation, create/update/delete sound events, add/remove tags, add notes) in `apps/api/tests/contract/test_annotations.py`

### Backend Implementation for User Story 2

- [x] T032 [US2] Implement AnnotationTaskService (list with filters, get_detail, update status/assignment, complete, get_next) in `apps/api/echoroo/services/annotation_task.py`
- [x] T033 [US2] Implement AnnotationService (get_or_create_clip_annotation, add/remove clip tags, create/update/delete sound events, add/remove sound event tags, add notes) in `apps/api/echoroo/services/annotation.py`
- [x] T034 [US2] Implement NoteService (create note for clip or sound event annotations) in `apps/api/echoroo/services/note.py`
- [x] T035 [US2] Implement annotation task API endpoints (GET list, GET detail, PATCH update, POST complete, GET next) in `apps/api/echoroo/api/v1/annotation_tasks.py`
- [x] T036 [US2] Implement annotation API endpoints (GET clip annotation, POST/DELETE clip tags, GET/POST sound events, PATCH/DELETE sound event, POST/DELETE sound event tags, POST notes) in `apps/api/echoroo/api/v1/annotations.py`
- [x] T037 [US2] Register annotation_tasks and annotations routers in `apps/api/echoroo/api/v1/__init__.py`
- [x] T038 [US2] Implement batch task generation Celery worker (generate tasks from clips in associated datasets) in `apps/api/echoroo/workers/annotation_tasks.py`
- [x] T039 [US2] Add generate-tasks endpoint to annotation projects API in `apps/api/echoroo/api/v1/annotation_projects.py`

### Frontend Implementation for User Story 2

- [x] T040 [P] [US2] Create annotation tasks API client in `apps/web/src/lib/api/annotation-tasks.ts`
- [x] T041 [P] [US2] Create annotations API client (clip annotations, sound events, tags, notes) in `apps/web/src/lib/api/annotations.ts`
- [x] T042 [US2] Create AnnotationCanvas component (bounding box drawing on spectrogram overlay with mouse/touch events) in `apps/web/src/lib/components/annotation/AnnotationCanvas.svelte`
- [x] T043 [US2] Create TagSelector component (dropdown with search, quick-select keyboard shortcuts 1-9) in `apps/web/src/lib/components/annotation/TagSelector.svelte`
- [x] T044 [US2] Create AnnotationList component (sidebar listing current clip's sound events with tags) in `apps/web/src/lib/components/annotation/AnnotationList.svelte`
- [x] T045 [US2] Create TaskNavigator component (previous/next task, progress indicator, complete button) in `apps/web/src/lib/components/annotation/TaskNavigator.svelte`
- [x] T046 [US2] Create task list page (filterable task list with status/assignee) in `apps/web/src/routes/(app)/projects/[id]/annotations/[annotationProjectId]/+page.svelte`
- [x] T047 [US2] Create annotation workspace page (spectrogram + canvas + tag selector + annotation list + task navigator + auto-save) in `apps/web/src/routes/(app)/projects/[id]/annotations/[annotationProjectId]/tasks/[taskId]/+page.svelte`

**Checkpoint**: User Story 2 is fully functional - annotators can execute tasks, draw bounding boxes, tag events, and navigate between tasks

---

## Phase 5: User Story 3 - Tag Management (Priority: P2)

**Goal**: Researchers can create/manage tags with hierarchical structure, GBIF species search, and usage statistics.

**Independent Test**: Create tags in different categories, set up hierarchy (parent/child), search GBIF for a species, verify usage stats show correct counts.

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T048 [P] [US3] Contract tests for tag CRUD, GBIF suggest proxy, and statistics endpoints in `apps/api/tests/contract/test_tags.py`

### Backend Implementation for User Story 3

- [x] T049 [US3] Implement TagService (CRUD, hierarchy management, GBIF proxy via httpx, statistics aggregation) in `apps/api/echoroo/services/tag.py`
- [x] T050 [US3] Implement tag API endpoints (GET/POST list, GET/PATCH/DELETE detail, GET gbif-suggest, GET statistics) in `apps/api/echoroo/api/v1/tags.py`
- [x] T051 [US3] Register tags router in `apps/api/echoroo/api/v1/__init__.py`

### Frontend Implementation for User Story 3

- [x] T052 [P] [US3] Create tags API client (CRUD, GBIF suggest, statistics) in `apps/web/src/lib/api/tags.ts`
- [x] T053 [US3] Enhance TagSelector component with GBIF autocomplete (debounced search, display scientific + common names) in `apps/web/src/lib/components/annotation/TagSelector.svelte`
- [x] T054 [US3] Create tag management page (tag list with hierarchy tree, create/edit dialog, GBIF search, usage stats) in `apps/web/src/routes/(app)/projects/[id]/annotations/tags/+page.svelte`

**Checkpoint**: User Story 3 is fully functional - tags can be managed with hierarchy and GBIF integration

---

## Phase 6: User Story 4 - Clip-Level Annotation (Priority: P2)

**Goal**: Annotators can quickly tag entire clips (presence/absence) without drawing bounding boxes, including batch tagging.

**Independent Test**: Select a clip, add a presence tag, verify clip annotation saved. Select multiple clips, batch-apply a tag, verify all updated.

### Tests for User Story 4

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T055 [P] [US4] Contract tests for clip-level tag add/remove and batch tagging in `apps/api/tests/contract/test_annotations.py` (extend existing)

### Backend Implementation for User Story 4

- [x] T056 [US4] Add batch clip annotation endpoint (POST /api/v1/projects/{id}/clip-annotations/batch-tag) to `apps/api/echoroo/api/v1/annotations.py`
- [x] T057 [US4] Implement batch tag logic in AnnotationService (create clip annotations for multiple tasks, add tags) in `apps/api/echoroo/services/annotation.py`

### Frontend Implementation for User Story 4

- [x] T058 [US4] Create ClipAnnotationPanel component (quick tag toggles, presence/absence buttons, note input) in `apps/web/src/lib/components/annotation/ClipAnnotationPanel.svelte`
- [x] T059 [US4] Add batch tagging mode to task list page (multi-select clips, batch tag dialog) in `apps/web/src/routes/(app)/projects/[id]/annotations/[annotationProjectId]/+page.svelte`

**Checkpoint**: User Story 4 is fully functional - clip-level annotation and batch tagging work independently

---

## Phase 7: User Story 5 - Annotation Review (Priority: P2)

**Goal**: Project admins can review annotations (approve/reject with comments), filter by review status.

**Independent Test**: Open review page, view an annotation, approve it, verify status changes. Reject another with a comment, verify annotator sees feedback.

### Tests for User Story 5

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T060 [P] [US5] Contract tests for review endpoint (approve/reject with comment) and review status filtering in `apps/api/tests/contract/test_annotations.py` (extend existing)
- [x] T061 [P] [US5] Integration test for full review workflow (annotate → submit for review → approve/reject → re-work) in `apps/api/tests/integration/test_review_workflow.py`

### Backend Implementation for User Story 5

- [x] T062 [US5] Implement review logic in AnnotationService (approve/reject with comment, update task status to review_pending/completed) in `apps/api/echoroo/services/annotation.py`
- [x] T063 [US5] Add review endpoint (POST /api/v1/projects/{id}/clip-annotations/{id}/review) to `apps/api/echoroo/api/v1/annotations.py`
- [x] T064 [US5] Add review status filter to annotation task list endpoint in `apps/api/echoroo/api/v1/annotation_tasks.py`

### Frontend Implementation for User Story 5

- [x] T065 [US5] Create ReviewPanel component (approve/reject buttons, comment input, review history) in `apps/web/src/lib/components/annotation/ReviewPanel.svelte`
- [x] T066 [US5] Create review page (list review-pending annotations, spectrogram view, approve/reject workflow) in `apps/web/src/routes/(app)/projects/[id]/annotations/[annotationProjectId]/review/+page.svelte`

**Checkpoint**: User Story 5 is fully functional - review workflow operates independently

---

## Phase 8: User Story 6 - Annotation Export (Priority: P3)

**Goal**: Researchers can export annotations in JSON, CSV (Raven-compatible), and AOEF formats.

**Independent Test**: Export a project as JSON - verify structure. Export as CSV - verify Raven-compatible columns. Export as AOEF - verify soundevent format compliance.

### Tests for User Story 6

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T067 [P] [US6] Contract tests for export endpoint (JSON, CSV, AOEF format responses) in `apps/api/tests/contract/test_annotation_projects.py` (extend existing)

### Backend Implementation for User Story 6

- [x] T068 [US6] Implement annotation export service (JSON formatter with full metadata, CSV Raven-compatible formatter, AOEF soundevent-compatible formatter) in `apps/api/echoroo/services/annotation_export.py`
- [x] T069 [US6] Add export endpoint (GET /api/v1/projects/{id}/annotation-projects/{id}/export?format=json|csv|aoef) to `apps/api/echoroo/api/v1/annotation_projects.py`

### Frontend Implementation for User Story 6

- [x] T070 [US6] Create ExportDialog component (format selector, review status filter, download button) in `apps/web/src/lib/components/annotation/ExportDialog.svelte`
- [x] T071 [US6] Add export button and dialog to annotation project detail page in `apps/web/src/routes/(app)/projects/[id]/annotations/[annotationProjectId]/+page.svelte`

**Checkpoint**: User Story 6 is fully functional - all three export formats work correctly

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Integration testing, type checking, and cleanup

- [ ] T072 [P] Integration test for full annotation workflow (create project → generate tasks → annotate → complete) in `apps/api/tests/integration/test_annotation_workflow.py`
- [ ] T073 [P] Add annotation sidebar link to project navigation layout in `apps/web/src/routes/(app)/projects/[id]/+layout.svelte`
- [ ] T074 Run backend type check: `cd apps/api && uv run mypy .`
- [ ] T075 Run frontend type check: `cd apps/web && npm run check`
- [ ] T076 Run all backend tests: `cd apps/api && uv run pytest tests/contract/ tests/integration/ -v`
- [ ] T077 Run quickstart.md validation workflow

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion - BLOCKS all user stories
- **User Stories (Phase 3-8)**: All depend on Phase 2 completion
  - US1 (Phase 3) and US3 (Phase 5) can run in parallel
  - US2 (Phase 4) depends on US1 (needs annotation project for task context)
  - US4 (Phase 6) depends on US2 (needs ClipAnnotation service)
  - US5 (Phase 7) depends on US2 (needs ClipAnnotation with review fields)
  - US6 (Phase 8) depends on US2 (needs annotation data to export)
- **Polish (Phase 9)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2 - No dependencies on other stories
- **US2 (P1)**: Depends on US1 (annotation tasks belong to annotation projects)
- **US3 (P2)**: Can start after Phase 2 - Independent (basic tag CRUD only)
- **US4 (P2)**: Depends on US2 (uses clip annotation service)
- **US5 (P2)**: Depends on US2 (reviews clip annotations)
- **US6 (P3)**: Depends on US2 (exports annotation data)

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Services before API endpoints
- API endpoints before frontend
- Backend before frontend (API must exist for frontend to call)

### Parallel Opportunities

- Phase 1: All model tasks (T002-T007) can run in parallel; all schema tasks (T010-T015) can run in parallel
- Phase 2: All repository tasks (T016-T021) can run in parallel
- US1 and US3: Can be developed in parallel (different entities)
- Frontend tasks within each story marked [P] can run in parallel
- Backend and frontend teams can split: backend completes US1→US2, frontend follows

---

## Parallel Example: Phase 1 (Setup)

```bash
# Launch all model tasks in parallel:
Task: "Create Tag model in apps/api/echoroo/models/tag.py"
Task: "Create AnnotationProject model in apps/api/echoroo/models/annotation_project.py"
Task: "Create AnnotationTask model in apps/api/echoroo/models/annotation_task.py"
Task: "Create ClipAnnotation model in apps/api/echoroo/models/clip_annotation.py"
Task: "Create SoundEventAnnotation model in apps/api/echoroo/models/sound_event_annotation.py"
Task: "Create Note model in apps/api/echoroo/models/note.py"
```

## Parallel Example: User Story 1 (Frontend)

```bash
# After backend is complete, launch frontend tasks in parallel:
Task: "Create annotation projects API client in apps/web/src/lib/api/annotation-projects.ts"
Task: "Create AnnotationProjectForm component in apps/web/src/lib/components/annotation/AnnotationProjectForm.svelte"
Task: "Create AnnotationProjectList component in apps/web/src/lib/components/annotation/AnnotationProjectList.svelte"
```

---

## Implementation Strategy

### MVP First (User Story 1 + 2)

1. Complete Phase 1: Setup (all models, schemas, migrations)
2. Complete Phase 2: Foundational (all repositories)
3. Complete Phase 3: US1 - Annotation Project Creation
4. Complete Phase 4: US2 - Annotation Task Execution
5. **STOP and VALIDATE**: Test annotation workflow end-to-end
6. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 → Annotation projects manageable → Deploy/Demo (MVP-1)
3. US2 → Full annotation workflow → Deploy/Demo (MVP-2, core product)
4. US3 → Tag management with GBIF → Deploy/Demo
5. US4 → Clip-level batch annotation → Deploy/Demo
6. US5 → Quality control via review → Deploy/Demo
7. US6 → Data export for analysis → Deploy/Demo

### SSA Delegation Strategy

| Phase | SSA (subagent_type) | Notes |
|-------|---------------------|-------|
| Phase 1 models | `backend-developer` | All SQLAlchemy models in parallel |
| Phase 1 schemas | `backend-developer` | All Pydantic schemas in parallel |
| Phase 1 types | `frontend-developer` | TypeScript types |
| Phase 2 repos | `backend-developer` | All repositories in parallel |
| US1-US6 backend | `backend-developer` | Service + API per story |
| US1-US6 frontend | `frontend-developer` | Components + pages per story |
| US2 worker | `backend-developer` | Celery task generation |
| Phase 9 tests | `test-automator` | Integration tests |

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Constitution requires TDD: write tests FIRST, verify they FAIL, then implement
- Auto-save (research.md §8) should be implemented in US2 workspace page
- GBIF proxy endpoint (research.md §2) should be implemented in US3
- Geometry validation (research.md §3) should be in AnnotationService
- Batch task generation (research.md §5) uses Celery, implemented in US2
- Export formats (research.md §6) implemented in US6
