# Echoroo Product Vision

> 日本語版: [VISION.ja.md](VISION.ja.md)

## Mission

Enable NPOs, local governments, and researchers to manage environmental audio data
and conduct wildlife surveys with the help of machine learning.
No expertise in bioacoustics or machine learning required.

## Target Users

**Primary target**: staff at NPOs and local governments conducting wildlife surveys

- Not experts in acoustics or ML
- Collect data by deploying autonomous recorders (e.g. AudioMoth) in the field
- Want to know "which species are at this location, and when"
- Need to produce reports for stakeholders
- Limited time and budget

## Core Principles

1. **ML-first**: users review ML results instead of annotating from scratch
2. **Zero configuration**: put data in, get results out
3. **Traceability**: the origin of every detection is trackable (model name, version, confidence, human verification status)
4. **Negative data matters**: distinguish "nothing was found" from "not yet reviewed"

---

## Data Model

### Hierarchy

```
Project (a survey project, e.g. "2026 Yatoyama Park Monitoring")
  └── Site (a deployment location, represented geographically by an H3 hexagonal cell)
       └── Dataset (one deployment of one recorder = a directory of audio files)
            └── Recording (a single audio file with metadata)
```

### Annotations (attached directly to recordings)

An annotation is a **time segment on a recording** and does not depend on fixed-length clips.

```
Recording
  ├── Annotation (start_time, end_time, species tag, source, confidence, status)
  └── Confirmed region (start_time, end_time — records the time interval a human reviewed)
```

- **Annotation**: "species X was detected from time Y to Z"
  - Source: birdnet / perch_search / human
  - Status: unreviewed / confirmed / rejected
  - Confidence: 0.0–1.0 (for ML detections)
  - Optional: freq_low, freq_high (frequency band, for experts)

- **Confirmed region (ConfirmedRegion)**: "a human reviewed this time interval"
  - With annotations = positive data
  - Without annotations = negative data (explicitly "nothing was there")
  - Unconfirmed intervals = unknown

### Detection run records (DetectionRun) — internal data, not exposed to users

ML execution metadata is retained for traceability:
- Model name, version, parameters
- Processing status, counts
- Linkage between annotations and their source run

### Clips — internal processing only

Clips are **not exposed to users**. They are generated dynamically in memory at
ML inference time (supporting per-model input lengths, e.g. 3 seconds for
BirdNET, 5 seconds for Perch).

### Deprecated concepts

The following Whombat-derived concepts are **deprecated**:
- Annotation projects (AnnotationProject)
- Annotation tasks (AnnotationTask)
- Clip annotations (ClipAnnotation)
- Sound event annotations (SoundEventAnnotation → replaced by Annotation)
- User-facing clips

---

## Core Workflows

### 1. Data import + automatic processing (background)

```
User imports a dataset (a directory of audio files)
  ↓ (automatic, non-blocking, Celery workers)
  ├── BirdNET detection → saved as annotations (source=birdnet)
  └── Perch embedding generation → saved to pgvector
  ↓
User is notified: "Processing complete"
```

- ML model selection is configured by administrators. Users do not choose per run. Defaults are:
- Detection: BirdNET (bird species identification)
- Embeddings: Perch (similarity search for species not covered by BirdNET)
- Processing is fully non-blocking. Users can keep working while processing runs

### 2. Reviewing ML detections (the user's main task)

```
Species List View (default screen)
  → All detected species listed with counts and confidence
  → Click a species → card-based review view
  → For each detection:
     1. The ML-detected interval is highlighted on the spectrogram
     2. The user listens/looks to verify
     3. If correct: drag to mark the actual time range of the call + confirm the species
        If a false positive: reject (noise)
        If a different species: select the correct species + mark the time range
```

Review flow:
- ML detections (per clip) are shown as an underlay
- Users **always mark the actual time range of the call** before confirming
- This produces precise annotations independent of clip length
- Result: human-verified time-segment annotations, independent of the ML detection

UI design principles:
- The Species List is the entry point (directly answers "what was found?")
- Card grid with mini spectrograms and play buttons
- Highlight the ML-detected interval and prompt range selection within it
- No frequency-axis manipulation by default
- Keyboard shortcuts for power users

### 3. Similarity search (finding species not covered by BirdNET)

```
User selects or uploads a reference sound
  → Similarity search across the whole dataset using Perch embeddings
  → Candidates are presented as detections
  → User reviews: confirm / reject
```

Use cases:
- Mammals, amphibians, insects (species BirdNET does not cover)
- Rare or locally endemic species absent from BirdNET's training data
- Exploratory use: "what is this sound?"

### 4. Manual review by sampling

```
User clicks "sampling review" on a dataset
  → System generates random time segments (excluding confirmed regions)
  → User listens to each segment
  → If a species call is present: add an annotation
  → Mark the segment as confirmed (creates a ConfirmedRegion)
```

Purpose:
- Creating negative data for ML training
- Quality-checking ML results
- Finding species the ML missed

---

## Presenting Results

### Explore (cross-project search)

- Sites displayed on a map as H3 hexagonal cells
- Search by species name
- Filters: "verified only" / "all detections"
- Results: list of matching sites → click through to the dataset

### Dataset detail view

- **Spiral Plot**: temporal patterns of detections (time-of-day × date heatmap)
- **Review progress**: confirmed / unreviewed / unprocessed
- **Species List**: detection counts and verification status per species
- Links to individual recordings

---

## Export

### 1. Detection CSV (for survey reports)

```csv
recording_filename, start_time, end_time, species, confidence,
source, model_name, model_version, verified, verified_by,
search_query_recording, search_query_start_time, search_query_end_time
```

Fields:
- **source**: `birdnet` / `perch_search` / `human`
- **verified**: `true` / `false` / `null` (unreviewed)
- **search_query_***: for embedding-search results, the source audio of the query

### 2. ML training dataset (for model development)

Export verified data in a form directly usable for machine learning.

```
export/
  ├── audio/                      # Audio files (cut per segment)
  │   ├── rec001_12.3-14.8.wav    # Positive: call present
  │   ├── rec002_0.0-15.0.wav     # Negative: confirmed, no call
  │   └── ...
  ├── annotations.csv             # Labels for each audio file
  │   recording, start, end, species, is_positive
  │   rec001, 12.3, 14.8, Parus_minor, true
  │   rec002, 0.0, 15.0, , false
  ├── metadata.json               # Export conditions, model info,
  │                               # sampling conditions, etc.
  └── README.txt                  # Dataset description
```

Contents:
- **Positive data**: audio clips with human-verified, range-marked annotations
- **Negative data**: audio clips from ConfirmedRegions with no annotations
- **Metadata**: includes the original ML detections, sampling conditions, and model info
- Also includes data from sampling reviews (the sampled audio + its annotations)

### 3. Additional formats (future)

- **PDF report**: a formatted survey report for stakeholders
  - Species checklist, activity timeline, site map
  - Usable as-is for government/NPO reporting
- **JSON**: machine-readable structured data

---

## Sharing

- **Detections-only sharing**: share "when, where, which species" across projects without exposing raw audio
- **Verified filter**: recipients can view only human-verified detections
- **No unauthenticated access**: sharing is within the platform (between authenticated users) only
- **Data download**: enhanced export for authorized users

---

## Information Architecture

### Navigation (5 items)

```
Overview       — site map + detection summary + recent activity
Sites & Data   — site management + datasets + recordings (unified view)
Detections     — ML results + review (the core feature)
Reports        — export + sharing
Settings       — project settings + member management
```

### Terminology mapping

| Internal / technical term | User-facing label |
|---------------------------|-------------------|
| Annotation | Detection |
| Tag | Species |
| SoundEvent | Detection |
| Clip | (not exposed) |
| ConfirmedRegion | Reviewed region |
| DetectionRun | (not exposed) |

---

## Administrator Settings

- **ML models**: choose which models run (detection = BirdNET, embeddings = Perch)
- **User management**: roles, activation/deactivation, email verification
- **System settings**: registration mode, session timeout
- **Recorder catalog**: device types (AudioMoth, etc.)
- **License catalog**: CC licenses for datasets

---

## Prioritized Roadmap

### P0: Foundation (required for launch)
- Data management (project → site → dataset → recording) ✓ (mostly implemented)
- Metadata management + visibility settings ✓ (mostly implemented)

### P1: Core value
- Automatic BirdNET detection on dataset import
- Perch embedding generation on dataset import
- Species List View + review UI (verification by range marking)
- New annotation model (time segments on recordings)
- ConfirmedRegion model
- Data export (detection CSV + ML training dataset)

### P2: Differentiation
- Perch similarity-search UI
- Detection sharing (across projects)
- Explore view (map + species search)
- Manual review workflow by sampling
- Spiral Plot / timeline heatmap

### P3: Growth
- PDF report generation
- Custom model training pipeline
- Batch inference with custom models
- Guided onboarding flow
- Tablet optimization
