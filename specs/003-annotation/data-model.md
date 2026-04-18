# Data Model: Annotation Feature (Revised)

**Feature Branch**: `003-annotation`
**Date**: 2026-04-17 (revision of 2026-02-19)

## Revision Summary vs. Previous Spec

| Previous (Whombat-derived) | New (Cross-model evaluation) |
|---|---|
| `AnnotationProject` + `AnnotationTask` + `ClipAnnotation` | `AnnotationSet` + `AnnotationSegment` (flatter) |
| `SoundEventAnnotation` with `geometry` (BoundingBox w/ frequency) | `TimeRangeAnnotation` (time-only, `[start, end]`) |
| Hierarchical `Tag` table with parent/children, GBIF fields | Direct FK to existing `Species` table |
| Multi-tag M2M per sound-event | Single `species_id` per TimeRangeAnnotation |
| `ClipAnnotation.review_status` (unreviewed/approved/rejected) + reviewer fields | Dropped; single `status` on segment only |
| `Note.is_review` flag + nullable dual FK | Two association tables (`AnnotationSegmentNote`, `TimeRangeAnnotationNote`); `is_issue` flag replaces `is_review` |
| `source` (human/model) on sound events | Dropped; TimeRangeAnnotation is ground-truth only; detector output lives in `EvaluationRun` |
| No explicit "empty" marker | `AnnotationSegment.is_empty` (required for recall denominator) |

The existing detection-review models in `apps/api/echoroo/models/annotation.py` (`Annotation`, `AnnotationVote`) are preserved. The new entity is named `TimeRangeAnnotation` to avoid collision.

---

## Entity Relationship Diagram

```
 Project (existing)          Dataset (existing)           Species (existing)
      |1                             |1                         |1
      |N                             |N                         |N
      v                              v                          v
 +---------------------+      +---------------------+     +-----------------------+
 |  AnnotationSet      |----->| Recording (filtered)|     | AnnotationSetSpecies  | (M2M palette)
 |---------------------|      +---------------------+     +-----------------------+
 | PK id: UUID         |              ^                             ^
 | FK project_id       |              |                             |
 | FK dataset_id       |              |                             |
 | FK created_by_id    |              |                             |
 |    name             |              |                             |
 |    filter_date_range (jsonb null)  |                             |
 |    filter_tod_range  (jsonb null)  |                             |
 |    segment_length_sec (>= 10)      |                             |
 |    num_segments                    |                             |
 |    status (sampling|ready|in_progress|completed)                 |
 |    timestamps                                                    |
 +---------------------+                                            |
      |1                                                            |
      |N                                                            |
      v                                                             |
 +---------------------------+                                      |
 |  AnnotationSegment        |                                      |
 |---------------------------|                                      |
 | PK id: UUID               |                                      |
 | FK annotation_set_id      |                                      |
 | FK recording_id           |                                      |
 |    start_time_sec         |  (within recording)                  |
 |    end_time_sec           |                                      |
 |    is_empty (bool)        |                                      |
 |    status (unannotated|annotated|skipped)                        |
 | FK annotated_by_id (null) |                                      |
 |    annotated_at (null)    |                                      |
 |    timestamps             |                                      |
 +---------------------------+                                      |
      |1                      |N (AnnotationSegmentNote)            |
      |N                      v                                     |
      v                 +---------------------------+               |
 +--------------------------+  | Note (existing)    |               |
 | TimeRangeAnnotation      |  +--------------------+               |
 |--------------------------|           ^                           |
 | PK id: UUID              |           | N (TimeRangeAnnotationNote)
 | FK segment_id            |           |                           |
 |    start_time_sec        |  (within segment)                     |
 |    end_time_sec          |                                       |
 | FK species_id            |---------------------------------------+
 |    confidence (null)     |
 | FK created_by_id         |
 |    timestamps            |
 +--------------------------+

 +-------------------+       +-----------------------+
 |  EvaluationRun    |------>| EvaluationResult      |
 |-------------------|       |-----------------------|
 | PK id: UUID       |       | PK id: UUID           |
 | FK set_id         |       | FK run_id             |
 |    model_kind     |       | FK species_id (null)  |  (null = overall)
 |    model_ref      |       |    tp_precision       |
 |    started_at     |       |    tp_recall          |
 |    finished_at    |       |    fp                 |
 |    status         |       |    fn                 |
 |    created_by_id  |       |    precision          |
 +-------------------+       |    recall             |
                             |    f1                 |
                             +-----------------------+
```

---

## Entity Definitions

### AnnotationSet

Top-level container. One set = one ground-truth collection used to evaluate one or more models.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | |
| `project_id` | UUID | FK projects.id, NOT NULL, ON DELETE CASCADE | Owning project |
| `dataset_id` | UUID | FK datasets.id, NOT NULL, ON DELETE CASCADE | Source dataset |
| `created_by_id` | UUID | FK users.id, NOT NULL | Creator |
| `name` | String(200) | NOT NULL | Display name |
| `filter_date_range` | JSONB | nullable | `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}` (both inclusive) |
| `filter_time_of_day_range` | JSONB | nullable | `{"start": "HH:MM", "end": "HH:MM"}` (local tod; range may wrap midnight) |
| `segment_length_sec` | Integer | NOT NULL, CHECK >= 10 | Length of each sampled segment |
| `num_segments` | Integer | NOT NULL, CHECK >= 1 | Requested count |
| `status` | Enum | NOT NULL, default `sampling` | `sampling | ready | in_progress | completed` |
| `sampling_warning` | Text | nullable | E.g. "only 42 of 100 segments available after filters" |
| `created_at` / `updated_at` | DateTime | NOT NULL | |

**Constraints**: `UNIQUE(project_id, name)`.
**Indexes**: `ix_annotation_sets_project_id`, `ix_annotation_sets_dataset_id`, `ix_annotation_sets_status`.
**Relationships**: `project`, `dataset`, `created_by`, `segments` (1:N), `species_palette` (M2N via `AnnotationSetSpecies`).

**Status transitions**:
```
sampling  -> ready            (background job finished)
ready     -> in_progress      (first segment annotated)
in_progress -> completed      (all segments annotated or skipped)
completed -> in_progress      (edit reopens a segment)
```

---

### AnnotationSetSpecies (association)

| Field | Type | Constraints |
|-------|------|-------------|
| `annotation_set_id` | UUID | FK, PK, ON DELETE CASCADE |
| `species_id` | UUID | FK species.id, PK, ON DELETE CASCADE |
| `position` | Integer | default 0 (for palette ordering / keyboard slot hints) |

---

### AnnotationSegment

Materialized, independently annotatable segment of a recording.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | |
| `annotation_set_id` | UUID | FK annotation_sets.id, NOT NULL, ON DELETE CASCADE | |
| `recording_id` | UUID | FK recordings.id, NOT NULL, ON DELETE CASCADE | |
| `start_time_sec` | Float | NOT NULL, CHECK >= 0 | Offset inside the recording |
| `end_time_sec` | Float | NOT NULL, CHECK > start_time_sec | |
| `is_empty` | Boolean | NOT NULL, default false | Explicit "no target calls" |
| `status` | Enum | NOT NULL, default `unannotated` | `unannotated | annotated | skipped` |
| `annotated_by_id` | UUID | FK users.id, nullable, ON DELETE SET NULL | |
| `annotated_at` | DateTime | nullable | |
| `created_at` / `updated_at` | DateTime | NOT NULL | |

**Constraints**: `CHECK (end_time_sec - start_time_sec) = annotation_set.segment_length_sec` enforced at service layer (not DB; avoids cross-table check). `CHECK end_time_sec <= recording.duration_sec` enforced at sampling time.
**Indexes**: `ix_annotation_segments_set_id`, `ix_annotation_segments_recording_id`, `ix_annotation_segments_status`, compound `ix_annotation_segments_set_status`.
**Relationships**: `annotation_set`, `recording`, `annotated_by`, `annotations` (1:N), `notes` (M2N via `AnnotationSegmentNote`).

**Invariants**:
- If `status = annotated` and no TimeRangeAnnotations exist then `is_empty = true`.
- Creating a TimeRangeAnnotation sets `is_empty = false`.

---

### TimeRangeAnnotation

One call-event inside a segment.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | |
| `segment_id` | UUID | FK annotation_segments.id, NOT NULL, ON DELETE CASCADE | |
| `start_time_sec` | Float | NOT NULL, CHECK >= 0 | Offset inside the segment |
| `end_time_sec` | Float | NOT NULL, CHECK > start_time_sec | |
| `species_id` | UUID | FK species.id, NOT NULL, ON DELETE RESTRICT | Single label |
| `confidence` | Float | nullable, CHECK 0 <= x <= 1 | Annotator-declared confidence |
| `created_by_id` | UUID | FK users.id, NOT NULL | |
| `created_at` / `updated_at` | DateTime | NOT NULL | |

**Constraints**: `end_time_sec <= segment.end_time_sec - segment.start_time_sec` enforced at service layer.
**Indexes**: `ix_time_range_annotations_segment_id`, `ix_time_range_annotations_species_id`.
**Relationships**: `segment`, `species`, `created_by`, `notes` (M2N via `TimeRangeAnnotationNote`).

Overlapping annotations of the same or different species on the same segment are allowed.

---

### AnnotationSegmentNote / TimeRangeAnnotationNote (association tables)

Reuse the existing `Note` table (`content`, `created_by_id`, `created_at`, `updated_at`). Add `is_issue: bool` to `Note` if not already present (migration concern; see `research.md`).

`AnnotationSegmentNote`
| Field | Type | Constraints |
|-------|------|-------------|
| `segment_id` | UUID | FK, PK, ON DELETE CASCADE |
| `note_id` | UUID | FK notes.id, PK, ON DELETE CASCADE |

`TimeRangeAnnotationNote`
| Field | Type | Constraints |
|-------|------|-------------|
| `annotation_id` | UUID | FK time_range_annotations.id, PK, ON DELETE CASCADE |
| `note_id` | UUID | FK notes.id, PK, ON DELETE CASCADE |

---

### EvaluationRun

Records one execution of the evaluation for a `(set, model)` pair.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK | |
| `annotation_set_id` | UUID | FK, NOT NULL, ON DELETE CASCADE | |
| `model_kind` | Enum | NOT NULL | `birdnet | perch | custom` |
| `model_ref` | String(200) | nullable | Custom model UUID or builtin version label |
| `status` | Enum | NOT NULL | `pending | running | completed | failed` |
| `started_at` / `finished_at` | DateTime | nullable | |
| `created_by_id` | UUID | FK users.id, NOT NULL | |
| `error` | Text | nullable | |

**Indexes**: `ix_evaluation_runs_set_model` on `(annotation_set_id, model_kind, model_ref)`.

---

### EvaluationResult

One row per `(run, species_id-or-null)`; `species_id = NULL` means overall aggregate.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK | |
| `run_id` | UUID | FK evaluation_runs.id, NOT NULL, ON DELETE CASCADE | |
| `species_id` | UUID | FK species.id, nullable, ON DELETE SET NULL | NULL = overall |
| `tp_precision` | Integer | NOT NULL, default 0 | # detections with >=1 same-species GT overlap |
| `fp` | Integer | NOT NULL, default 0 | # detections with no same-species GT overlap |
| `tp_recall` | Integer | NOT NULL, default 0 | # GTs covered by >=1 same-species detection |
| `fn` | Integer | NOT NULL, default 0 | # GTs with no same-species detection overlap |
| `precision` | Float | NOT NULL | = tp_precision / (tp_precision + fp); 0 if denom 0 |
| `recall` | Float | NOT NULL | = tp_recall / (tp_recall + fn); 0 if denom 0 |
| `f1` | Float | NOT NULL | harmonic mean |
| `detections_total` | Integer | NOT NULL | Debug/audit |
| `ground_truths_total` | Integer | NOT NULL | Debug/audit |

**Indexes**: `UNIQUE(run_id, species_id)` with NULLs treated as distinct via partial index.

---

## Enum Definitions

```python
class AnnotationSetStatus(str, Enum):
    SAMPLING = "sampling"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

class SegmentStatus(str, Enum):
    UNANNOTATED = "unannotated"
    ANNOTATED = "annotated"
    SKIPPED = "skipped"

class ModelKind(str, Enum):
    BIRDNET = "birdnet"
    PERCH = "perch"
    CUSTOM = "custom"

class EvaluationRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
```

---

## Index Strategy

- `annotation_sets(project_id, status)` — list sets filtered by state.
- `annotation_segments(annotation_set_id, status)` — segment list views.
- `annotation_segments(recording_id)` — reverse lookup during evaluation detection cropping.
- `time_range_annotations(segment_id)` — editor loads.
- `time_range_annotations(species_id)` — per-species evaluation grouping.
- `evaluation_results(run_id, species_id)` — unique.

---

## Migration Plan (SQL sketches — implementation owned by backend SSA)

```sql
CREATE TYPE annotation_set_status AS ENUM ('sampling','ready','in_progress','completed');
CREATE TYPE segment_status AS ENUM ('unannotated','annotated','skipped');
CREATE TYPE model_kind AS ENUM ('birdnet','perch','custom');
CREATE TYPE evaluation_run_status AS ENUM ('pending','running','completed','failed');

CREATE TABLE annotation_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    dataset_id UUID NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    created_by_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(200) NOT NULL,
    filter_date_range JSONB,
    filter_time_of_day_range JSONB,
    segment_length_sec INTEGER NOT NULL CHECK (segment_length_sec >= 10),
    num_segments INTEGER NOT NULL CHECK (num_segments >= 1),
    status annotation_set_status NOT NULL DEFAULT 'sampling',
    sampling_warning TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, name)
);

CREATE TABLE annotation_set_species (
    annotation_set_id UUID REFERENCES annotation_sets(id) ON DELETE CASCADE,
    species_id UUID REFERENCES species(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (annotation_set_id, species_id)
);

CREATE TABLE annotation_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    annotation_set_id UUID NOT NULL REFERENCES annotation_sets(id) ON DELETE CASCADE,
    recording_id UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    start_time_sec DOUBLE PRECISION NOT NULL CHECK (start_time_sec >= 0),
    end_time_sec DOUBLE PRECISION NOT NULL,
    is_empty BOOLEAN NOT NULL DEFAULT FALSE,
    status segment_status NOT NULL DEFAULT 'unannotated',
    annotated_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
    annotated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (end_time_sec > start_time_sec)
);

CREATE TABLE time_range_annotations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id UUID NOT NULL REFERENCES annotation_segments(id) ON DELETE CASCADE,
    start_time_sec DOUBLE PRECISION NOT NULL CHECK (start_time_sec >= 0),
    end_time_sec DOUBLE PRECISION NOT NULL,
    species_id UUID NOT NULL REFERENCES species(id) ON DELETE RESTRICT,
    confidence DOUBLE PRECISION CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    created_by_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (end_time_sec > start_time_sec)
);

CREATE TABLE annotation_segment_notes (
    segment_id UUID NOT NULL REFERENCES annotation_segments(id) ON DELETE CASCADE,
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    PRIMARY KEY (segment_id, note_id)
);

CREATE TABLE time_range_annotation_notes (
    annotation_id UUID NOT NULL REFERENCES time_range_annotations(id) ON DELETE CASCADE,
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    PRIMARY KEY (annotation_id, note_id)
);

-- Ensure notes has is_issue flag (ADD COLUMN IF NOT EXISTS in a dedicated migration).

CREATE TABLE evaluation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    annotation_set_id UUID NOT NULL REFERENCES annotation_sets(id) ON DELETE CASCADE,
    model_kind model_kind NOT NULL,
    model_ref VARCHAR(200),
    status evaluation_run_status NOT NULL DEFAULT 'pending',
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_by_id UUID NOT NULL REFERENCES users(id),
    error TEXT
);

CREATE TABLE evaluation_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    species_id UUID REFERENCES species(id) ON DELETE SET NULL,
    tp_precision INTEGER NOT NULL DEFAULT 0,
    fp INTEGER NOT NULL DEFAULT 0,
    tp_recall INTEGER NOT NULL DEFAULT 0,
    fn INTEGER NOT NULL DEFAULT 0,
    precision DOUBLE PRECISION NOT NULL,
    recall DOUBLE PRECISION NOT NULL,
    f1 DOUBLE PRECISION NOT NULL,
    detections_total INTEGER NOT NULL,
    ground_truths_total INTEGER NOT NULL
);

CREATE UNIQUE INDEX ux_evaluation_results_overall
    ON evaluation_results(run_id) WHERE species_id IS NULL;
CREATE UNIQUE INDEX ux_evaluation_results_species
    ON evaluation_results(run_id, species_id) WHERE species_id IS NOT NULL;
```

---

## Data Integrity Rules

- Deleting a `Project` cascades to `AnnotationSet`, its `AnnotationSegment`s, `TimeRangeAnnotation`s, notes, palette links, evaluation runs and results.
- Deleting a `Species` is restricted if any `TimeRangeAnnotation` references it (use ON DELETE RESTRICT) to protect ground truth integrity. Palette links cascade on species delete instead (M2M, safe).
- `AnnotationSegment.is_empty` and presence of `TimeRangeAnnotation`s are kept consistent by the service layer on every create/delete/edit.
- `AnnotationSet.status` is recomputed server-side when any child segment's status changes.
