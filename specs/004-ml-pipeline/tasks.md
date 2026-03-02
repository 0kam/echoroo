# Tasks: ML Pipeline

**Input**: Design documents from `/specs/004-ml-pipeline/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: TDD approach per constitution - tests are REQUIRED for all API endpoints and services.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

- **Backend**: `apps/api/echoroo/` (FastAPI)
- **Frontend**: `apps/web/src/` (SvelteKit)
- **Backend Tests**: `apps/api/tests/`
- **Frontend Tests**: `apps/web/tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies, enums, data models, schemas, migrations, Celery configuration

### Dependencies & Configuration

- [ ] T001 Add ML dependencies to `apps/api/pyproject.toml`: birdnetlib (BirdNET wrapper), tensorflow (Perch/BirdNET), pgvector (SQLAlchemy pgvector support), celery[redis] (task queue)
- [ ] T002 [P] Create Celery app configuration in `apps/api/echoroo/workers/celery_app.py` (broker=Redis, result_backend=Redis, task serializer=json, task_track_started=True, worker_concurrency configurable)
- [ ] T003 [P] Add Celery worker service to `compose.dev.yaml` (separate container running celery worker, mounts audio directory, depends on db+redis)
- [ ] T004 [P] Add ML model cache volume to `compose.dev.yaml` (persistent volume for downloaded BirdNET/Perch models)

### Enums

- [ ] T005 [P] Add new enums to `apps/api/echoroo/models/enums.py`: DetectionRunStatus (pending, running, completed, failed, cancelled), DetectionRunType (detection, embedding), AnnotationSourceV2 (birdnet, perch_search, human), AnnotationStatusV2 (unreviewed, confirmed, rejected)

### Data Models

- [ ] T006 [P] Create DetectionRun model in `apps/api/echoroo/models/detection_run.py` (id UUID PK, dataset_id FK, model_name, model_version, run_type DetectionRunType, parameters JSONB, status DetectionRunStatus, detection_count int, error_message text, started_at timestamp, completed_at timestamp, created_at, updated_at)
- [ ] T007 [P] Create new Annotation model (VISION.md style) in `apps/api/echoroo/models/annotation_v2.py` (id UUID PK, recording_id FK recordings, tag_id FK tags nullable, detection_run_id FK detection_runs nullable, source AnnotationSourceV2, status AnnotationStatusV2, start_time float, end_time float, confidence float nullable, freq_low float nullable, freq_high float nullable, species_name string nullable, created_by_id FK users nullable, created_at, updated_at)
- [ ] T008 [P] Create Embedding model in `apps/api/echoroo/models/embedding.py` (id UUID PK, recording_id FK recordings, detection_run_id FK detection_runs, start_time float, end_time float, vector Vector(1024) using pgvector, created_at). Add HNSW index on vector column for cosine similarity search
- [ ] T009 Register new models in `apps/api/echoroo/models/__init__.py` (DetectionRun, AnnotationV2, Embedding, new enums)
- [ ] T010 Generate Alembic migration for detection_runs, annotations_v2, embeddings tables in `apps/api/alembic/versions/`

### Pydantic Schemas

- [ ] T011 [P] Create DetectionRun schemas in `apps/api/echoroo/schemas/detection_run.py` (DetectionRunResponse, DetectionRunListResponse, DetectionRunDetailResponse, DetectionRunRetriggerRequest)
- [ ] T012 [P] Create AnnotationV2 schemas in `apps/api/echoroo/schemas/annotation_v2.py` (AnnotationV2Response, AnnotationV2ListResponse, AnnotationV2CreateRequest)
- [ ] T013 [P] Create Embedding schemas in `apps/api/echoroo/schemas/embedding.py` (EmbeddingResponse)
- [ ] T014 [P] Create similarity search schemas in `apps/api/echoroo/schemas/similarity_search.py` (SimilaritySearchRequest, SimilaritySearchResponse, SimilaritySearchResult)
- [ ] T015 [P] Create ML-related TypeScript types in `apps/web/src/lib/types/ml.ts` (DetectionRun, DetectionRunStatus, AnnotationV2, SimilaritySearchResult)

### ML Module

- [ ] T016 [P] Create ML module init and audio processor in `apps/api/echoroo/ml/__init__.py` and `apps/api/echoroo/ml/audio_processor.py` (load_audio with soundfile, resample with scipy, chunk_audio for fixed-length segments with configurable window/hop)
- [ ] T017 [P] Create model manager in `apps/api/echoroo/ml/model_manager.py` (download_model, get_model_path, check_model_exists for BirdNET and Perch models, configurable cache directory)

**Checkpoint**: All models, schemas, migrations, Celery config, and ML module foundation are ready

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core repositories and services used across multiple user stories

**CRITICAL**: No user story work can begin until this phase is complete

### Repositories

- [ ] T018 [P] Implement DetectionRunRepository in `apps/api/echoroo/repositories/detection_run.py` (get_by_id, list_by_dataset, list_all with filters, create, update_status, update_count)
- [ ] T019 [P] Implement AnnotationV2Repository in `apps/api/echoroo/repositories/annotation_v2.py` (get_by_id, list_by_recording, list_by_detection_run, create_batch, delete_by_detection_run, count_by_detection_run)
- [ ] T020 [P] Implement EmbeddingRepository in `apps/api/echoroo/repositories/embedding.py` (create_batch, delete_by_detection_run, search_similar with pgvector cosine distance, get_by_recording)

### Core Services

- [ ] T021 Implement DetectionRunService in `apps/api/echoroo/services/detection_run.py` (create_run, update_status, complete_run, fail_run, cancel_run, list_runs, get_run, retrigger_run)

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - BirdNET自動検出 (Priority: P1) -- MVP

**Goal**: After dataset import completes, BirdNET automatically runs in the background and saves detection results as AnnotationV2 records (source=birdnet).

**Independent Test**: Import a dataset, verify BirdNET task is triggered, AnnotationV2 records with source=birdnet are created for detected species.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T022 [P] [US1] Unit test for BirdNET wrapper (mock model, test audio chunking, test result parsing) in `apps/api/tests/unit/test_birdnet_wrapper.py`
- [ ] T023 [P] [US1] Unit test for audio processor (test load, resample, chunk functions) in `apps/api/tests/unit/test_audio_processor.py`
- [ ] T024 [P] [US1] Integration test for BirdNET pipeline (test dataset import triggers BirdNET task, DetectionRun created, AnnotationV2 records created) in `apps/api/tests/integration/test_ml_pipeline.py`

### Backend Implementation for User Story 1

- [ ] T025 [US1] Implement BirdNET wrapper in `apps/api/echoroo/ml/birdnet_wrapper.py` (load_model, predict: takes audio array + samplerate, returns list of (species, confidence, start_time, end_time), configurable min_confidence threshold)
- [ ] T026 [US1] Implement BirdNET Celery task in `apps/api/echoroo/workers/birdnet_task.py` (@shared_task with bind=True, max_retries=3: loads recordings for dataset, creates DetectionRun, iterates recordings, chunks audio to 3s windows, runs BirdNET inference, creates AnnotationV2 records in batches, updates DetectionRun status/count on completion/failure)
- [ ] T027 [US1] Implement ML pipeline orchestrator service in `apps/api/echoroo/services/ml_pipeline.py` (trigger_pipeline: called after dataset import completes, dispatches birdnet_task.delay() and perch_task.delay(), returns DetectionRun IDs)
- [ ] T028 [US1] Integrate ML pipeline trigger into dataset import completion in `apps/api/echoroo/services/dataset.py` (after status changes to COMPLETED, call ml_pipeline.trigger_pipeline)
- [ ] T029 [US1] Add BirdNET confidence threshold to system settings (key: ml_birdnet_min_confidence, default: 0.25) — add migration seed data in `apps/api/alembic/versions/`

**Checkpoint**: User Story 1 is fully functional - BirdNET auto-detects species on dataset import

---

## Phase 4: User Story 2 - Perch埋め込み生成 (Priority: P1)

**Goal**: After dataset import completes, Perch embeddings are automatically generated and stored in pgvector.

**Independent Test**: Import a dataset, verify Perch task is triggered, embeddings are stored in pgvector embeddings table with correct dimensions.

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T030 [P] [US2] Unit test for Perch wrapper (mock model, test audio chunking to 5s, test embedding output shape [1024]) in `apps/api/tests/unit/test_perch_wrapper.py`
- [ ] T031 [P] [US2] Unit test for embedding repository (test pgvector insert, test cosine similarity query) in `apps/api/tests/unit/test_embedding_repo.py`

### Backend Implementation for User Story 2

- [ ] T032 [US2] Implement Perch wrapper in `apps/api/echoroo/ml/perch_wrapper.py` (load_model from TFHub, embed: takes audio array + samplerate, returns numpy array of shape (n_chunks, 1024), configurable chunk_duration=5.0s and hop_duration=2.5s)
- [ ] T033 [US2] Implement Perch embedding Celery task in `apps/api/echoroo/workers/perch_task.py` (@shared_task with bind=True, max_retries=3: loads recordings for dataset, creates DetectionRun(type=embedding), iterates recordings, chunks audio to 5s windows, generates embeddings, batch-inserts into embeddings table via EmbeddingRepository, updates DetectionRun status/count on completion/failure)
- [ ] T034 [US2] Update ML pipeline orchestrator to also trigger Perch task in `apps/api/echoroo/services/ml_pipeline.py` (trigger_pipeline now dispatches both birdnet_task.delay() and perch_task.delay() concurrently)
- [ ] T035 [US2] Create HNSW index migration for embeddings.vector column (cosine distance, m=16, ef_construction=64) in `apps/api/alembic/versions/`

**Checkpoint**: User Story 2 is fully functional - Perch embeddings auto-generated on dataset import

---

## Phase 5: User Story 3 - DetectionRun管理 (Priority: P1)

**Goal**: Administrators can view ML execution status, filter by dataset/status, and re-trigger failed runs.

**Independent Test**: Access admin panel, view DetectionRun list with filters, re-trigger a failed run.

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T036 [P] [US3] Contract tests for DetectionRun admin API (list with filters, get detail, retrigger, cancel) in `apps/api/tests/contract/test_detection_runs.py`

### Backend Implementation for User Story 3

- [ ] T037 [US3] Implement DetectionRun admin API endpoints in `apps/api/echoroo/api/v1/detection_runs.py` (GET /api/v1/admin/detection-runs with pagination + dataset_id + status filters, GET /api/v1/admin/detection-runs/{id} detail, POST /api/v1/admin/detection-runs/{id}/retrigger, POST /api/v1/admin/detection-runs/{id}/cancel). All endpoints require superuser auth.
- [ ] T038 [US3] Register detection_runs router in `apps/api/echoroo/api/v1/__init__.py`

### Frontend Implementation for User Story 3

- [ ] T039 [P] [US3] Create DetectionRun API client in `apps/web/src/lib/api/detection-runs.ts` (list, getDetail, retrigger, cancel)
- [ ] T040 [US3] Create DetectionRun management page in `apps/web/src/routes/(app)/admin/detection-runs/+page.svelte` (table with status badges, dataset name, model info, counts, error messages, filter dropdowns for dataset and status, retrigger/cancel action buttons)

**Checkpoint**: User Story 3 is fully functional - admins can monitor and manage ML runs

---

## Phase 6: User Story 4 - 類似音検索 (Priority: P2)

**Goal**: Users can select a reference sound and search across dataset using Perch embeddings. Results are presented as detection candidates for review.

**Independent Test**: Select a time range from a recording, run similarity search, verify results with similarity scores are returned.

### Tests for User Story 4

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T041 [P] [US4] Contract tests for similarity search API (search by recording segment, search by uploaded audio, confirm/reject results) in `apps/api/tests/contract/test_similarity_search.py`
- [ ] T042 [P] [US4] Unit test for similarity search service (mock embeddings, test vector query, test result ranking) in `apps/api/tests/unit/test_similarity_search.py`

### Backend Implementation for User Story 4

- [ ] T043 [US4] Implement SimilaritySearchService in `apps/api/echoroo/services/similarity_search.py` (search_by_segment: compute embedding for reference segment, query pgvector for top-k similar, return results with scores; search_by_upload: process uploaded audio, compute embedding, search; confirm_result: create AnnotationV2 with source=perch_search; reject_result: mark as rejected)
- [ ] T044 [US4] Implement similarity search API endpoints in `apps/api/echoroo/api/v1/similarity_search.py` (POST /api/v1/projects/{id}/similarity-search with recording_id + start_time + end_time OR uploaded file, GET results, POST confirm, POST reject)
- [ ] T045 [US4] Register similarity_search router in `apps/api/echoroo/api/v1/__init__.py`

### Frontend Implementation for User Story 4

- [ ] T046 [P] [US4] Create similarity search API client in `apps/web/src/lib/api/similarity-search.ts` (search, confirm, reject)
- [ ] T047 [US4] Create similarity search page in `apps/web/src/routes/(app)/projects/[id]/search/+page.svelte` (reference sound selector with spectrogram, search button, results list with similarity scores, spectrogram preview, play button, confirm/reject actions per result)

**Checkpoint**: User Story 4 is fully functional - users can search for similar sounds

---

## Phase 7: Notification & Integration

**Purpose**: User notifications for ML processing completion and cross-cutting polish

- [ ] T048 Add ML processing status to dataset detail response in `apps/api/echoroo/schemas/dataset.py` (add ml_status field showing latest DetectionRun status for the dataset)
- [ ] T049 Add ML status query to dataset service in `apps/api/echoroo/services/dataset.py` (query DetectionRun for dataset, return aggregated status: processing/completed/failed/none)
- [ ] T050 [P] Display ML processing status on dataset detail page in `apps/web/src/routes/(app)/projects/[id]/datasets/[datasetId]/+page.svelte` (status badge: "Processing...", "ML Complete", "ML Failed", with progress indicator)
- [ ] T051 [P] Add polling for ML status on dataset page (poll GET /api/v1/datasets/{id} every 10 seconds while status is "processing", stop when completed/failed)

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Integration testing, type checking, and cleanup

- [ ] T052 [P] Integration test for full ML pipeline (import dataset → BirdNET + Perch triggered → DetectionRuns created → AnnotationV2 records → Embeddings stored) in `apps/api/tests/integration/test_ml_pipeline.py` (extend T024)
- [ ] T053 [P] Add ML system settings to admin settings page (ml_birdnet_min_confidence, ml_detection_model, ml_embedding_model) in `apps/web/src/routes/(app)/admin/settings/+page.svelte`
- [ ] T054 Run backend type check: `cd apps/api && uv run mypy .`
- [ ] T055 Run frontend type check: `cd apps/web && npm run check`
- [ ] T056 Run all backend tests: `cd apps/api && uv run pytest tests/ -v`
- [ ] T057 Run ruff linter: `cd apps/api && uv run ruff check .`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Phase 2 completion
- **User Story 2 (Phase 4)**: Depends on Phase 2 completion. Can run in PARALLEL with US1
- **User Story 3 (Phase 5)**: Depends on Phase 2 completion. Can start after US1 or US2 creates DetectionRuns
- **User Story 4 (Phase 6)**: Depends on US2 completion (requires embeddings to exist)
- **Notification (Phase 7)**: Depends on US1 and US2 completion
- **Polish (Phase 8)**: Depends on all desired user stories being complete

### User Story Dependencies

```
Setup (Phase 1)
    │
    ▼
Foundational (Phase 2)
    │
    ├──────────────────────────┐
    │                          │
    ▼                          ▼
[US1] BirdNET Detection    [US2] Perch Embedding
    (P1)                       (P1)
    │                          │
    ├──────────────────────────┤
    │                          │
    ▼                          ▼
[US3] DetectionRun Mgmt    [US4] Similarity Search
    (P1)                       (P2)
    │                          │
    └──────────┬───────────────┘
               │
               ▼
        Notification (Phase 7)
               │
               ▼
        Polish (Phase 8)
```

### Within Each User Story

1. Tests MUST be written and FAIL before implementation (TDD)
2. ML wrappers before Celery tasks
3. Services before API endpoints
4. Backend before frontend
5. Story complete before moving to next priority

### Parallel Opportunities

**Phase 1 (all parallel)**:
- T002, T003, T004 (Celery/Docker config)
- T005 (enums)
- T006, T007, T008 (models)
- T011, T012, T013, T014, T015 (schemas)
- T016, T017 (ML module)

**Phase 2 (parallel groups)**:
- T018, T019, T020 (repositories)

**US1 + US2 (parallel)**:
- BirdNET tasks (T022-T029) and Perch tasks (T030-T035) can be developed in parallel since they use different models and write to different tables

**Per User Story**:
- All tests marked [P] can run in parallel
- Frontend components marked [P] can run in parallel

---

## Implementation Strategy

### MVP First (P1 Stories Only)

1. Complete Phase 1: Setup (models, schemas, Celery, ML module)
2. Complete Phase 2: Foundational (repositories, DetectionRunService)
3. Complete Phase 3 + Phase 4 in parallel: US1 (BirdNET) + US2 (Perch)
4. Complete Phase 5: US3 (DetectionRun Admin)
5. Complete Phase 7: Notifications
6. **STOP and VALIDATE**: Test full pipeline end-to-end
7. Deploy/demo if ready - **This is the MVP!**

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 → BirdNET detection works → Deploy/Demo (core ML value)
3. US2 → Perch embeddings generated → Deploy/Demo (search foundation)
4. US3 → Admin can monitor ML → Deploy/Demo (operational readiness)
5. Notifications → Users see ML status → Deploy/Demo (UX complete)
6. US4 → Similarity search → Deploy/Demo (P2 feature, differentiation)
