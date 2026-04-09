# Model Training Pipeline Overhaul (v5 — final)

## Overview

Rebuild the custom model training pipeline: structured data sampling, active
learning iteration, and rigorous evaluation.

## Design Principles

1. **Lightweight**: Sub-10s for sampling/AL on ≤50k embeddings. Chunk-based
   scoring via pgvector binary format, capped candidate pools, `TABLESAMPLE`.
2. **Celery-first**: All heavy compute runs as Celery tasks with polling.
3. **Single training path**: All models use round-based training. Remove
   `training_session_ids` entirely.
4. **Pre-created annotations**: Seed/AL rounds create `Annotation` records
   upfront. Users label via existing vote API with `review_min_votes=1`
   for sampling-sourced annotations.

## Architecture

### Training Data Flow

```
Model (target_tag_id NOT NULL, reference_session_id in training_config)
  └→ SamplingRounds (seed, then 0-4 AL rounds)
       └→ SamplingRoundItems (embedding_id + annotation_id NOT NULL)
            └→ Annotations (status: unreviewed → confirmed/rejected)
                 └→ Training query joins items → annotations → embeddings
```

### Training Query

```sql
SELECT e.vector, a.status, e.recording_id
FROM sampling_round_items sri
JOIN sampling_rounds sr ON sr.id = sri.sampling_round_id
JOIN annotations a ON a.id = sri.annotation_id
JOIN embeddings e ON e.id = sri.embedding_id
WHERE sr.custom_model_id = :model_id
  AND a.status IN ('confirmed', 'rejected')
  AND a.tag_id = :target_tag_id
```

### Co-occurrence Policy

Only annotations matching `target_tag_id`:
- `confirmed` + matching tag → positive (1)
- `rejected` + matching tag → negative (0)
- Different tag → ignored

### Annotation Lifecycle

Seed/AL tasks pre-create `Annotation` records as `unreviewed` with
`source='sampling_round'`. These annotations bypass the project's
`review_min_votes` consensus requirement — a single vote immediately
sets the status to `confirmed` or `rejected`. This is appropriate because
model training is a single-user workflow, not a collaborative review.

### Query Vector Source

Seed sampling requires reference embeddings for Easy Positives / Boundary.
These come from the model's associated search session, stored in
`training_config.reference_session_id`. The Celery task:
1. Loads the search session's `species_config` to get reference audio keys
2. Runs embedding inference on reference audio (or reuses cached embeddings)
3. Uses these as query vectors for pgvector nearest-neighbor queries

### Cross-Round Duplicate Prevention

AL sampling queries exclude all embeddings already in any round for the model:

```sql
WHERE e.id NOT IN (
    SELECT embedding_id FROM sampling_round_items sri2
    JOIN sampling_rounds sr2 ON sr2.id = sri2.sampling_round_id
    WHERE sr2.custom_model_id = :model_id
)
```

### Embedding Fetch Performance

Current per-row vector parsing is the bottleneck for large datasets.
New code uses pgvector's binary format with batch fetching:

```python
# Fetch vectors as binary blobs in batches of 5000
result = await db.execute(text("""
    SELECT e.id, e.vector::bytea, e.recording_id
    FROM embeddings e
    WHERE e.model_name = :model AND ...
    LIMIT 5000 OFFSET :off
"""))
# Parse batch to numpy array in one operation
vectors = np.frombuffer(b''.join(row.vector for row in rows),
                        dtype=np.float32).reshape(-1, dim)
```

This avoids per-row JSON/text parsing overhead.

---

## Phase 0: Bug Fixes + Schema

**Goal**: Fix evaluation bugs, lay schema foundation. Single migration + deploy.

### Bug Fixes

**1. Data Leak** (`ml/classifiers.py`):
1. Split 20% test upfront (stratified)
2. CV on 80% to pick C
3. Train on 80% + unlabeled (exclude test recordings from unlabeled pool)
4. Evaluate on held-out 20%
5. Final model: retrain on ALL labeled with best C (metrics from step 4)

Recording-level unlabeled exclusion is done here, not deferred to Phase 2:
```sql
WHERE e.recording_id NOT IN (
    SELECT DISTINCT recording_id FROM test_set_recording_ids
)
```

**2. Metrics Names** (`ml/classifiers.py`, `types/custom-model.ts`, `+page.svelte`):
Standardize: `roc_auc`, `training_duration_s`, `confusion_matrix` as
`[[tn,fp],[fn,tp]]`.

### DB Migration (0016)

```sql
-- Sampling rounds with task tracking
CREATE TABLE sampling_rounds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    custom_model_id UUID NOT NULL REFERENCES custom_models(id) ON DELETE CASCADE,
    round_number INTEGER NOT NULL DEFAULT 0,
    round_type VARCHAR(20) NOT NULL
        CHECK (round_type IN ('seed', 'active_learning')),
    sampling_config JSONB,
    sample_count INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    job_id VARCHAR(255),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (custom_model_id, round_number)
);
CREATE INDEX ix_sampling_rounds_model ON sampling_rounds(custom_model_id);

-- Items within each round
CREATE TABLE sampling_round_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sampling_round_id UUID NOT NULL
        REFERENCES sampling_rounds(id) ON DELETE CASCADE,
    embedding_id UUID NOT NULL
        REFERENCES embeddings(id) ON DELETE CASCADE,
    sample_type VARCHAR(20) NOT NULL
        CHECK (sample_type IN (
            'easy_positive', 'boundary', 'others', 'active_learning'
        )),
    similarity FLOAT,
    decision_distance FLOAT,
    annotation_id UUID NOT NULL
        REFERENCES annotations(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (sampling_round_id, embedding_id)
);
CREATE INDEX ix_sri_round ON sampling_round_items(sampling_round_id);
CREATE INDEX ix_sri_annotation ON sampling_round_items(annotation_id);

-- Model schema changes
ALTER TABLE custom_models ADD COLUMN training_config JSONB;
ALTER TABLE custom_models ALTER COLUMN target_tag_id SET NOT NULL;
ALTER TABLE custom_models DROP COLUMN training_session_ids;
```

### Code Removals (Phase 0)

Remove from codebase:
- `training_session_ids` from `CustomModel` ORM, `CustomModelCreate` schema,
  `CustomModelResponse` schema, service layer, frontend types
- `_fetch_training_embeddings` (replaced by `_fetch_training_data` in Phase 1)
- Any UI referencing `training_session_ids`

### Changes

| File | Change |
|------|--------|
| `ml/classifiers.py` | Fix data leak; recording-level unlabeled exclusion |
| `types/custom-model.ts` | Align metric names; remove training_session_ids |
| `models/+page.svelte` | Fix metric display; remove session selection UI |
| `models/sampling_round.py` | New ORM: SamplingRound, SamplingRoundItem |
| `models/custom_model.py` | Remove training_session_ids; target_tag_id NOT NULL |
| `schemas/custom_model.py` | target_tag_id required; training_config; drop training_session_ids |
| `services/custom_model.py` | Store training_config; remove session-based logic |
| `workers/classifier_tasks.py` | target_tag_id filter; training_config read; remove old fetch |
| `api/v1/custom_models.py` | Remove training_session_ids from create; train reads training_config |

### Completion Definition
- Data leak fixed (unit test)
- Recording-level unlabeled exclusion in place
- Metrics display correctly
- target_tag_id NOT NULL enforced
- training_session_ids fully removed
- Migration applies cleanly

---

## Phase 1: Seed Sampling + Training

**Goal**: 3-category seed sampling, annotation pre-creation, round-based training.

**Depends on**: Phase 0

### Seed Sampling (Celery Task: `generate_seed_samples`)

Input: `model_id`. Task reads `training_config.reference_session_id` to get
query vectors.

| Category | Method | Count | Time |
|----------|--------|-------|------|
| Easy Positives | `ORDER BY vector <=> :query LIMIT 5` (HNSW) | 5 | <100ms |
| Boundary | `ORDER BY vector <=> :query LIMIT 205 OFFSET 5` → random 10 | 10 | <200ms |
| Others | `TABLESAMPLE BERNOULLI(p)` → 1000 candidates → farthest-first 20 | 20 | <2s |

Total: ~35 items, <3s.

For each item, the task:
1. Creates an `Annotation(status='unreviewed', tag_id=model.target_tag_id,
   source='sampling_round')` — bypasses consensus requirement
2. Creates a `SamplingRoundItem(annotation_id=annotation.id, ...)`

### Training Path

Single path — `_fetch_training_data` replaces old `_fetch_training_embeddings`:

```python
async def _fetch_training_data(db, model_id, target_tag_id):
    return await db.execute(text("""
        SELECT e.vector, a.status, e.recording_id
        FROM sampling_round_items sri
        JOIN sampling_rounds sr ON sr.id = sri.sampling_round_id
        JOIN annotations a ON a.id = sri.annotation_id
        JOIN embeddings e ON e.id = sri.embedding_id
        WHERE sr.custom_model_id = :model_id
          AND a.status IN ('confirmed', 'rejected')
          AND a.tag_id = :target_tag_id
    """), {"model_id": str(model_id), "target_tag_id": str(target_tag_id)})
```

### New Files

| File | Purpose |
|------|---------|
| `ml/sampling.py` | farthest_first, seed sampling logic |
| `schemas/sampling.py` | Request/Response schemas |
| `repositories/sampling_round.py` | Repository |
| `SeedSamplingView.svelte` | 3-category lane UI |

### Modified Files

| File | Change |
|------|--------|
| `workers/classifier_tasks.py` | New task: `generate_seed_samples`; new `_fetch_training_data` |
| `api/v1/custom_models.py` | POST seed-samples, GET sampling-rounds, GET round detail |
| `services/custom_model.py` | generate_seed_samples, get_sampling_rounds |
| `services/annotation_vote.py` | Skip consensus for `source='sampling_round'` annotations |
| `ReviewTab.svelte` | Round-based view with 3-category lanes |
| `TrainingMeter.svelte` | Progress from round items |
| `api/custom-models.ts` | New API calls |
| `types/custom-model.ts` | SamplingRound, SamplingRoundItem types |

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/{model_id}/seed-samples` | Generate seed (returns round_id) |
| GET | `/{model_id}/sampling-rounds` | List rounds with status |
| GET | `/{model_id}/sampling-rounds/{round_id}` | Round detail + items |

### Completion Definition
- Seed generates 35 items in <5s
- Annotations pre-created, single vote confirms/rejects
- Training pulls from rounds
- End-to-end: create model → seed → label → train → metrics

---

## Phase 2: Evaluation Overhaul

**Goal**: Grouped CV + blind audit set.

**Depends on**: Phase 0, Phase 1

### Grouped CV

`StratifiedGroupKFold` (sklearn ≥1.5), group by `recording_id`.
Fallback: `StratifiedKFold` when `n_recordings < n_splits * 2`.

### Audit Set (Celery Task: `generate_audit_set`)

Generated after training:
1. Score project embeddings in chunks of 5000 (binary format)
2. Divide scores into 5 buckets, sample 4-10 per bucket → ~20-50 items
3. Exclude all `sampling_round_items` embeddings for this model
4. Pre-create `Annotation(source='audit_set')` for each item
5. User labels via vote API (same single-vote bypass)

### DB Migration (0017)

```sql
ALTER TABLE custom_models ADD COLUMN audit_metrics JSONB;

CREATE TABLE audit_set_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    custom_model_id UUID NOT NULL
        REFERENCES custom_models(id) ON DELETE CASCADE,
    embedding_id UUID NOT NULL
        REFERENCES embeddings(id) ON DELETE CASCADE,
    recording_id UUID NOT NULL
        REFERENCES recordings(id) ON DELETE CASCADE,
    predicted_proba FLOAT,
    annotation_id UUID NOT NULL
        REFERENCES annotations(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (custom_model_id, embedding_id)
);
CREATE INDEX ix_audit_model ON audit_set_items(custom_model_id);
```

### New Files

| File | Purpose |
|------|---------|
| `ml/evaluation.py` | select_audit_set (score-stratified), evaluate_on_audit_set |

### Modified Files

| File | Change |
|------|--------|
| `ml/classifiers.py` | `recording_ids` param; StratifiedGroupKFold |
| `workers/classifier_tasks.py` | New task: `generate_audit_set`; exclude audit from unlabeled |
| `models/sampling_round.py` | Add AuditSetItem ORM |
| `api/v1/custom_models.py` | POST audit-set, GET audit-set, POST audit-set/evaluate |
| `types/custom-model.ts` | cv_metrics + audit_metrics |
| `models/+page.svelte` | "Internal Validation" vs "Blind Audit" |
| `api/custom-models.ts` | Audit set API calls |

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/{model_id}/audit-set` | Generate audit set (Celery) |
| GET | `/{model_id}/audit-set` | Get audit items |
| POST | `/{model_id}/audit-set/evaluate` | Compute metrics from labels |

No `PATCH /audit-set/{item_id}` — labeling uses existing vote API on the
pre-created annotation_id. Consistent with seed/AL labeling.

### Completion Definition
- CV grouped by recording
- Audit set score-stratified, excluded from training
- Both metric layers displayed in UI

---

## Phase 3: Active Learning

**Goal**: 2-4 AL rounds after seed.

**Depends on**: Phase 1

### AL Iteration (Celery Task: `run_al_iteration`)

1. Train lightweight SVM (`SVC(kernel="linear", probability=False)`,
   no self-training). <1s for 200 samples.
2. Score unlabeled in chunks of 5000 via `decision_function` (binary format).
   Exclude all existing round items for this model.
   Keep running top-60 closest to margin via `MarginTracker`.
   Peak memory ~40MB per chunk.
3. Farthest-first on 60 candidates → select 20. <100ms.
4. Pre-create annotations, store round. Total: <10s for 50k.

### New Files

| File | Purpose |
|------|---------|
| `ml/active_learning.py` | select_al_samples, MarginTracker |
| `ALRoundView.svelte` | AL round UI |

### Modified Files

| File | Change |
|------|--------|
| `workers/classifier_tasks.py` | New task: `run_al_iteration` |
| `api/v1/custom_models.py` | POST suggest-samples |
| `services/custom_model.py` | dispatch AL task |
| `ml/classifiers.py` | `decision_function()` wrapper |
| `ReviewTab.svelte` | Multi-round accordion |
| `TrainingMeter.svelte` | Aggregate across rounds |
| `api/custom-models.ts` | suggestNextSamples() |

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/{model_id}/suggest-samples` | Trigger AL (returns round_id) |

Poll via `GET /sampling-rounds/{round_id}`.

### Convergence
- < 5 uncertain candidates → "model confident"
- Each round independently valuable

### Completion Definition
- AL in <10s for 50k, <50MB peak
- 2-4 rounds, then final training

---

## Summary

### Dependency Graph

```
Phase 0 (Bugs + Schema + Removals)
    └──→ Phase 1 (Seed + Training)
              ├──→ Phase 2 (Evaluation)  ─── parallel
              └──→ Phase 3 (AL)  ─────────┘
```

### Migrations

| # | Phase | Content |
|---|-------|---------|
| 0016 | 0 | sampling_rounds, sampling_round_items, custom_models.training_config, target_tag_id NOT NULL, DROP training_session_ids |
| 0017 | 2 | audit_set_items, custom_models.audit_metrics |

### All Endpoints

| Phase | Method | Endpoint |
|-------|--------|----------|
| 1 | POST | `/{model_id}/seed-samples` |
| 1 | GET | `/{model_id}/sampling-rounds` |
| 1 | GET | `/{model_id}/sampling-rounds/{round_id}` |
| 2 | POST | `/{model_id}/audit-set` |
| 2 | GET | `/{model_id}/audit-set` |
| 2 | POST | `/{model_id}/audit-set/evaluate` |
| 3 | POST | `/{model_id}/suggest-samples` |

### All New Files

| Phase | File |
|-------|------|
| 0 | `models/sampling_round.py` |
| 1 | `ml/sampling.py`, `schemas/sampling.py`, `repositories/sampling_round.py`, `SeedSamplingView.svelte` |
| 2 | `ml/evaluation.py` |
| 3 | `ml/active_learning.py`, `ALRoundView.svelte` |
