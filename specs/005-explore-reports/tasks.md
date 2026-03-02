# Tasks: Explore, Reports & Export

**Input**: Design documents from `/specs/005-explore-reports/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

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

## Phase 1: Shared Models & Infrastructure

**Purpose**: New database models and shared infrastructure required by multiple user stories

### ConfirmedRegion Model (Prerequisite for US2, US3, US4)

- [ ] T001 [P] Create ConfirmedRegion model in apps/api/echoroo/models/confirmed_region.py (recording_id, start_time, end_time, reviewed_by_id, created_at; CheckConstraint end_time > start_time; Index on recording_id)
- [ ] T002 [P] Add ConfirmedRegion to apps/api/echoroo/models/__init__.py and apps/api/echoroo/models/enums.py (if new enums needed)
- [ ] T003 [P] Create ConfirmedRegion schemas in apps/api/echoroo/schemas/confirmed_region.py (Create, Response, List)
- [ ] T004 [P] Create ConfirmedRegionRepository in apps/api/echoroo/repositories/confirmed_region.py (CRUD, list_by_recording, get_unconfirmed_intervals)
- [ ] T005 Create ConfirmedRegionService in apps/api/echoroo/services/confirmed_region.py (create, list, get_unconfirmed_intervals)
- [ ] T006 Create Alembic migration for confirmed_regions table in apps/api/alembic/versions/

### ExportJob Model (Prerequisite for US4)

- [ ] T007 [P] Create ExportJob model in apps/api/echoroo/models/export_job.py (dataset_id, format enum [detection_csv, ml_training], status enum [queued, processing, completed, failed], file_path, created_by_id, created_at, completed_at, error_message)
- [ ] T008 [P] Add ExportJob to apps/api/echoroo/models/__init__.py; add ExportFormat and ExportStatus to enums.py
- [ ] T009 [P] Create ExportJob schemas in apps/api/echoroo/schemas/detection_export.py
- [ ] T010 [P] Create ExportJobRepository in apps/api/echoroo/repositories/export_job.py (CRUD, list_by_dataset)
- [ ] T011 Create Alembic migration for export_jobs table in apps/api/alembic/versions/

### Frontend Types

- [ ] T012 [P] Create explore types in apps/web/src/lib/types/explore.ts (SiteWithDetections, ExploreSearchResult, SpiralPlotData, SpeciesDetectionSummary)
- [ ] T013 [P] Create sampling types in apps/web/src/lib/types/sampling.ts (SamplingSession, SamplingSegment, SamplingConfig)

**Checkpoint**: Shared infrastructure ready - user story implementation can begin

---

## Phase 2: User Story 2 - Spiral Plot・データセット詳細強化 (Priority: P2)

**Goal**: Add Spiral Plot, review progress, and species detection list to dataset detail page

**Independent Test**: Open dataset detail page, verify Spiral Plot renders, species list shows, review progress displays

### Tests for User Story 2

- [ ] T014 [P] [US2] Contract test for GET /api/v1/projects/{id}/datasets/{datasetId}/spiral-plot in apps/api/tests/contract/test_spiral_plot.py
- [ ] T015 [P] [US2] Contract test for GET /api/v1/projects/{id}/datasets/{datasetId}/review-progress in apps/api/tests/contract/test_dataset_detail.py
- [ ] T016 [P] [US2] Contract test for GET /api/v1/projects/{id}/datasets/{datasetId}/species-summary in apps/api/tests/contract/test_dataset_detail.py
- [ ] T017 [P] [US2] Unit test for Spiral Plot data aggregation in apps/api/tests/unit/test_spiral_plot.py (hour x date bucketing, species filter)

### Implementation for User Story 2

- [ ] T018 [P] [US2] Create Spiral Plot schemas in apps/api/echoroo/schemas/spiral_plot.py (SpiralPlotRequest with species filter, SpiralPlotResponse with hour_buckets x date_buckets matrix)
- [ ] T019 [P] [US2] Create review progress and species summary schemas in apps/api/echoroo/schemas/dataset.py (ReviewProgressResponse, SpeciesDetectionSummary)
- [ ] T020 [US2] Create SpiralPlotService in apps/api/echoroo/services/spiral_plot.py (aggregate annotations by hour x date, apply species filter, return matrix data)
- [ ] T021 [US2] Add spiral-plot, review-progress, species-summary endpoints to datasets router in apps/api/echoroo/api/v1/datasets.py
- [ ] T022 [P] [US2] Create API client functions in apps/web/src/lib/api/datasets.ts (fetchSpiralPlot, fetchReviewProgress, fetchSpeciesSummary)
- [ ] T023 [US2] Create SpiralPlot.svelte component in apps/web/src/lib/components/visualization/SpiralPlot.svelte (Canvas-based heatmap: Y=hour 0-24, X=date; color intensity=detection count; transparent overlay for hover tooltips)
- [ ] T024 [P] [US2] Create ReviewProgress.svelte component in apps/web/src/lib/components/visualization/ReviewProgress.svelte (progress bar: confirmed/unreviewed/unprocessed)
- [ ] T025 [P] [US2] Create SpeciesDetectionList.svelte component in apps/web/src/lib/components/visualization/SpeciesDetectionList.svelte (sortable table: species name, detection count, confirmed count, percentage)
- [ ] T026 [US2] Enhance dataset detail page apps/web/src/routes/(app)/projects/[id]/datasets/[datasetId]/+page.svelte (add SpiralPlot, ReviewProgress, SpeciesDetectionList sections below existing content)

**Checkpoint**: Dataset detail page shows detection patterns, review progress, and species summary

---

## Phase 3: User Story 1 - Exploreビュー (Priority: P2)

**Goal**: Cross-project site search with H3 map and species filter

**Independent Test**: Open Explore page, verify map shows sites, search by species name, filter confirmed only

### Tests for User Story 1

- [ ] T027 [P] [US1] Contract test for GET /api/v1/explore/sites in apps/api/tests/contract/test_explore.py (returns sites with detection counts)
- [ ] T028 [P] [US1] Contract test for GET /api/v1/explore/sites?species=xxx in apps/api/tests/contract/test_explore.py (species filter)
- [ ] T029 [P] [US1] Contract test for GET /api/v1/explore/sites?confirmed_only=true in apps/api/tests/contract/test_explore.py (confirmed filter)
- [ ] T030 [P] [US1] Integration test for explore search flow in apps/api/tests/integration/test_explore_flow.py (multi-project, visibility checks)

### Implementation for User Story 1

- [ ] T031 [P] [US1] Create explore schemas in apps/api/echoroo/schemas/explore.py (ExploreSearchParams, ExploreSearchResult with site_id, h3_index, project_id, project_name, site_name, detection_count, species_list)
- [ ] T032 [US1] Create ExploreService in apps/api/echoroo/services/explore.py (search sites across projects with species/confirmed filters, respect project visibility and user permissions)
- [ ] T033 [US1] Create explore router in apps/api/echoroo/api/v1/explore.py (GET /explore/sites with query params: species, confirmed_only, bounds)
- [ ] T034 [US1] Register explore router in apps/api/echoroo/api/v1/__init__.py
- [ ] T035 [P] [US1] Create API client in apps/web/src/lib/api/explore.ts (searchSites)
- [ ] T036 [US1] Create ExploreMap.svelte component in apps/web/src/lib/components/explore/ExploreMap.svelte (extends H3MapPicker pattern: multi-site rendering, color by detection count, clickable hexagons)
- [ ] T037 [P] [US1] Create SpeciesSearch.svelte component in apps/web/src/lib/components/explore/SpeciesSearch.svelte (autocomplete search input, debounced API calls)
- [ ] T038 [P] [US1] Create SitePopup.svelte component in apps/web/src/lib/components/explore/SitePopup.svelte (site name, project, detection count, link to dataset)
- [ ] T039 [US1] Create Explore page in apps/web/src/routes/(app)/explore/+page.svelte (ExploreMap + SpeciesSearch + confirmed filter toggle + results list)

**Checkpoint**: Users can explore sites across projects and search by species

---

## Phase 4: User Story 3 - サンプリングレビュー (Priority: P2)

**Goal**: Generate random unconfirmed segments for efficient negative data creation

**Independent Test**: Start sampling review on dataset, review segments, create ConfirmedRegions

### Tests for User Story 3

- [ ] T040 [P] [US3] Unit test for sampling algorithm in apps/api/tests/unit/test_sampling_algo.py (unconfirmed interval calculation, random segment generation, no overlap with ConfirmedRegions, proportional distribution across recordings)
- [ ] T041 [P] [US3] Contract test for POST /api/v1/projects/{id}/datasets/{datasetId}/sampling-sessions in apps/api/tests/contract/test_sampling.py
- [ ] T042 [P] [US3] Contract test for GET /api/v1/projects/{id}/datasets/{datasetId}/sampling-sessions/{sessionId} in apps/api/tests/contract/test_sampling.py
- [ ] T043 [P] [US3] Contract test for PATCH /api/v1/projects/{id}/datasets/{datasetId}/sampling-sessions/{sessionId}/segments/{segmentId} in apps/api/tests/contract/test_sampling.py (mark reviewed, create ConfirmedRegion)
- [ ] T044 [P] [US3] Integration test for sampling review flow in apps/api/tests/integration/test_sampling_flow.py

### Implementation for User Story 3

- [ ] T045 [P] [US3] Create SamplingSession and SamplingSegment models in apps/api/echoroo/models/sampling.py (Session: dataset_id, user_id, segment_count, segment_duration_seconds, status enum; Segment: session_id, recording_id, start_time, end_time, status enum [pending, reviewed, skipped])
- [ ] T046 [P] [US3] Add Sampling models to apps/api/echoroo/models/__init__.py and enums
- [ ] T047 [P] [US3] Create sampling schemas in apps/api/echoroo/schemas/sampling.py (SessionCreate, SessionResponse, SegmentResponse, SegmentReview)
- [ ] T048 [P] [US3] Create SamplingRepository in apps/api/echoroo/repositories/sampling.py
- [ ] T049 [US3] Create SamplingService in apps/api/echoroo/services/sampling.py (create_session with segment generation algorithm, review_segment with ConfirmedRegion creation, get_session_summary)
- [ ] T050 [US3] Create sampling router in apps/api/echoroo/api/v1/sampling.py (POST sessions, GET session, PATCH segment)
- [ ] T051 [US3] Register sampling router in apps/api/echoroo/api/v1/__init__.py
- [ ] T052 [US3] Create Alembic migration for sampling_sessions and sampling_segments tables in apps/api/alembic/versions/
- [ ] T053 [P] [US3] Create API client in apps/web/src/lib/api/sampling.ts (createSession, getSession, reviewSegment)
- [ ] T054 [US3] Create SamplingSetup.svelte component in apps/web/src/lib/components/sampling/SamplingSetup.svelte (segment count input, segment duration input, start button)
- [ ] T055 [US3] Create SegmentReviewer.svelte component in apps/web/src/lib/components/sampling/SegmentReviewer.svelte (spectrogram + audio player for segment, annotation add form, confirm/skip buttons)
- [ ] T056 [P] [US3] Create SamplingSummary.svelte component in apps/web/src/lib/components/sampling/SamplingSummary.svelte (total reviewed, annotations added, confirmed regions created)
- [ ] T057 [US3] Create sampling review page in apps/web/src/routes/(app)/projects/[id]/datasets/[datasetId]/sampling-review/+page.svelte (SamplingSetup → SegmentReviewer flow → SamplingSummary)

**Checkpoint**: Users can efficiently create negative data through random sampling

---

## Phase 5: User Story 4 - データエクスポート (Priority: P2)

**Goal**: Detection results CSV and ML training dataset export

**Independent Test**: Export detection CSV, verify format; export ML training ZIP, verify structure

### Tests for User Story 4

- [ ] T058 [P] [US4] Contract test for POST /api/v1/projects/{id}/datasets/{datasetId}/exports (create export job) in apps/api/tests/contract/test_detection_export.py
- [ ] T059 [P] [US4] Contract test for GET /api/v1/projects/{id}/datasets/{datasetId}/exports/{exportId} (status check) in apps/api/tests/contract/test_detection_export.py
- [ ] T060 [P] [US4] Contract test for GET /api/v1/projects/{id}/datasets/{datasetId}/exports/{exportId}/download in apps/api/tests/contract/test_detection_export.py
- [ ] T061 [P] [US4] Integration test for detection CSV export in apps/api/tests/integration/test_export_flow.py (verify column format matches VISION.md spec)
- [ ] T062 [P] [US4] Integration test for ML training export in apps/api/tests/integration/test_export_flow.py (verify ZIP structure: audio/, annotations.csv, metadata.json, README.txt)

### Implementation for User Story 4

- [ ] T063 [US4] Create DetectionExportService in apps/api/echoroo/services/detection_export.py with methods:
  - generate_detection_csv(): VISION.md format (recording_filename, start_time, end_time, species, confidence, source, model_name, model_version, verified, verified_by, search_query_*)
  - generate_ml_training_zip(): audio clips + annotations.csv + metadata.json + README.txt
  - process_export_job(): Background job handler
- [ ] T064 [US4] Create detection export router in apps/api/echoroo/api/v1/detection_export.py (POST create job, GET status, GET download)
- [ ] T065 [US4] Register detection export router in apps/api/echoroo/api/v1/__init__.py
- [ ] T066 [P] [US4] Create API client in apps/web/src/lib/api/detection-export.ts (createExport, getExportStatus, downloadExport)
- [ ] T067 [US4] Create DetectionExportDialog.svelte in apps/web/src/lib/components/export/DetectionExportDialog.svelte (format selector: detection CSV / ML training, filter options, progress display)
- [ ] T068 [US4] Create MLExportDialog.svelte in apps/web/src/lib/components/export/MLExportDialog.svelte (options: include negatives, species filter, progress display)
- [ ] T069 [US4] Add export buttons and dialogs to dataset detail page apps/web/src/routes/(app)/projects/[id]/datasets/[datasetId]/+page.svelte

**Checkpoint**: Users can export detection results and ML training datasets

---

## Phase 6: User Story 5 - 検出結果の共有 (Priority: P3)

**Goal**: Share detection results (not raw audio) between projects

**Independent Test**: Create share, verify recipient sees confirmed detections in Explore

### Tests for User Story 5

- [ ] T070 [P] [US5] Contract test for POST /api/v1/projects/{id}/datasets/{datasetId}/shares in apps/api/tests/contract/test_sharing.py
- [ ] T071 [P] [US5] Contract test for GET /api/v1/projects/{id}/datasets/{datasetId}/shares in apps/api/tests/contract/test_sharing.py
- [ ] T072 [P] [US5] Contract test for DELETE /api/v1/projects/{id}/datasets/{datasetId}/shares/{shareId} in apps/api/tests/contract/test_sharing.py
- [ ] T073 [P] [US5] Integration test for sharing flow in apps/api/tests/integration/test_sharing_flow.py (verify shared data appears in Explore, confirmed_only filter works)

### Implementation for User Story 5

- [ ] T074 [P] [US5] Create DetectionShare model in apps/api/echoroo/models/sharing.py (source_dataset_id, target_project_id, shared_by_id, confirmed_only boolean default true, created_at)
- [ ] T075 [P] [US5] Add DetectionShare to apps/api/echoroo/models/__init__.py
- [ ] T076 [P] [US5] Create sharing schemas in apps/api/echoroo/schemas/sharing.py (ShareCreate, ShareResponse, ShareList)
- [ ] T077 [P] [US5] Create SharingRepository in apps/api/echoroo/repositories/sharing.py
- [ ] T078 [US5] Create SharingService in apps/api/echoroo/services/sharing.py (create share, list shares, revoke share, integrate with ExploreService)
- [ ] T079 [US5] Create sharing router in apps/api/echoroo/api/v1/sharing.py (POST, GET, DELETE)
- [ ] T080 [US5] Register sharing router in apps/api/echoroo/api/v1/__init__.py
- [ ] T081 [US5] Create Alembic migration for detection_shares table in apps/api/alembic/versions/
- [ ] T082 [US5] Update ExploreService to include shared datasets in search results apps/api/echoroo/services/explore.py
- [ ] T083 [P] [US5] Create API client in apps/web/src/lib/api/sharing.ts (createShare, listShares, deleteShare)
- [ ] T084 [US5] Create sharing management UI in dataset detail page (share button, recipient selector, active shares list)

**Checkpoint**: Detection results can be shared between projects

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T085 [P] Run mypy type check on new backend code (apps/api)
- [ ] T086 [P] Run npm check on new frontend code (apps/web)
- [ ] T087 [P] Run ruff linter on backend (apps/api)
- [ ] T088 [P] Run eslint on frontend (apps/web)
- [ ] T089 Create e2e test for Explore flow in apps/web/tests/e2e/explore.spec.ts
- [ ] T090 Create e2e test for sampling review flow in apps/web/tests/e2e/sampling.spec.ts
- [ ] T091 Create e2e test for export flow in apps/web/tests/e2e/export.spec.ts
- [ ] T092 Add navigation link "Explore" to main app layout/sidebar
- [ ] T093 Add "Sampling Review" button to dataset detail page (only when dataset has completed processing)
- [ ] T094 Performance validation: Spiral Plot with 10K+ data points

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Shared Models)**: No dependencies within this feature - can start immediately (but depends on 003-annotation models being defined)
- **Phase 2 (US2 - Spiral Plot)**: Depends on Phase 1 (ConfirmedRegion for review progress)
- **Phase 3 (US1 - Explore)**: Depends on Phase 1 (needs annotation data to search); can run in parallel with Phase 2
- **Phase 4 (US3 - Sampling)**: Depends on Phase 1 (ConfirmedRegion model); can run in parallel with Phases 2 and 3
- **Phase 5 (US4 - Export)**: Depends on Phase 1 (ConfirmedRegion for negative data, ExportJob model)
- **Phase 6 (US5 - Sharing)**: Depends on Phase 3 (Explore service to show shared data)
- **Phase 7 (Polish)**: Depends on all desired user stories being complete

### User Story Dependencies

```
Phase 1: Shared Models (ConfirmedRegion, ExportJob, types)
    │
    ├────────────────────────────┬────────────────────────────┐
    │                            │                            │
    ▼                            ▼                            ▼
[US2] Spiral Plot            [US1] Explore               [US3] Sampling
  (P2)                         (P2)                         Review (P2)
    │                            │                            │
    │                            │                            │
    ▼                            ▼                            ▼
[US4] Export ◄───────────── Depends on                   (independent)
  (P2)                     ConfirmedRegion
                              from US3
                                │
                                ▼
                           [US5] Sharing
                              (P3)
```

### Within Each User Story

1. Tests MUST be written and FAIL before implementation (TDD)
2. Models before repositories
3. Repositories before services
4. Services before routers
5. Backend before frontend
6. Story complete before moving to next priority

### Parallel Opportunities

**Phase 1 (all models parallel)**:
- T001, T003, T004, T007, T009, T010, T012, T013

**Phase 2 + 3 + 4 can run in parallel** (different API endpoints and UI components):
- Developer A: User Story 2 (Spiral Plot + dataset detail)
- Developer B: User Story 1 (Explore) + User Story 3 (Sampling)
- Developer C: User Story 4 (Export)

**Per User Story**:
- All tests marked [P] can run in parallel
- Models/schemas marked [P] can run in parallel
- Frontend components marked [P] can run in parallel

---

## Implementation Strategy

### Incremental Delivery

1. Phase 1: Shared Models → Foundation ready
2. Phase 2: Spiral Plot + Dataset Detail → Dataset insights visible
3. Phase 3: Explore → Cross-project discovery
4. Phase 4: Sampling Review → Negative data creation workflow
5. Phase 5: Export → Data extraction for reports and ML
6. Phase 6: Sharing (P3) → Cross-project collaboration
7. Phase 7: Polish → Quality assurance

### Priority-Based Stopping Points

**Minimum Viable (P2 only)**:
1. Complete Phases 1-5 (US1-US4)
2. **STOP and VALIDATE**: Test all P2 stories independently
3. Deploy if ready

**Full Feature**:
4. Add Phase 6 (US5 - Sharing, P3)
5. Complete Phase 7 (Polish)
