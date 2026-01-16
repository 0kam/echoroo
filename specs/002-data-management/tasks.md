# Tasks: Data Management

**Input**: Design documents from `/specs/002-data-management/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Contract tests are required per constitution (II. TDD). Test tasks are included in Phase 12 after all implementation phases.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and new dependencies

- [x] T001 Add h3, soundfile, mutagen dependencies to apps/api/pyproject.toml
- [x] T002 [P] Add h3-js, mapbox-gl, wavesurfer.js dependencies to apps/web/package.json
- [x] T003 [P] Add AUDIO_ROOT and SPECTROGRAM_CACHE_DIR environment variables to .env.example
- [x] T004 Create enum definitions (DatasetVisibility, DatasetStatus, DatetimeParseStatus) in apps/api/echoroo/models/enums.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**CRITICAL**: No user story work can begin until this phase is complete

### Database Migrations

- [x] T005 Create Alembic migration for sites table in apps/api/alembic/versions/
- [x] T006 Create Alembic migration for datasets table in apps/api/alembic/versions/
- [x] T007 Create Alembic migration for recordings table in apps/api/alembic/versions/
- [x] T008 Create Alembic migration for clips table in apps/api/alembic/versions/

### Core Models

- [x] T009 [P] Create Site SQLAlchemy model in apps/api/echoroo/models/site.py
- [x] T010 [P] Create Dataset SQLAlchemy model in apps/api/echoroo/models/dataset.py
- [x] T011 [P] Create Recording SQLAlchemy model in apps/api/echoroo/models/recording.py
- [x] T012 [P] Create Clip SQLAlchemy model in apps/api/echoroo/models/clip.py
- [x] T013 Export new models from apps/api/echoroo/models/__init__.py

### Core Schemas

- [x] T014 [P] Create Site Pydantic schemas in apps/api/echoroo/schemas/site.py
- [x] T015 [P] Create Dataset Pydantic schemas in apps/api/echoroo/schemas/dataset.py
- [x] T016 [P] Create Recording Pydantic schemas in apps/api/echoroo/schemas/recording.py
- [x] T017 [P] Create Clip Pydantic schemas in apps/api/echoroo/schemas/clip.py
- [x] T018 Export new schemas from apps/api/echoroo/schemas/__init__.py

### Core Repositories

- [x] T019 [P] Create SiteRepository in apps/api/echoroo/repositories/site.py
- [x] T020 [P] Create DatasetRepository in apps/api/echoroo/repositories/dataset.py
- [x] T021 [P] Create RecordingRepository in apps/api/echoroo/repositories/recording.py
- [x] T022 [P] Create ClipRepository in apps/api/echoroo/repositories/clip.py
- [x] T023 Export new repositories from apps/api/echoroo/repositories/__init__.py

### Audio Processing Utilities

- [x] T024 Create AudioService with metadata extraction (soundfile/mutagen) in apps/api/echoroo/services/audio.py
- [x] T025 Add spectrogram generation utilities to apps/api/echoroo/services/audio.py
- [x] T026 Add audio resampling for playback to apps/api/echoroo/services/audio.py

### Frontend Types

- [x] T027 [P] Create TypeScript types for Site, Dataset, Recording, Clip in apps/web/src/lib/types/data.ts

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Site Creation and Management (Priority: P1) MVP

**Goal**: Enable researchers to define geographic locations (sites) using Uber H3 hexagonal cells for organizing recording data spatially.

**Independent Test**: Create a site by selecting an H3 hex on a map, then verify the site appears in the site list and can be associated with datasets.

### Backend Implementation for US1

- [x] T028 [P] [US1] Create SiteService with CRUD operations in apps/api/echoroo/services/site.py
- [x] T029 [P] [US1] Create H3 utility functions (validate, from_coordinates, to_boundary) in apps/api/echoroo/services/h3_utils.py
- [x] T030 [US1] Create Sites API endpoints (list, create, get, update, delete) in apps/api/echoroo/api/v1/sites.py
- [x] T031 [US1] Create H3 utility endpoints (validate, from-coordinates) in apps/api/echoroo/api/v1/h3.py
- [x] T032 [US1] Register sites and h3 routers in apps/api/echoroo/api/v1/__init__.py

### Frontend Implementation for US1

- [x] T033 [P] [US1] Create Sites API client in apps/web/src/lib/api/sites.ts
- [x] T034 [P] [US1] Create H3 API client in apps/web/src/lib/api/h3.ts
- [x] T035 [US1] Create H3MapPicker component for site selection in apps/web/src/lib/components/map/H3MapPicker.svelte
- [x] T036 [US1] Create SiteList component in apps/web/src/lib/components/data/SiteList.svelte
- [x] T037 [US1] Create SiteForm component (create/edit) in apps/web/src/lib/components/data/SiteForm.svelte
- [x] T038 [US1] Create Sites management page in apps/web/src/routes/(app)/projects/[id]/sites/+page.svelte
- [x] T039 [US1] Create Site detail page in apps/web/src/routes/(app)/projects/[id]/sites/[siteId]/+page.svelte

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - Audio Dataset Import (Priority: P1) MVP

**Goal**: Enable researchers to import collections of audio recordings with metadata extraction (datetime patterns, sample rate, duration).

**Independent Test**: Upload an audio file directory, verify recordings appear with extracted metadata.

### Backend Implementation for US2

- [x] T040 [P] [US2] Create DatasetService with CRUD operations in apps/api/echoroo/services/dataset.py
- [x] T041 [US2] Add import functionality (scan directory, extract metadata) to DatasetService in apps/api/echoroo/services/dataset.py
- [x] T042 [US2] Add datetime pattern parsing logic to DatasetService in apps/api/echoroo/services/dataset.py
- [x] T043 [US2] Create Celery import task in apps/api/echoroo/workers/import_task.py
- [x] T044 [US2] Create Datasets API endpoints (list, create, get, update, delete) in apps/api/echoroo/api/v1/datasets.py
- [x] T045 [US2] Add import/rescan endpoints to Datasets API in apps/api/echoroo/api/v1/datasets.py
- [x] T046 [US2] Add statistics endpoint to Datasets API in apps/api/echoroo/api/v1/datasets.py
- [x] T047 [US2] Create directories listing endpoint in apps/api/echoroo/api/v1/datasets.py
- [x] T048 [US2] Register datasets router in apps/api/echoroo/api/v1/__init__.py

### Frontend Implementation for US2

- [x] T049 [P] [US2] Create Datasets API client in apps/web/src/lib/api/datasets.ts
- [x] T050 [US2] Create DatasetList component in apps/web/src/lib/components/data/DatasetList.svelte
- [x] T051 [US2] Create DatasetForm component (create/edit) in apps/web/src/lib/components/data/DatasetForm.svelte
- [x] T052 [US2] Create DirectoryBrowser component in apps/web/src/lib/components/data/DirectoryBrowser.svelte
- [x] T053 [US2] Create DatetimePatternTester component in apps/web/src/lib/components/data/DatetimePatternTester.svelte
- [x] T054 [US2] Create ImportProgress component in apps/web/src/lib/components/data/ImportProgress.svelte
- [x] T055 [US2] Create DatasetStatistics component in apps/web/src/lib/components/data/DatasetStatistics.svelte
- [x] T056 [US2] Create Datasets management page in apps/web/src/routes/(app)/projects/[id]/datasets/+page.svelte
- [x] T057 [US2] Create Dataset detail page in apps/web/src/routes/(app)/projects/[id]/datasets/[datasetId]/+page.svelte

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Recording Browsing and Exploration (Priority: P1) MVP

**Goal**: Enable researchers to browse imported recordings, view metadata, play audio with spectrogram visualization.

**Independent Test**: Import sample recordings, verify list display, filtering, spectrogram generation, and audio playback.

### Backend Implementation for US3

- [x] T058 [P] [US3] Create RecordingService with CRUD operations in apps/api/echoroo/services/recording.py
- [x] T059 [US3] Add search across datasets functionality to RecordingService in apps/api/echoroo/services/recording.py
- [x] T060 [US3] Create Recordings API endpoints (list, search, get, update, delete) in apps/api/echoroo/api/v1/recordings.py
- [x] T061 [US3] Add audio streaming endpoint with HTTP Range support in apps/api/echoroo/api/v1/recordings.py
- [x] T062 [US3] Add playback endpoint with resampling for browser compatibility in apps/api/echoroo/api/v1/recordings.py
- [x] T063 [US3] Add spectrogram generation endpoint in apps/api/echoroo/api/v1/recordings.py
- [x] T064 [US3] Add download endpoint in apps/api/echoroo/api/v1/recordings.py
- [x] T065 [US3] Register recordings router in apps/api/echoroo/api/v1/__init__.py

### Frontend Implementation for US3

- [x] T066 [P] [US3] Create Recordings API client in apps/web/src/lib/api/recordings.ts
- [x] T067 [US3] Create RecordingList component with filtering in apps/web/src/lib/components/data/RecordingList.svelte
- [x] T068 [US3] Create SpectrogramViewer component in apps/web/src/lib/components/audio/SpectrogramViewer.svelte
- [x] T069 [US3] Create AudioPlayer component with WaveSurfer.js in apps/web/src/lib/components/audio/AudioPlayer.svelte
- [x] T070 [US3] Create PlaybackSpeedControl component in apps/web/src/lib/components/audio/PlaybackSpeedControl.svelte
- [x] T071 [US3] Create RecordingDetail component in apps/web/src/lib/components/data/RecordingDetail.svelte
- [x] T072 [US3] Create Recordings browser page in apps/web/src/routes/(app)/projects/[id]/recordings/+page.svelte
- [x] T073 [US3] Create Recording detail page in apps/web/src/routes/(app)/projects/[id]/recordings/[recordingId]/+page.svelte

**Checkpoint**: At this point, User Stories 1, 2, AND 3 should all work independently (Core MVP complete)

---

## Phase 6: User Story 4 - Clip Creation and Management (Priority: P2)

**Goal**: Enable researchers to create time segments (clips) from recordings for annotation and analysis.

**Independent Test**: Create clips from a recording, verify list display, playback, and spectrogram.

### Backend Implementation for US4

- [x] T074 [P] [US4] Create ClipService with CRUD operations in apps/api/echoroo/services/clip.py
- [x] T075 [US4] Add auto-generate clips functionality to ClipService in apps/api/echoroo/services/clip.py
- [x] T076 [US4] Create Clips API endpoints (list, create, get, update, delete) in apps/api/echoroo/api/v1/clips.py
- [x] T077 [US4] Add generate endpoint for auto-clip creation in apps/api/echoroo/api/v1/clips.py
- [x] T078 [US4] Add clip audio/spectrogram/download endpoints in apps/api/echoroo/api/v1/clips.py
- [x] T079 [US4] Register clips router in apps/api/echoroo/api/v1/__init__.py

### Frontend Implementation for US4

- [x] T080 [P] [US4] Create Clips API client in apps/web/src/lib/api/clips.ts
- [x] T081 [US4] Create ClipList component in apps/web/src/lib/components/data/ClipList.svelte
- [x] T082 [US4] Create ClipCreator component (time range selection) in apps/web/src/lib/components/audio/ClipCreator.svelte
- [x] T083 [US4] Create AutoClipGenerator component in apps/web/src/lib/components/data/AutoClipGenerator.svelte
- [x] T084 [US4] Create ClipDetail component in apps/web/src/lib/components/data/ClipDetail.svelte
- [x] T085 [US4] Integrate clip creation into Recording detail page apps/web/src/routes/(app)/projects/[id]/recordings/[recordingId]/+page.svelte

**Checkpoint**: At this point, User Story 4 should be fully functional

---

## Phase 7: User Story 5 - Custom Metadata Management (Priority: P2)

**Goal**: Enable researchers to add notes to recordings and clips for organization and search.

**Independent Test**: Add notes to recordings and clips, verify they are saved and displayed.

### Backend Implementation for US5

- [x] T086 [US5] Add note field handling to RecordingService in apps/api/echoroo/services/recording.py
- [x] T087 [US5] Add note field handling to ClipService in apps/api/echoroo/services/clip.py

### Frontend Implementation for US5

- [x] T088 [US5] Create NoteEditor component in apps/web/src/lib/components/data/NoteEditor.svelte
- [x] T089 [US5] Integrate NoteEditor into RecordingDetail in apps/web/src/lib/components/data/RecordingDetail.svelte
- [x] T090 [US5] Integrate NoteEditor into ClipDetail in apps/web/src/lib/components/data/ClipDetail.svelte

**Checkpoint**: At this point, User Story 5 should be fully functional

---

## Phase 8: User Story 6 - Audio Processing Settings (Priority: P3)

**Goal**: Enable researchers to customize spectrogram parameters and audio filters.

**Independent Test**: Change spectrogram parameters, verify visualization updates accordingly.

### Backend Implementation for US6

- [x] T091 [US6] Add PCEN normalization to spectrogram generation in apps/api/echoroo/services/audio.py
- [x] T092 [US6] Add highpass/lowpass filter support in apps/api/echoroo/services/audio.py
- [x] T093 [US6] Add multi-channel selection support in apps/api/echoroo/services/audio.py

### Frontend Implementation for US6

- [x] T094 [US6] Create SpectrogramSettings component in apps/web/src/lib/components/audio/SpectrogramSettings.svelte
- [x] T095 [US6] Create ColorMapPicker component in apps/web/src/lib/components/audio/ColorMapPicker.svelte
- [x] T096 [US6] Create AudioFilterSettings component in apps/web/src/lib/components/audio/AudioFilterSettings.svelte
- [x] T097 [US6] Integrate settings components into SpectrogramViewer in apps/web/src/lib/components/audio/SpectrogramViewer.svelte

**Checkpoint**: At this point, User Story 6 should be fully functional

---

## Phase 9: User Story 7 - Dataset Visibility and Sharing (Priority: P3)

**Goal**: Enable researchers to control access to datasets (private/public).

**Independent Test**: Create datasets with different visibility settings, verify access control.

### Backend Implementation for US7

- [x] T098 [US7] Add visibility-based access control to DatasetService in apps/api/echoroo/services/dataset.py
- [x] T099 [US7] Add visibility filtering to dataset list endpoint in apps/api/echoroo/api/v1/datasets.py

### Frontend Implementation for US7

- [x] T100 [US7] Create VisibilitySelector component in apps/web/src/lib/components/data/VisibilitySelector.svelte
- [x] T101 [US7] Integrate VisibilitySelector into DatasetForm in apps/web/src/lib/components/data/DatasetForm.svelte

**Checkpoint**: At this point, User Story 7 should be fully functional

---

## Phase 10: User Story 8 - Dataset and Recording Export (Priority: P2)

**Goal**: Enable researchers to export datasets in CamtrapDP format and download recordings.

**Independent Test**: Export dataset, verify ZIP contains correct CSV files and optional audio.

### Backend Implementation for US8

- [x] T102 [P] [US8] Create CamtrapDP export service in apps/api/echoroo/services/export.py
- [x] T103 [US8] Add deployments.csv generation to export service in apps/api/echoroo/services/export.py
- [x] T104 [US8] Add media.csv generation to export service in apps/api/echoroo/services/export.py
- [x] T105 [US8] Add streaming ZIP generation to export service in apps/api/echoroo/services/export.py
- [x] T106 [US8] Add export endpoint to Datasets API in apps/api/echoroo/api/v1/datasets.py

### Frontend Implementation for US8

- [x] T107 [P] [US8] Create ExportDialog component in apps/web/src/lib/components/data/ExportDialog.svelte
- [x] T108 [US8] Create DownloadButton component in apps/web/src/lib/components/data/DownloadButton.svelte
- [x] T109 [US8] Integrate ExportDialog into Dataset detail page in apps/web/src/routes/(app)/projects/[id]/datasets/[datasetId]/+page.svelte
- [x] T110 [US8] Integrate DownloadButton into RecordingDetail in apps/web/src/lib/components/data/RecordingDetail.svelte

**Checkpoint**: At this point, User Story 8 should be fully functional

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T111 [P] Add keyboard shortcuts (space for play/pause) to AudioPlayer in apps/web/src/lib/components/audio/AudioPlayer.svelte
- [x] T112 [P] Add spectrogram viewport auto-scroll during playback in apps/web/src/lib/components/audio/SpectrogramViewer.svelte
- [x] T113 [P] Add spectrogram click-to-seek functionality in apps/web/src/lib/components/audio/SpectrogramViewer.svelte
- [x] T114 Add cascade delete warnings for Site/Dataset deletion in frontend
- [x] T115 Add error handling and user-friendly messages across all API endpoints

---

## Phase 12: Testing (Constitution Compliance)

**Purpose**: Contract tests per constitution II. TDD requirement

**Note**: Tests are added after implementation to enable rapid prototyping while maintaining constitution compliance before deployment.

### Backend Contract Tests

- [x] T119 [P] Create contract tests for Sites API in apps/api/tests/contract/test_sites.py
- [x] T120 [P] Create contract tests for Datasets API in apps/api/tests/contract/test_datasets.py
- [x] T121 [P] Create contract tests for Recordings API in apps/api/tests/contract/test_recordings.py
- [x] T122 [P] Create contract tests for Clips API in apps/api/tests/contract/test_clips.py

### Backend Integration Tests

- [x] T123 [P] Create integration tests for dataset import workflow in apps/api/tests/integration/test_dataset_import.py
- [x] T124 [P] Create integration tests for recording workflow in apps/api/tests/integration/test_recording_workflow.py

### Validation & Type Check

- [x] T125 Run mypy type check on backend (apps/api) - PASSED (0 errors in 81 files)
- [x] T126 Run svelte-check on frontend (apps/web) - PASSED (0 errors, 12 warnings)
- [x] T127 Run quickstart.md validation

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - US1 (Sites) → US2 (Datasets) → US3 (Recordings) must be sequential due to data hierarchy
  - US4 (Clips) depends on US3 (Recordings)
  - US5 (Notes) depends on US3 and US4
  - US6 (Audio Settings) can start after US3
  - US7 (Visibility) can start after US2
  - US8 (Export) depends on US2 and US3
- **Polish (Phase 11)**: Depends on all desired user stories being complete
- **Testing (Phase 12)**: Depends on implementation being complete; required before deployment per constitution

### User Story Dependencies

- **User Story 1 (P1 - Sites)**: Can start after Foundational (Phase 2)
- **User Story 2 (P1 - Datasets)**: Depends on US1 (Sites must exist to create datasets)
- **User Story 3 (P1 - Recordings)**: Depends on US2 (Datasets must exist to have recordings)
- **User Story 4 (P2 - Clips)**: Depends on US3 (Recordings must exist to create clips)
- **User Story 5 (P2 - Notes)**: Depends on US3 and US4 (needs recordings and clips)
- **User Story 6 (P3 - Audio Settings)**: Depends on US3 (needs recordings with spectrograms)
- **User Story 7 (P3 - Visibility)**: Depends on US2 (needs datasets)
- **User Story 8 (P2 - Export)**: Depends on US2 and US3 (needs datasets and recordings)

### Within Each User Story

- Models before repositories
- Repositories before services
- Services before API endpoints
- Backend before frontend (frontend depends on API)
- Core implementation before integration

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel
- All Foundational tasks marked [P] can run in parallel (within Phase 2)
- Backend and Frontend within same story can sometimes run in parallel if API contract is clear
- Different user stories marked [P] can run in parallel by different developers

---

## Parallel Example: Foundational Phase

```bash
# Launch all models in parallel:
Task: "Create Site SQLAlchemy model in apps/api/echoroo/models/site.py"
Task: "Create Dataset SQLAlchemy model in apps/api/echoroo/models/dataset.py"
Task: "Create Recording SQLAlchemy model in apps/api/echoroo/models/recording.py"
Task: "Create Clip SQLAlchemy model in apps/api/echoroo/models/clip.py"

# Launch all schemas in parallel (after models):
Task: "Create Site Pydantic schemas in apps/api/echoroo/schemas/site.py"
Task: "Create Dataset Pydantic schemas in apps/api/echoroo/schemas/dataset.py"
Task: "Create Recording Pydantic schemas in apps/api/echoroo/schemas/recording.py"
Task: "Create Clip Pydantic schemas in apps/api/echoroo/schemas/clip.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1-3 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1 (Sites)
4. Complete Phase 4: User Story 2 (Datasets)
5. Complete Phase 5: User Story 3 (Recordings)
6. **STOP and VALIDATE**: Test core workflow independently
7. Deploy/demo if ready (MVP!)

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 (Sites) → Test independently
3. Add User Story 2 (Datasets) → Test independently
4. Add User Story 3 (Recordings) → Test independently → Deploy/Demo (MVP!)
5. Add User Story 4 (Clips) → Test independently
6. Add User Story 5 (Notes) → Test independently
7. Add User Story 8 (Export) → Test independently
8. Add User Story 6 (Audio Settings) → Test independently
9. Add User Story 7 (Visibility) → Test independently
10. Each story adds value without breaking previous stories

### SSA Delegation Strategy

| Phase | Tasks | Recommended SSA |
|-------|-------|-----------------|
| Setup | T001-T004 | backend-developer |
| Foundational - Models | T005-T013 | backend-developer |
| Foundational - Schemas | T014-T018 | backend-developer |
| Foundational - Repos | T019-T023 | backend-developer |
| Foundational - Audio | T024-T026 | backend-developer |
| Foundational - Types | T027 | frontend-developer |
| US1-8 Backend | T028-T032, T040-T048, etc. | backend-developer |
| US1-8 Frontend | T033-T039, T049-T057, etc. | frontend-developer |
| Polish - Audio UX | T111-T113 | frontend-developer |
| Polish - Warnings/Errors | T114-T115 | frontend-developer |
| Testing - Contract | T119-T122 | backend-developer |
| Testing - Integration | T123-T124 | backend-developer |
| Testing - Validation | T125-T127 | backend-developer + frontend-developer |

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Data hierarchy constraint: Sites → Datasets → Recordings → Clips (must respect this order)
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
