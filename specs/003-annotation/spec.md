# Feature Specification: Ground Truth Annotation for Cross-Model Evaluation

**Feature Branch**: `003-annotation`
**Created**: 2026-01-15
**Last Revised**: 2026-04-17
**Status**: Draft (Revised)
**Input**: Ground-truth annotation of audio segments to evaluate detection model accuracy (BirdNET 3s / Perch 5s / Custom) on a shared reference set.

## Context and Goals

The annotation subsystem exists for one primary purpose: **produce a ground-truth reference set that can fairly evaluate multiple detector models regardless of their internal window size**. The previous Whombat-derived design (bounding boxes on spectrograms, hierarchical tags, approval workflows, AOEF export) was heavier than Echoroo needs and coupled annotation semantics to frequency geometry and window-size-dependent matching.

The revised design replaces that with:

- **AnnotationSet**: a named collection of randomly sampled fixed-length segments (>= 10 s) drawn from recordings matching a dataset + optional date/time-of-day filters, plus a per-set species palette reused across segments.
- **AnnotationSegment**: one segment in the set. Annotators either mark it empty (no calls of interest) or add one or more time-range annotations.
- **TimeRangeAnnotation**: a `[start_sec, end_sec]` interval inside the segment with a single species from the palette. No frequency range, no bounding box.
- **Symmetric overlap evaluation**: precision and recall computed with order-independent, non-1:1 overlap matching (any positive overlap counts), making the metric invariant to the evaluated model's window length.

Existing entities (`Species`, `Recording`, `Dataset`, `Note`, `User`, `Project`) are reused. The existing detection-review `Annotation`/`AnnotationVote` models under `apps/api/echoroo/models/annotation.py` are untouched; the new entity is deliberately named `TimeRangeAnnotation` to avoid collision.

## User Scenarios and Testing *(mandatory)*

### User Story 1 - Create an Annotation Set (Priority: P1)

A researcher wants to evaluate model accuracy on a target dataset. They create an AnnotationSet by picking a dataset, narrowing with optional date / time-of-day filters, choosing a segment length (>= 10 s) and a target number of segments, then launching sampling.

**Why this priority**: Without an AnnotationSet the rest of the workflow has no input.

**Independent Test**: Create a set, wait for sampling to finish, verify `num_segments` AnnotationSegments were materialized, each pointing to a valid Recording and falling within its duration.

**Acceptance Scenarios**:

1. **Given** a project with at least one Dataset containing recordings, **When** the user submits the create form with `dataset_id`, `segment_length_sec = 30`, `num_segments = 100`, **Then** an AnnotationSet is created with status `sampling` and a background sampling job is dispatched.
2. **Given** a filter `date_range = [2025-04-01, 2025-04-30]` and `time_of_day_range = [04:00, 09:00]`, **When** sampling runs, **Then** only recordings whose `recorded_at` falls in that window are candidates for segment extraction.
3. **Given** sampling completes, **When** the user opens the set, **Then** status is `ready` and exactly `num_segments` segments exist (or fewer if the filtered pool was smaller, in which case a warning is shown).
4. **Given** the user attempts `segment_length_sec = 5`, **When** the form is submitted, **Then** validation rejects it (minimum is 10 s).

---

### User Story 2 - Annotate Time Ranges on a Segment (Priority: P1)

An annotator opens a segment, plays it, and for every recognizable call drags on the waveform/spectrogram to create a time-range annotation, then picks a species from the set's palette.

**Why this priority**: Core ground-truth production.

**Independent Test**: On a segment with a known call, create one time-range annotation spanning the call, assign a species, save, reload, confirm it persisted with `status = annotated` on the parent segment.

**Acceptance Scenarios**:

1. **Given** a `ready` segment is open, **When** the user drags a time range and selects species X from the palette, **Then** a TimeRangeAnnotation is created with `start_time_sec`/`end_time_sec` within `[0, segment_length_sec]` and `species_id = X`.
2. **Given** multiple overlapping calls exist, **When** the user creates separate time-range annotations for each, **Then** all are stored independently and can share or differ in species.
3. **Given** a time-range annotation exists, **When** the user edits its range or species, **Then** the change is persisted and reflected on reload.
4. **Given** the user has added at least one annotation, **When** the user marks the segment complete, **Then** `status` transitions `unannotated -> annotated` and `annotated_by_id`/`annotated_at` are set.

---

### User Story 3 - Mark a Segment as Empty (Priority: P1)

An annotator listens to a segment and concludes it contains no target vocalizations. They mark the segment explicitly empty.

**Why this priority**: Recall's denominator requires knowing which segments were verified empty vs. merely unreviewed. Empty-marked segments contribute zero GT; missing this information biases recall.

**Independent Test**: Open an unannotated segment, click "Mark as empty", verify `is_empty = true`, `status = annotated`, no TimeRangeAnnotations attached, and the segment appears in evaluation denominators as a segment with zero GT.

**Acceptance Scenarios**:

1. **Given** an `unannotated` segment, **When** the user clicks "Mark as empty", **Then** `is_empty = true`, `status = annotated`, `annotated_by_id` is recorded, and any existing TimeRangeAnnotations are rejected (or the action is only offered when none exist).
2. **Given** an empty-marked segment, **When** an annotator later adds a time-range annotation, **Then** `is_empty` flips back to `false` automatically.
3. **Given** evaluation runs, **When** computing recall, **Then** empty segments are included in the covered set of segments but contribute 0 to `TP_R + FN` for that segment.

---

### User Story 4 - Comment on Segments or Annotations (Priority: P2)

An annotator wants to flag uncertainty ("possibly Locustella, low SNR") or raise a correction request on a peer's annotation.

**Why this priority**: Quality signal; not blocking for basic ground-truth capture.

**Independent Test**: Attach a note to a segment and to a specific TimeRangeAnnotation; reload and verify both appear with author and timestamp.

**Acceptance Scenarios**:

1. **Given** a segment is open, **When** the user adds a note, **Then** it is linked to the segment via `AnnotationSegmentNote` and lists author + created_at.
2. **Given** a TimeRangeAnnotation is selected, **When** the user adds a note with `is_issue = true`, **Then** it is linked via `TimeRangeAnnotationNote` and surfaced as an issue badge in the UI.
3. **Given** multiple notes exist, **When** the user opens the segment, **Then** they are sorted by `created_at` ascending.

---

### User Story 5 - Cross-Model Evaluation (Priority: P2)

A researcher selects an AnnotationSet and a list of models (BirdNET, Perch, one or more Custom models) and triggers evaluation. The system runs each model against every recording window covered by the set's segments, then computes precision / recall / F1 overall and per species using the symmetric overlap metric.

**Why this priority**: The entire data model exists to serve this comparison.

**Independent Test**: On a set with known GT, run BirdNET and Perch evaluation, verify overall P/R/F1 and a per-species breakdown are returned and numerically match a reference hand-calculation for at least one species.

**Acceptance Scenarios**:

1. **Given** a `ready` or `completed` AnnotationSet, **When** the user submits `model_ids = [birdnet, perch]`, **Then** the system runs detections restricted to segment time-ranges, computes metrics per model, and persists the results.
2. **Given** a Perch detection covers a 5 s window containing three 0.2 s ground-truth pulses of the same species, **When** metrics are computed, **Then** the detection is counted once as `TP_P = 1` (detection matched), three GTs are each counted as covered (`TP_R += 3`), and no FN is incurred for this trio.
3. **Given** a BirdNET detection of species A and a GT of species B overlap in time, **When** metrics are computed, **Then** this pair contributes nothing to `TP_P` or `TP_R` (species mismatch); the detection is FP and the GT is FN.
4. **Given** results exist, **When** the user opens the evaluation view, **Then** per-model P/R/F1 and per-species breakdown are displayed, sortable by species F1.

---

### User Story 6 - Manage the Species Palette (Priority: P3)

Before or during annotation, a researcher curates the set's species palette so the annotation UI only shows the relevant taxa (and quick-access keyboard slots stay compact).

**Why this priority**: Improves annotation speed but a default palette from detector outputs is acceptable initially.

**Independent Test**: Add a species via GBIF search, confirm it appears in the palette dropdown; remove a species, confirm it disappears but existing TimeRangeAnnotations using it are preserved.

**Acceptance Scenarios**:

1. **Given** an AnnotationSet, **When** the user searches GBIF and selects a species, **Then** it is added to the palette via `AnnotationSetSpecies` and is selectable in the UI.
2. **Given** a species in the palette is in use by existing annotations, **When** the user removes it, **Then** the palette link is removed but existing TimeRangeAnnotations keep their `species_id` (the palette is a UI filter, not a foreign-key constraint on annotation species).
3. **Given** the palette is empty, **When** sampling completes, **Then** a default palette is suggested from detector top-N species observed on the sampled recordings (optional enhancement).

---

### Edge Cases

- **Filter yields too few recordings**: sampling returns fewer segments than `num_segments`; set status becomes `ready` with a `sampling_warning`.
- **Segment straddles end-of-recording**: sampling MUST constrain `end_time_sec <= recording.duration_sec`; otherwise reject the candidate and resample.
- **Overlapping TimeRangeAnnotations**: allowed (different species or even same species flagged separately).
- **Species removed from palette but still referenced**: preserved on existing annotations; re-add to edit cleanly.
- **Evaluation triggered on an in-progress set**: allowed but flagged as "partial ground truth; metrics provisional".
- **Detection outside any segment window**: ignored (not counted as FP) — evaluation is scoped to segment time-ranges only.
- **Empty-marked segment with detections**: each detection is an FP; no TP/FN is possible since there are no GTs.
- **Two annotators disagree**: v1 assumes single-annotator-per-segment. Multi-annotator consensus is out of scope.

## Requirements *(mandatory)*

### Functional Requirements

#### AnnotationSet Management
- **FR-001**: The system MUST create an AnnotationSet with `name`, `project_id`, `dataset_id`, optional `filter_date_range`, optional `filter_time_of_day_range`, `segment_length_sec >= 10`, `num_segments >= 1`.
- **FR-002**: The system MUST launch a background sampling job that selects recordings matching the filters and extracts `num_segments` random non-overlapping segments of the requested length, persisted as AnnotationSegment rows.
- **FR-003**: The system MUST expose AnnotationSet status (`sampling | ready | in_progress | completed`) and transition it automatically based on segment annotation progress (all segments `annotated` or `skipped` => `completed`).
- **FR-004**: The system MUST allow updating AnnotationSet metadata (name) but MUST NOT allow changing sampling parameters after `ready`.
- **FR-005**: The system MUST support deleting an AnnotationSet and cascade to its segments, TimeRangeAnnotations, notes, and palette links.

#### Segment Annotation
- **FR-006**: The system MUST allow creating, updating, and deleting TimeRangeAnnotations within a segment; `start_time_sec` and `end_time_sec` MUST satisfy `0 <= start < end <= segment_length_sec`.
- **FR-007**: Each TimeRangeAnnotation MUST reference exactly one `species_id` from the existing `Species` table.
- **FR-008**: The system MUST allow marking a segment as empty (`is_empty = true`, `status = annotated`), and automatically unset `is_empty` when a TimeRangeAnnotation is added.
- **FR-009**: The system MUST record `annotated_by_id` and `annotated_at` when a segment transitions to `annotated`.
- **FR-010**: The system MUST allow skipping a segment (`status = skipped`) which excludes it from evaluation denominators.

#### Notes
- **FR-011**: The system MUST attach notes to either a segment or a TimeRangeAnnotation (not both in a single note row).
- **FR-012**: The system MUST support an `is_issue` flag on notes for surfacing quality concerns.

#### Species Palette
- **FR-013**: The system MUST maintain a per-AnnotationSet species palette via a many-to-many link to the existing `Species` table.
- **FR-014**: Removing a species from the palette MUST NOT cascade to existing TimeRangeAnnotations.

#### Cross-Model Evaluation
- **FR-015**: The system MUST run evaluation for a list of model identifiers (built-ins `birdnet`, `perch`, plus Custom model UUIDs) against an AnnotationSet.
- **FR-016**: The system MUST compute per-model `precision`, `recall`, `f1` overall and per species using the **symmetric overlap rule** defined in `research.md` (any positive time-overlap with matching `species_id` counts; no 1:1 matching, no IoU threshold, no taxonomy fallback).
- **FR-017**: The system MUST scope detections to segment time-ranges: detections outside any segment are discarded before matching.
- **FR-018**: The system MUST persist evaluation results (`EvaluationRun` + `EvaluationResult` per model) for later retrieval without re-running.
- **FR-019**: The system MUST allow re-running evaluation; the latest run per (set, model) is considered current.

### Key Entities

- **AnnotationSet**: Named reference collection scoped to a project + dataset, parameterized by sampling filters and segment geometry, with a species palette.
- **AnnotationSegment**: Materialized segment of a recording, annotatable independently, with explicit empty/skipped states.
- **TimeRangeAnnotation**: A `[start, end]` interval inside a segment tagged with a single species.
- **AnnotationSetSpecies** (association): Palette membership.
- **AnnotationSegmentNote / TimeRangeAnnotationNote** (association): Link to existing Note entity.
- **EvaluationRun / EvaluationResult**: Persisted P/R/F1 output per (set, model, species).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Sampling of 100 segments over a dataset of 500 recordings completes in under 60 s.
- **SC-002**: An annotator can process (open, listen, annotate or mark empty, save) 30 s segments at >= 60 segments/hour.
- **SC-003**: Creating or updating a TimeRangeAnnotation returns in < 200 ms p95.
- **SC-004**: Evaluating BirdNET + Perch + one Custom model on a 100-segment set completes in under 5 minutes (assumes detections are pre-cached; otherwise bounded by inference throughput).
- **SC-005**: Per-species P/R/F1 output is numerically reproducible: re-running evaluation with the same inputs yields identical numbers (deterministic aggregation).
- **SC-006**: Evaluation metric is window-size invariant: swapping a model's internal window length (e.g., BirdNET 3s vs. a hypothetical 1s variant) on the same detections-equivalent output yields identical P/R/F1 per the formula in `research.md`.

## Out of Scope

- Bounding-box / frequency-range annotation.
- Hierarchical tag taxonomy; only flat single-species labels are used.
- Multi-annotator consensus or IRR (inter-rater reliability) calculations.
- Approval / rejection workflow on individual annotations.
- Export to AOEF / CSV / JSON (can be added later once the core eval loop is trusted).
- Audit Set feature (scheduled for removal in Phase E).

## Assumptions

- Every recording has a reliable `duration_sec` and, when filters are applied, a reliable `recorded_at`.
- Detector models already exist and expose a way to run detections on a recording interval, returning `(start_sec, end_sec, species_id, score)` tuples.
- Species identity is captured solely via `species_id` from the existing `Species` table; taxonomy-aware matching is explicitly out of scope for v1.
