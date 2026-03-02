# Tasks: Detection Review

**Input**: Design documents from `/specs/003-detection-review/`
**Prerequisites**: plan.md (required), spec.md (required)
**Replaces**: Old `003-annotation` tasks

**Tests**: TDD approach per constitution - tests are REQUIRED for all API endpoints and services.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Backend**: `apps/api/echoroo/` (FastAPI)
- **Frontend**: `apps/web/src/` (SvelteKit)
- **Backend Tests**: `apps/api/tests/`
- **Frontend Tests**: `apps/web/tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: New enums, dependencies, and configuration

- [ ] T001 [P] Add new enums (DetectionSource, DetectionStatus, DetectionRunStatus) to apps/api/echoroo/models/enums.py
- [ ] T002 [P] Create TypeScript types for Detection, ConfirmedRegion, DetectionRun, SpeciesSummary in apps/web/src/lib/types/detection.ts
- [ ] T003 [P] Add detection types to apps/web/src/lib/types/index.ts

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**CRITICAL**: No user story work can begin until this phase is complete

### Database Migrations

- [ ] T004 Create Alembic migration for `annotations` table (new table, NOT modifying old annotation tables) in apps/api/alembic/versions/
- [ ] T005 Create Alembic migration for `confirmed_regions` table in apps/api/alembic/versions/
- [ ] T006 Create Alembic migration for `detection_runs` table in apps/api/alembic/versions/

### Core Models

- [ ] T007 [P] Create Annotation SQLAlchemy model in apps/api/echoroo/models/annotation.py (recording_id FK, tag_id FK, detection_run_id FK, source, status, confidence, start_time, end_time, freq_low, freq_high, reviewed_by_id, reviewed_at)
- [ ] T008 [P] Create ConfirmedRegion SQLAlchemy model in apps/api/echoroo/models/confirmed_region.py (recording_id FK, start_time, end_time, reviewed_by_id)
- [ ] T009 [P] Create DetectionRun SQLAlchemy model in apps/api/echoroo/models/detection_run.py (project_id FK, dataset_id FK, model_name, model_version, parameters JSONB, status, annotation_count, started_at, completed_at, error_message)
- [ ] T010 Export new models from apps/api/echoroo/models/__init__.py (add Annotation, ConfirmedRegion, DetectionRun and new enums)

### Core Schemas

- [ ] T011 [P] Create Detection Pydantic schemas in apps/api/echoroo/schemas/detection.py (DetectionCreate, DetectionUpdate, DetectionResponse, DetectionListResponse, SpeciesSummaryResponse, ConfirmRequest, ChangeSpeciesRequest)
- [ ] T012 [P] Create ConfirmedRegion Pydantic schemas in apps/api/echoroo/schemas/confirmed_region.py (ConfirmedRegionCreate, ConfirmedRegionResponse, ConfirmedRegionListResponse)
- [ ] T013 [P] Create DetectionRun Pydantic schemas in apps/api/echoroo/schemas/detection_run.py (DetectionRunCreate, DetectionRunUpdate, DetectionRunResponse, DetectionRunListResponse)

### Core Repositories

- [ ] T014 [P] Create AnnotationRepository in apps/api/echoroo/repositories/annotation.py (CRUD + species_summary aggregation query + filters: tag_id, status, confidence range, dataset_id, recording_id)
- [ ] T015 [P] Create ConfirmedRegionRepository in apps/api/echoroo/repositories/confirmed_region.py (CRUD + list by recording_id)
- [ ] T016 [P] Create DetectionRunRepository in apps/api/echoroo/repositories/detection_run.py (CRUD + list by project_id)

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 3 - Detection Data Model & API (Priority: P1) MVP

**Goal**: Provide the complete backend API for detections, confirmed regions, and detection runs. This is the foundation for all frontend stories.

**Independent Test**: Call API endpoints directly to verify CRUD operations and aggregation queries.

### Tests for User Story 3

- [ ] T017 [P] [US3] Contract test for GET /api/v1/projects/{id}/detections in apps/api/tests/contract/test_detections.py
- [ ] T018 [P] [US3] Contract test for GET /api/v1/projects/{id}/detections/species-summary in apps/api/tests/contract/test_detections.py
- [ ] T019 [P] [US3] Contract test for POST /api/v1/projects/{id}/detections in apps/api/tests/contract/test_detections.py
- [ ] T020 [P] [US3] Contract test for POST /api/v1/projects/{id}/detections/{id}/confirm in apps/api/tests/contract/test_detections.py
- [ ] T021 [P] [US3] Contract test for POST /api/v1/projects/{id}/detections/{id}/reject in apps/api/tests/contract/test_detections.py
- [ ] T022 [P] [US3] Contract test for POST /api/v1/projects/{id}/detections/{id}/change-species in apps/api/tests/contract/test_detections.py
- [ ] T023 [P] [US3] Contract test for confirmed regions CRUD in apps/api/tests/contract/test_confirmed_regions.py
- [ ] T024 [P] [US3] Contract test for detection runs CRUD in apps/api/tests/contract/test_detection_runs.py
- [ ] T025 [P] [US3] Integration test for review workflow (create detection -> confirm with time range -> verify ConfirmedRegion) in apps/api/tests/integration/test_review_workflow.py

### Implementation for User Story 3

- [ ] T026 [US3] Create DetectionService in apps/api/echoroo/services/detection.py (list with filters, species_summary, create, confirm with ConfirmedRegion creation, reject, change_species)
- [ ] T027 [US3] Create ConfirmedRegionService in apps/api/echoroo/services/confirmed_region.py (CRUD, list by recording)
- [ ] T028 [US3] Create DetectionRunService in apps/api/echoroo/services/detection_run.py (CRUD, update status)
- [ ] T029 [US3] Create detections router in apps/api/echoroo/api/v1/detections.py (list, species-summary, get, create, confirm, reject, change-species, delete)
- [ ] T030 [US3] Create confirmed_regions router in apps/api/echoroo/api/v1/confirmed_regions.py (list, create, delete)
- [ ] T031 [US3] Create detection_runs router in apps/api/echoroo/api/v1/detection_runs.py (list, get, create, update)
- [ ] T032 [US3] Register new routers in apps/api/echoroo/api/v1/__init__.py

**Checkpoint**: Backend API fully functional - frontend work can begin

---

## Phase 4: User Story 1 - Species List View (Priority: P1) MVP

**Goal**: Display species-level detection summary as the main entry point.

**Independent Test**: Open Detections page, verify species list with counts, confidence, and review progress.

### Frontend Implementation for US1

- [ ] T033 [P] [US1] Create Detections API client in apps/web/src/lib/api/detections.ts (listDetections, getSpeciesSummary, confirmDetection, rejectDetection, changeSpecies)
- [ ] T034 [P] [US1] Create SpeciesListItem component in apps/web/src/lib/components/detection/SpeciesListItem.svelte (species name, detection count, avg confidence, review progress bar)
- [ ] T035 [US1] Create SpeciesListView component in apps/web/src/lib/components/detection/SpeciesListView.svelte (species list with search, filter, sort)
- [ ] T036 [US1] Create DetectionFilters component in apps/web/src/lib/components/detection/DetectionFilters.svelte (status filter, dataset filter, confidence range, search)
- [ ] T037 [US1] Create Detections page in apps/web/src/routes/(app)/projects/[id]/detections/+page.svelte (renders SpeciesListView)

**Checkpoint**: Species List View functional - users can see what species were detected

---

## Phase 5: User Story 2 - Detection Review UI (Priority: P1) MVP

**Goal**: Card-based detection review with mini spectrograms, playback, and time range selection.

**Independent Test**: Click species, review cards with Confirm/Reject, verify time range selection and status updates.

### Frontend Implementation for US2

- [ ] T038 [P] [US2] Create MiniSpectrogram component in apps/web/src/lib/components/detection/MiniSpectrogram.svelte (compact spectrogram with ML detection highlight overlay, reuses existing spectrogram endpoint)
- [ ] T039 [P] [US2] Create TimeRangeSelector component in apps/web/src/lib/components/detection/TimeRangeSelector.svelte (drag-to-select on mini spectrogram, returns start_time/end_time)
- [ ] T040 [P] [US2] Create ReviewActions component in apps/web/src/lib/components/detection/ReviewActions.svelte (Confirm/Reject buttons, keyboard shortcuts C/R/Space)
- [ ] T041 [P] [US2] Create SpeciesCorrector component in apps/web/src/lib/components/detection/SpeciesCorrector.svelte (dropdown to change species tag, reuses TagSelector pattern)
- [ ] T042 [US2] Create DetectionCard component in apps/web/src/lib/components/detection/DetectionCard.svelte (assembles MiniSpectrogram + playback + ReviewActions + metadata)
- [ ] T043 [US2] Create DetectionReviewGrid component in apps/web/src/lib/components/detection/DetectionReviewGrid.svelte (card grid with pagination, filter bar, confidence slider)
- [ ] T044 [US2] Create Detection Review page in apps/web/src/routes/(app)/projects/[id]/detections/[tagId]/+page.svelte (renders DetectionReviewGrid for selected species)
- [ ] T045 [US2] Add keyboard shortcut handler for Detection Review (C=Confirm, R=Reject, Space=play, Arrow keys=navigate cards) in DetectionReviewGrid

**Checkpoint**: Core review workflow functional - users can review and confirm/reject detections

---

## Phase 6: User Story 5 - Navigation Restructure (Priority: P2)

**Goal**: Update project sidebar to 5 items per VISION.md.

**Independent Test**: Verify sidebar shows 5 items and routes work correctly.

### Frontend Implementation for US5

- [ ] T046 [US5] Update project layout navigation in apps/web/src/routes/(app)/projects/[id]/+layout.svelte (change to 5 items: Overview, Sites & Data, Detections, Reports, Settings)
- [ ] T047 [P] [US5] Create Sites & Data combined page in apps/web/src/routes/(app)/projects/[id]/data/+page.svelte (unified view with tabs for Sites, Datasets, Recordings)
- [ ] T048 [P] [US5] Create Reports page in apps/web/src/routes/(app)/projects/[id]/reports/+page.svelte (export options: Detection CSV, ML Dataset)

**Checkpoint**: New navigation active

---

## Phase 7: User Story 4 - Detection Export (Priority: P2)

**Goal**: Export detections as CSV and ML training dataset.

**Independent Test**: Export CSV and ML dataset, verify output format and content.

### Tests for User Story 4

- [ ] T049 [P] [US4] Contract test for GET /api/v1/projects/{id}/detections/export/csv in apps/api/tests/contract/test_detection_export.py
- [ ] T050 [P] [US4] Contract test for GET /api/v1/projects/{id}/detections/export/ml-dataset in apps/api/tests/contract/test_detection_export.py
- [ ] T051 [P] [US4] Integration test for CSV export content in apps/api/tests/integration/test_detection_export.py
- [ ] T052 [P] [US4] Integration test for ML dataset export (audio clips + annotations.csv + metadata.json) in apps/api/tests/integration/test_detection_export.py

### Backend Implementation for US4

- [ ] T053 [US4] Create DetectionExportService in apps/api/echoroo/services/detection_export.py (CSV generation with VISION.md format, ML dataset ZIP generation with audio clips + annotations.csv + metadata.json + README.txt)
- [ ] T054 [US4] Add export endpoints to detections router in apps/api/echoroo/api/v1/detections.py (GET /export/csv, GET /export/ml-dataset with streaming response)

### Frontend Implementation for US4

- [ ] T055 [P] [US4] Create DetectionExportDialog component in apps/web/src/lib/components/detection/DetectionExportDialog.svelte (format selection, filter options, download trigger)
- [ ] T056 [P] [US4] Create Export API client in apps/web/src/lib/api/detection-export.ts (exportCSV, exportMLDataset with filter params)
- [ ] T057 [US4] Integrate DetectionExportDialog into Reports page apps/web/src/routes/(app)/projects/[id]/reports/+page.svelte
- [ ] T058 [US4] Add export button to Species List View in apps/web/src/lib/components/detection/SpeciesListView.svelte

**Checkpoint**: Export functionality complete

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T059 [P] Add loading states and skeleton UI to SpeciesListView and DetectionReviewGrid
- [ ] T060 [P] Add error handling and empty state messages across all detection components
- [ ] T061 [P] Add review progress animation (card transitions when confirmed/rejected)
- [ ] T062 [P] Run mypy type check on backend (apps/api)
- [ ] T063 [P] Run svelte-check on frontend (apps/web)
- [ ] T064 [P] Run ruff linter on backend (apps/api)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Story 3 (Phase 3)**: Depends on Foundational - Backend API (BLOCKS frontend stories)
- **User Story 1 (Phase 4)**: Depends on US3 (needs species-summary API)
- **User Story 2 (Phase 5)**: Depends on US3 (needs detection CRUD API) + US1 (navigation from species list)
- **User Story 5 (Phase 6)**: Can start after US1 (needs Detections route to exist)
- **User Story 4 (Phase 7)**: Depends on US3 (needs detection data to export)
- **Polish (Phase 8)**: Depends on all desired user stories being complete

### User Story Dependencies

```
Setup (Phase 1)
    │
    ▼
Foundational (Phase 2)
    │
    ▼
[US3] Detection Data Model & API (P1)
    │
    ├────────────────────┐
    │                    │
    ▼                    ▼
[US1] Species List    [US4] Detection Export
  View (P1)             (P2)
    │
    ▼
[US2] Detection Review (P1)
    │
    ▼
[US5] Navigation Restructure (P2)
```

### Within Each User Story

1. Tests MUST be written and FAIL before implementation (TDD)
2. Models before repositories
3. Repositories before services
4. Services before routers
5. Backend before frontend
6. Story complete before moving to next priority

### Parallel Opportunities

**Phase 1 (all parallel)**:
- T001, T002, T003

**Phase 2 (parallel groups)**:
- T007, T008, T009 (models)
- T011, T012, T013 (schemas)
- T014, T015, T016 (repositories)

**Phase 3 (tests parallel, then implementation sequential)**:
- T017-T025 (all tests in parallel)
- T026, T027, T028 (services in parallel where possible)

**Phase 4 + 5 (frontend parallel within story)**:
- T033, T034 (parallel)
- T038, T039, T040, T041 (parallel)

**Phase 7 (tests parallel, backend then frontend)**:
- T049-T052 (all tests in parallel)
- T055, T056 (frontend parallel)

---

## Parallel Example: Foundational Phase

```bash
# Launch all models in parallel:
Task: "Create Annotation SQLAlchemy model in apps/api/echoroo/models/annotation.py"
Task: "Create ConfirmedRegion SQLAlchemy model in apps/api/echoroo/models/confirmed_region.py"
Task: "Create DetectionRun SQLAlchemy model in apps/api/echoroo/models/detection_run.py"

# Launch all schemas in parallel (after models):
Task: "Create Detection Pydantic schemas in apps/api/echoroo/schemas/detection.py"
Task: "Create ConfirmedRegion schemas in apps/api/echoroo/schemas/confirmed_region.py"
Task: "Create DetectionRun schemas in apps/api/echoroo/schemas/detection_run.py"

# Launch all repositories in parallel (after schemas):
Task: "Create AnnotationRepository in apps/api/echoroo/repositories/annotation.py"
Task: "Create ConfirmedRegionRepository in apps/api/echoroo/repositories/confirmed_region.py"
Task: "Create DetectionRunRepository in apps/api/echoroo/repositories/detection_run.py"
```

---

## Parallel Example: User Story 2 Frontend Components

```bash
# Launch independent components in parallel:
Task: "Create MiniSpectrogram component in apps/web/src/lib/components/detection/MiniSpectrogram.svelte"
Task: "Create TimeRangeSelector component in apps/web/src/lib/components/detection/TimeRangeSelector.svelte"
Task: "Create ReviewActions component in apps/web/src/lib/components/detection/ReviewActions.svelte"
Task: "Create SpeciesCorrector component in apps/web/src/lib/components/detection/SpeciesCorrector.svelte"

# Then assemble (depends on above):
Task: "Create DetectionCard component in apps/web/src/lib/components/detection/DetectionCard.svelte"
Task: "Create DetectionReviewGrid component in apps/web/src/lib/components/detection/DetectionReviewGrid.svelte"
```

---

## Implementation Strategy

### MVP First (P1 Stories Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 3 (Detection Data Model & API)
4. Complete Phase 4: User Story 1 (Species List View)
5. Complete Phase 5: User Story 2 (Detection Review UI)
6. **STOP and VALIDATE**: Test all P1 stories independently
7. Deploy/demo if ready - **This is the MVP!**

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add User Story 3 (API) → Test → Backend functional
3. Add User Story 1 (Species List) → Test → Users can see detections
4. Add User Story 2 (Review UI) → Test → Core review workflow functional (MVP!)
5. Add User Story 5 (Navigation) → Test → Clean navigation
6. Add User Story 4 (Export) → Test → Full feature complete

### SSA Delegation Strategy

| Phase | Tasks | Recommended SSA |
|-------|-------|-----------------|
| Setup | T001-T003 | backend-developer (T001) + frontend-developer (T002-T003) |
| Foundational - Migrations | T004-T006 | backend-developer |
| Foundational - Models | T007-T010 | backend-developer |
| Foundational - Schemas | T011-T013 | backend-developer |
| Foundational - Repos | T014-T016 | backend-developer |
| US3 - Tests | T017-T025 | backend-developer |
| US3 - Services/API | T026-T032 | backend-developer |
| US1 - Frontend | T033-T037 | frontend-developer |
| US2 - Frontend | T038-T045 | frontend-developer |
| US5 - Navigation | T046-T048 | frontend-developer |
| US4 - Tests | T049-T052 | backend-developer |
| US4 - Backend | T053-T054 | backend-developer |
| US4 - Frontend | T055-T058 | frontend-developer |
| Polish | T059-T064 | backend-developer + frontend-developer |

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing (TDD per constitution)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Old annotation models (AnnotationProject, AnnotationTask, ClipAnnotation, SoundEventAnnotation) remain in codebase but are NOT used by this feature
- Old annotation routes/services remain registered for backward compatibility but can be deprecated in a future PR
- The `annotations` table is a NEW table (not renaming any old table)
- Tag model is reused as-is; Annotation.tag_id references existing tags table
- Recording model is reused as-is; Annotation.recording_id references existing recordings table
- MiniSpectrogram component should reuse the existing spectrogram endpoint from apps/api/echoroo/api/v1/recordings.py
- AudioPlayer from apps/web/src/lib/components/audio/AudioPlayer.svelte can be reused for playback in DetectionCard