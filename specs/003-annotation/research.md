# Research: Annotation Feature (Revised)

**Feature Branch**: `003-annotation`
**Date**: 2026-04-17 (revision of 2026-02-19)

## Overview

This document captures the technical decisions for the annotation subsystem with the revised goal: **provide a ground-truth dataset for fair cross-model evaluation** (BirdNET 3s / Perch 5s / Custom). The previous iteration imported Whombat's bounding-box annotation model wholesale; the revision strips it down.

---

## 1. Why abandon the Whombat-style bounding box model

### Decision
Replace `SoundEventAnnotation(geometry = BoundingBox|TimeInterval)` with `TimeRangeAnnotation(start_sec, end_sec, species_id)`.

### Rationale
- The downstream evaluators (BirdNET / Perch / Custom classifiers in this project) do not publish per-frequency predictions — they return `(time_window, species, score)`. Annotating in frequency space therefore carries no evaluation value.
- Frequency annotation materially slows the annotator (typical speed drops 3–5x compared to time-only drag). For this project's use case (producing a reference set of ~100 segments) this friction is pure overhead.
- The absence of frequency annotation simplifies the UI component stack: waveform + single-axis drag, no spectrogram coordinate mapping required.

### Rejected alternatives
| Alternative | Rejected because |
|---|---|
| Keep `BoundingBox` as optional | Two code paths without a consumer; adds schema / migration surface |
| Use AOEF-compatible geometry JSON | Only useful for AOEF export, which is now out-of-scope |

---

## 2. Why `AnnotationSet` + `AnnotationSegment` instead of `AnnotationProject` + `AnnotationTask` + `ClipAnnotation`

### Decision
Collapse the 3-level hierarchy (Project/Task/ClipAnnotation) into 2 levels (Set/Segment). Tasks disappear; segments are directly annotatable.

### Rationale
- Assignment, priority, and review workflows (`AnnotationTask.assigned_to_id`, `priority`, `ClipAnnotation.review_status`) were premature for a small-team internal tool. v1 is single-annotator-per-segment.
- A "Task" added one layer of indirection without capturing any state the segment itself couldn't. Collapsing reduces one table, one migration, one set of queries, and one class of cross-table integrity rules.
- Sampling parameters (filter, segment length, count) are first-class attributes of the set — they describe *what the ground truth covers*, which is directly meaningful to the evaluation step.

---

## 3. Sampling algorithm

### Decision
Random, non-overlapping segments of fixed length drawn from recordings that pass the filter predicate.

### Algorithm
```
candidate_recordings = Recording.filter(
    dataset_id = set.dataset_id,
    recorded_at ∈ set.filter_date_range,
    time_of_day(recorded_at, site.timezone) ∈ set.filter_time_of_day_range,
    duration_sec >= set.segment_length_sec,
)

# Build a weighted list of (recording, slot_count) where
# slot_count = floor(duration / segment_length). Sample segments proportional
# to slot_count so long recordings don't starve short ones (but also aren't
# undersampled). Enforce non-overlapping slots within a recording using a set
# of taken slot indices.

segments = []
while len(segments) < set.num_segments and candidates_remaining:
    rec = weighted_random_choice(candidates)
    slot_idx = random_unused_slot(rec)
    if slot_idx is None: retire rec from candidates; continue
    segments.append(AnnotationSegment(
        recording_id = rec.id,
        start_time_sec = slot_idx * set.segment_length_sec,
        end_time_sec   = (slot_idx + 1) * set.segment_length_sec,
    ))

if len(segments) < set.num_segments:
    set.sampling_warning = f"only {len(segments)} / {set.num_segments} available"
set.status = 'ready'
```

### Rationale
- Fixed-size non-overlapping slots guarantee reproducibility and make evaluation bookkeeping trivial (detections are cropped per slot).
- Weighted-by-slot-count biasing avoids duration skew.
- Time-of-day is evaluated in the recording's local timezone (via its `Site.timezone` when present, otherwise UTC).

### Implementation notes
- Implemented as a Celery job (dispatched from `POST /annotation-sets/{id}/sample`).
- `segment_length_sec >= 10` is required: shorter segments give too little context for the annotator to identify species reliably.

---

## 4. Evaluation algorithm — symmetric overlap matching

### Decision
Compute precision and recall using **order-independent, non-1:1 overlap matching**. No IoU threshold, no mid-point rule, no taxonomy fallback.

### Formal definition

Let `GT` = ground-truth set of `(recording, segment_window, start, end, species_id)` from all `TimeRangeAnnotation`s, translated into recording-absolute coordinates. Note: segments with `is_empty = true` contribute zero GT rows but are still listed in the "covered recordings/windows" during detection cropping.

Let `DET` = detections from the model, filtered to overlap any segment's `(start, end)` (detections fully outside all segments are discarded before matching).

Overlap predicate on a `(det, gt)` pair:
```
overlap(det, gt) := det.species_id == gt.species_id
                  and max(det.start, gt.start) < min(det.end, gt.end)
```
Any strictly positive time overlap is sufficient; no IoU threshold.

**Precision side** (per detection):
```
TP_P = |{ d ∈ DET : ∃ g ∈ GT . overlap(d, g) }|
FP   = |{ d ∈ DET : ∀ g ∈ GT . not overlap(d, g) }|
precision = TP_P / (TP_P + FP)           # 0 if denom == 0
```

**Recall side** (per GT):
```
TP_R = |{ g ∈ GT : ∃ d ∈ DET . overlap(d, g) }|
FN   = |{ g ∈ GT : ∀ d ∈ DET . not overlap(d, g) }|
recall = TP_R / (TP_R + FN)              # 0 if denom == 0
```

**F1**: `2 * precision * recall / (precision + recall)` (0 if denom == 0).

Metrics are computed **overall** and **per `species_id`** (filtering both `GT` and `DET` to the species before applying the formulas).

### Why this specific rule

- **Window-size invariant** (the single most important property): Perch (5 s) and BirdNET (3 s) collapse any number of short events inside their window into a single detection. Under a 1:1 matching rule this penalizes the wider-window model unfairly (one detection can only "use" one GT). Under this symmetric rule:
  - 1 detection covering 3 GTs of the same species yields `TP_P = 1, TP_R = 3, FN = 0` — the detection is rewarded once on the precision side, each GT is credited on the recall side. No FN is incurred.
  - 3 detections hitting 1 GT yields `TP_P = 3, TP_R = 1, FN = 0` — over-detection is neither punished nor rewarded beyond what the detection count already implies (if those 3 detections were wrong about other GTs being absent, their FPs show up elsewhere).
- **No IoU threshold**: short target calls in a long window always have small IoU; a threshold makes recall brittle to window length. Overlap > 0 is the only rule that is length-agnostic.
- **No GT-center test**: requiring the GT centroid to be inside the detection introduces directionality and again disadvantages wide-window detectors on short calls near window boundaries.
- **Species match is strict (`species_id` equality)**: Echoroo currently has no "higher taxon" annotation level, so any rule involving genus or family matching is not implementable without inventing new data.

### Numerical example (from the spec)

A 5-second Perch window contains three 0.2-second pulses of species X. Perch emits one detection for species X covering the full 5 seconds.
- Detections: `[(0, 5, X)]` → `TP_P = 1`, `FP = 0` → precision = 1.0
- GTs: three rows of species X → all three overlap the detection → `TP_R = 3`, `FN = 0` → recall = 1.0
- F1 = 1.0. Window-size gives no penalty or bonus.

Compare to a 1:1 Hungarian match: the single detection would match one GT → `TP = 1`, `FN = 2` → recall = 0.33. This artificially rewards narrow-window models that happen to emit per-pulse detections.

### Rejected alternatives

| Alternative | Rejected because |
|---|---|
| 1:1 matching (Hungarian / greedy-by-IoU) | Penalizes wide-window models on clustered calls; violates SC-006 |
| IoU threshold (e.g., >= 0.3) | Threshold is length-dependent; BirdNET 3 s on 0.2 s calls always fails |
| GT-center-in-detection (soundevent `match_geometries` default) | Asymmetric; see above |
| Taxonomy-aware species match (match at genus when species differs) | Not representable — Echoroo has no taxon-level annotation; would require new data model |

---

## 5. Why explicit `is_empty` on segments

### Decision
Every segment carries an explicit boolean `is_empty` separate from `status`.

### Rationale
- Recall's denominator requires knowing, per evaluated window of audio, whether GT genuinely holds zero events. If we infer "empty" from "no TimeRangeAnnotation rows exist", we conflate "annotator confirmed silence" with "annotator never looked at this segment" — those have opposite implications for metrics.
- `status = annotated && count(TimeRangeAnnotation) == 0` could serve as a proxy but forces downstream code to join-and-count on every evaluation; an explicit flag is cheaper and self-documenting.
- The UI benefits too: the "Mark as empty" button is a primary action for a large fraction of segments, and it should be a one-click operation with visible persistent state.

### Invariants
- Creating a `TimeRangeAnnotation` sets `is_empty = false`.
- Setting `is_empty = true` is rejected if `TimeRangeAnnotation`s exist (the annotator must delete them first).
- `skipped` segments never contribute to either side of the metric.

---

## 6. Species palette design

### Decision
Per-set M2M link to the existing `Species` table (`AnnotationSetSpecies`). Removing from the palette does not cascade to existing annotations.

### Rationale
- The palette is a **UI filter** (autocomplete scope, keyboard shortcut slots), not a data integrity boundary. Making it an integrity boundary would mean losing annotations when a researcher reshapes the palette mid-project.
- Reusing the existing `Species` table avoids duplicating taxonomy data and inherits the GBIF integration already present (Japanese vernacular names, canonical names).

### GBIF integration reuse
- The existing GBIF search infrastructure (documented in `memory/MEMORY.md`) is reused directly; this spec does not re-specify it.
- Adding a species to the palette goes via `POST /annotation-sets/{id}/palette` with a `species_id`. Species creation itself (when the species isn't in the local table yet) flows through the existing `POST /species` endpoint.

---

## 7. Storing evaluation results

### Decision
Persist `EvaluationRun` (one per `(set, model_kind, model_ref)` execution) and `EvaluationResult` (one per `(run, species_id)` or overall with `species_id = NULL`).

### Rationale
- Running BirdNET/Perch inference on 100 segments is ~5 minutes; re-running every time the user opens the results page is wasteful.
- Storing per-species results at granularity chosen once keeps query latency O(1) per view; re-computing from raw detections on-demand would be O(detections) every view.
- Multiple historical runs are useful (comparing a tuned Custom model against its previous version). The latest run per `(set, model_kind, model_ref)` is considered "current" in the UI.

---

## 8. Out of scope / future work

- **Multi-annotator consensus / IRR**: v1 assumes single-annotator-per-segment. Supporting this requires an `annotations-per-segment` fan-out and a conflict resolution rule.
- **Export formats (AOEF / JSON / CSV)**: removable once the core P/R/F1 pipeline is trusted. The data model does not preclude adding them later; they are simply not in v1.
- **Taxon-aware matching**: add if Echoroo later gains higher-taxon annotation labels.
- **Frequency-aware annotation**: would require reintroducing `BoundingBox` geometry. Only worth doing if a frequency-aware model enters the evaluation pool.

---

## 9. Relationship to existing code

- `apps/api/echoroo/models/annotation.py` (`Annotation`, `AnnotationVote`) is part of the **detection review / voting** system and is unrelated to this feature. It must remain untouched. The new entity is named `TimeRangeAnnotation` (not `Annotation`) to avoid import-time collisions.
- Audit Set (scheduled for removal in Phase E) is explicitly not referenced by this spec.
- Existing `Species`, `Recording`, `Dataset`, `Site`, `Note`, `User`, `Project` models are reused as-is. Only `notes.is_issue` may need to be added as a nullable-default-false column if not already present.

---

## Summary of dependencies

- Backend: no new Python packages. Sampling uses existing Celery infra. Detection runs reuse existing BirdNET/Perch/Custom inference paths (same code path as the detection-review system).
- Frontend: no new packages. Waveform view reuses existing audio playback component; drag-to-create is implemented on the same canvas layer used elsewhere.
