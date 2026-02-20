# Research: Annotation Feature

**Date**: 2026-02-19
**Feature Branch**: `003-annotation`

## Overview

This document captures research findings and technical decisions for the annotation feature implementation.

---

## 1. Annotation Data Model Architecture

### Decision
Follow the existing pattern from the legacy codebase (Whombat-derived) with separation between AnnotationProject, AnnotationTask, ClipAnnotation, and SoundEventAnnotation. Simplify by using UUID-based models with the established Mixin pattern.

### Rationale
- Legacy codebase has a proven data model for bioacoustic annotation
- Separation of concerns: project management vs. annotation data
- SoundEventAnnotation allows fine-grained bounding box annotations
- ClipAnnotation allows quick presence/absence tagging
- Tag system supports hierarchical categorization

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|-----------------|
| Single Annotation table | Can't distinguish clip-level vs. sound-event-level annotations |
| Flat tag system | Species taxonomy requires hierarchy (Genus > Species > Subspecies) |
| Inline notes (text field) | Notes need creator tracking and timestamps for review workflow |

### Implementation Notes
- AnnotationProject → AnnotationTask → ClipAnnotation → SoundEventAnnotation hierarchy
- Tags are shared across projects via many-to-many relationships
- Notes are separate entities with user and timestamp tracking
- SoundEvent stores geometry (bounding box coordinates) separately from annotation metadata

---

## 2. Tag System and GBIF Integration

### Decision
Use GBIF Species Suggest API (`/v1/species/suggest`) for species autocomplete, store GBIF taxon key for cross-reference.

### Rationale
- GBIF Species Suggest API is lightweight and fast (no auth required)
- Returns canonical name, scientific name, taxonomy hierarchy
- Widely used in biodiversity informatics
- Legacy codebase already references GBIF integration

### API Details
- **Endpoint**: `GET https://api.gbif.org/v1/species/suggest?q={query}&limit=10`
- **Response fields**: `key`, `canonicalName`, `scientificName`, `rank`, `kingdom`, `phylum`, `class`, `order`, `family`, `genus`
- **No authentication required**, no rate limiting (reasonable use)

### Tag Categories
| Category | Description | Example |
|----------|-------------|---------|
| `species` | Biological species | Parus major |
| `sound_type` | Type of sound | Song, Call, Alarm |
| `quality` | Recording quality | Clear, Noisy, Faint |

### Implementation Notes
- Backend proxy endpoint to GBIF API (avoids CORS issues)
- Store `gbif_taxon_key` on Tag for species tags
- Frontend autocomplete component with debounced GBIF search
- Allow manual tag creation for non-species categories

---

## 3. Sound Event Geometry

### Decision
Use AOEF-compatible geometry types: BoundingBox as primary, TimeInterval as secondary.

### Rationale
- BoundingBox (time_start, freq_low, time_end, freq_high) is the standard for spectrogram annotation
- TimeInterval (start_time, end_time) for frequency-agnostic annotations
- AOEF compatibility enables export to soundevent/Whombat ecosystem
- Matches Raven Pro selection table format (Begin Time, End Time, Low Freq, High Freq)

### Geometry Types
| Type | Fields | Use Case |
|------|--------|----------|
| BoundingBox | time_start, freq_low, time_end, freq_high | Species detection with frequency range |
| TimeInterval | start_time, end_time | Clip-level or frequency-agnostic events |

### Implementation Notes
- Store geometry as JSON in `geometry` column: `{"type": "BoundingBox", "coordinates": [t1, f1, t2, f2]}`
- Validate coordinates at service layer (time within clip bounds, freq within recording range)
- Frontend draws rectangles on spectrogram canvas

---

## 4. Annotation Review Workflow

### Decision
Implement a simple status-based review workflow with three states: pending, approved, rejected.

### Rationale
- Simple enough for small teams
- Sufficient for quality control without complex workflow engine
- Matches spec requirements (US5)

### Workflow States
```
pending → approved
pending → rejected → pending (re-submit after correction)
```

### Implementation Notes
- Review status stored on ClipAnnotation
- Reviewer ID and review timestamp tracked
- Review comments stored as Notes with `is_review` flag
- Filter annotations by review status in task list

---

## 5. Batch Task Generation

### Decision
Use Celery background task for batch annotation task generation from clips.

### Rationale
- Large datasets may have thousands of clips
- Generating tasks for all clips synchronously would timeout
- Constitution requires heavy operations via task queue
- Progress tracking via WebSocket for large batches

### Implementation Notes
- `POST /api/v1/annotation-projects/{id}/generate-tasks` triggers Celery task
- Task creates AnnotationTask for each clip in associated datasets
- Skip clips that already have tasks in the project
- Report progress: created/skipped/total

---

## 6. Export Formats

### Decision
Support JSON, CSV, and AOEF export formats.

### Rationale
- JSON: Universal, preserves all metadata
- CSV: Easy to use in spreadsheets and R/Python
- AOEF: Interoperable with soundevent/Whombat ecosystem

### AOEF Format Structure
```json
{
  "version": "1.1.0",
  "created_on": "2026-01-01T00:00:00Z",
  "data": {
    "recordings": [...],
    "clips": [...],
    "sound_events": [...],
    "tags": [{"id": 0, "key": "species", "value": "Parus major"}],
    "clip_annotations": [...],
    "sound_event_annotations": [...]
  }
}
```

### CSV Format
Raven-compatible selection table format:
| Column | Description |
|--------|-------------|
| Selection | Row number |
| Begin Time (s) | Start time |
| End Time (s) | End time |
| Low Freq (Hz) | Low frequency |
| High Freq (Hz) | High frequency |
| Tag | Species/label |
| Confidence | Score 0-1 |
| Annotator | Creator |

### Implementation Notes
- Use Celery for large exports (>1000 annotations)
- Stream ZIP file for AOEF (includes recording references)
- CSV export as direct download (small enough for sync)

---

## 7. Frontend Annotation Interface

### Decision
Extend existing SpectrogramViewer component with drawing capabilities using HTML5 Canvas overlay.

### Rationale
- SpectrogramViewer already exists from 002-data-management
- Canvas overlay allows drawing bounding boxes without modifying spectrogram rendering
- WaveSurfer.js regions plugin can handle time intervals
- Keyboard shortcuts essential for annotation speed (SC-001: 100 clips/hour)

### Key UI Components
| Component | Purpose |
|-----------|---------|
| AnnotationCanvas | Canvas overlay for drawing bounding boxes |
| TagSelector | Autocomplete tag selection with GBIF search |
| TaskNavigator | Previous/Next task navigation |
| ReviewPanel | Approve/reject with comments |
| AnnotationList | Sidebar showing annotations on current clip |

### Keyboard Shortcuts
| Key | Action |
|-----|--------|
| Space | Play/Pause |
| Enter | Complete task, move to next |
| Escape | Cancel current drawing |
| Delete/Backspace | Delete selected annotation |
| 1-9 | Quick-select tags |

---

## 8. Auto-save and Session Recovery

### Decision
Auto-save annotations on every change (debounced 500ms). No explicit save button.

### Rationale
- Prevents data loss from browser crashes or timeouts
- Matches modern UX expectations
- Spec edge case: "auto-save unsaved work for session recovery"

### Implementation Notes
- Debounced auto-save: save 500ms after last change
- Optimistic updates via TanStack Query mutations
- On reconnect: compare local state with server and resolve conflicts
- Show save indicator: "Saving..." / "Saved" / "Error"

---

## Summary of Dependencies

### Backend (to add to pyproject.toml)
```toml
# No new dependencies required
# httpx already available for GBIF API proxy
```

### Frontend (to add to package.json)
```json
# No new dependencies required
# wavesurfer.js already installed from 002-data-management
```

---

## Unresolved Questions

None - all technical decisions made.
