# Implementation Plan: Explore, Reports & Export

**Branch**: `005-explore-reports` | **Date**: 2026-03-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-explore-reports/spec.md`

## Summary

This plan covers the implementation of Explore views, dataset detail enhancements (Spiral Plot, review progress, species list), sampling review workflow, data export (detection CSV and ML training dataset), and detection sharing between projects. The implementation follows a TDD approach with FastAPI backend and SvelteKit frontend, building on existing H3 map infrastructure and annotation models.

## Technical Context

**Language/Version**: Python 3.11 (Backend), TypeScript 5.x (Frontend)
**Primary Dependencies**: FastAPI, SQLAlchemy 2.0, Pydantic, SvelteKit, Svelte 5, TanStack Query, Tailwind CSS, mapbox-gl, h3-js, HTML5 Canvas API
**Storage**: PostgreSQL with pgvector extension
**Testing**: pytest (backend), vitest (frontend), Playwright (e2e)
**Target Platform**: Linux server (Docker), Modern browsers
**Project Type**: Web application (frontend + backend)
**Performance Goals**: Map < 3s for 1000 sites, Search < 500ms, Spiral Plot < 2s for 10K points
**Constraints**: Background processing for large exports, Canvas for Spiral Plot rendering
**Scale/Scope**: Up to 1000 sites, 100K+ annotations, 10K+ recordings per dataset

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Clean Architecture PASS
- **API Layer**: FastAPI routers in `apps/api/echoroo/api/v1/`
- **Service Layer**: Business logic in `apps/api/echoroo/services/`
- **Repository Layer**: Data access in `apps/api/echoroo/repositories/`
- **Domain Models**: SQLAlchemy models in `apps/api/echoroo/models/`
- Dependency injection via FastAPI's `Depends()`

### II. Test-Driven Development PASS
- Contract tests for all API endpoints (pytest)
- Integration tests for service layer (sampling algorithm, export generation)
- Unit tests for Spiral Plot data aggregation and sampling logic
- Frontend component tests (vitest) for Canvas rendering and map interactions
- E2E tests (Playwright) for complete workflows

### III. Type Safety PASS
- **Backend**: Pydantic schemas for request/response, SQLAlchemy 2.0 mapped_column types
- **Frontend**: TypeScript strict mode, OpenAPI-generated types, no `any` types

### IV. ML Pipeline Architecture N/A (indirect)
- This feature consumes ML outputs (annotations from DetectionRun) but does not run ML inference
- Export format designed for downstream ML training consumption

### V. API Versioning PASS
- All endpoints under `/api/v1/`
- Backward compatibility within major version

### Security Requirements PASS
- JWT token validation for all endpoints
- Project-level permission checks for data access
- Visibility controls for Explore (public projects + user's projects only)
- Sharing restricted to authenticated users

## Project Structure

### Documentation (this feature)

```text
specs/005-explore-reports/
├── spec.md              # Feature specification
├── plan.md              # This file
└── tasks.md             # Implementation tasks
```

### Source Code (repository root)

```text
apps/api/                           # FastAPI backend
├── echoroo/
│   ├── api/v1/                     # API routers
│   │   ├── explore.py              # Explore search endpoints (NEW)
│   │   ├── sampling.py             # Sampling review endpoints (NEW)
│   │   ├── detection_export.py     # Detection export endpoints (NEW)
│   │   └── sharing.py              # Detection sharing endpoints (NEW)
│   ├── models/                     # SQLAlchemy models
│   │   ├── confirmed_region.py     # ConfirmedRegion model (NEW)
│   │   ├── sampling.py             # SamplingSession, SamplingSegment (NEW)
│   │   ├── sharing.py              # DetectionShare model (NEW)
│   │   └── export_job.py           # ExportJob model (NEW)
│   ├── schemas/                    # Pydantic schemas
│   │   ├── explore.py              # Explore search schemas (NEW)
│   │   ├── spiral_plot.py          # Spiral Plot data schemas (NEW)
│   │   ├── sampling.py             # Sampling schemas (NEW)
│   │   ├── detection_export.py     # Export schemas (NEW)
│   │   └── sharing.py              # Sharing schemas (NEW)
│   ├── services/                   # Business logic
│   │   ├── explore.py              # Explore search service (NEW)
│   │   ├── spiral_plot.py          # Spiral Plot aggregation (NEW)
│   │   ├── sampling.py             # Sampling algorithm (NEW)
│   │   ├── detection_export.py     # Detection CSV + ML export (NEW)
│   │   ├── confirmed_region.py     # ConfirmedRegion service (NEW)
│   │   └── sharing.py              # Sharing service (NEW)
│   └── repositories/               # Data access layer
│       ├── confirmed_region.py     # ConfirmedRegion repo (NEW)
│       ├── sampling.py             # Sampling repo (NEW)
│       ├── sharing.py              # Sharing repo (NEW)
│       └── export_job.py           # ExportJob repo (NEW)
├── tests/
│   ├── contract/                   # API contract tests
│   │   ├── test_explore.py         # Explore endpoint tests (NEW)
│   │   ├── test_sampling.py        # Sampling endpoint tests (NEW)
│   │   ├── test_detection_export.py # Export endpoint tests (NEW)
│   │   └── test_sharing.py         # Sharing endpoint tests (NEW)
│   ├── integration/                # Service integration tests
│   │   ├── test_explore_flow.py    # Explore search flow (NEW)
│   │   ├── test_sampling_flow.py   # Sampling review flow (NEW)
│   │   └── test_export_flow.py     # Export generation flow (NEW)
│   └── unit/                       # Unit tests
│       ├── test_sampling_algo.py   # Sampling algorithm logic (NEW)
│       └── test_spiral_plot.py     # Spiral Plot aggregation (NEW)
└── alembic/                        # Database migrations

apps/web/                           # SvelteKit frontend
├── src/
│   ├── routes/                     # SvelteKit routes/pages
│   │   ├── (app)/
│   │   │   ├── explore/            # Explore page (NEW)
│   │   │   │   └── +page.svelte
│   │   │   └── projects/[id]/
│   │   │       └── datasets/[datasetId]/
│   │   │           ├── +page.svelte           # Enhanced (ADD Spiral Plot, Species List, Review Progress)
│   │   │           └── sampling-review/
│   │   │               └── +page.svelte       # Sampling review page (NEW)
│   ├── lib/
│   │   ├── api/                    # API client, TanStack Query hooks
│   │   │   ├── explore.ts          # Explore API client (NEW)
│   │   │   ├── sampling.ts         # Sampling API client (NEW)
│   │   │   ├── detection-export.ts # Export API client (NEW)
│   │   │   └── sharing.ts          # Sharing API client (NEW)
│   │   ├── components/             # Reusable UI components
│   │   │   ├── explore/            # Explore components (NEW)
│   │   │   │   ├── ExploreMap.svelte          # Multi-site H3 map
│   │   │   │   ├── SpeciesSearch.svelte       # Species name search
│   │   │   │   └── SitePopup.svelte           # Site info popup
│   │   │   ├── visualization/      # Data visualization (NEW)
│   │   │   │   ├── SpiralPlot.svelte          # Canvas-based heatmap
│   │   │   │   ├── ReviewProgress.svelte      # Review progress bar
│   │   │   │   └── SpeciesDetectionList.svelte # Species detection counts
│   │   │   ├── sampling/           # Sampling review components (NEW)
│   │   │   │   ├── SamplingSetup.svelte       # Session configuration
│   │   │   │   ├── SegmentReviewer.svelte     # Individual segment review
│   │   │   │   └── SamplingSummary.svelte     # Session results
│   │   │   └── export/             # Export components (NEW)
│   │   │       ├── DetectionExportDialog.svelte # Detection CSV export
│   │   │       └── MLExportDialog.svelte       # ML training export
│   │   └── types/                  # TypeScript types
│   │       ├── explore.ts          # Explore types (NEW)
│   │       └── sampling.ts         # Sampling types (NEW)
└── tests/
    ├── unit/                       # Component unit tests
    │   └── SpiralPlot.test.ts      # Canvas rendering tests (NEW)
    └── e2e/                        # Playwright e2e tests
        ├── explore.spec.ts         # Explore flow tests (NEW)
        ├── sampling.spec.ts        # Sampling review flow (NEW)
        └── export.spec.ts          # Export flow tests (NEW)
```

**Structure Decision**: Extends existing web application structure with new route groups for Explore (top-level), sampling review (nested under dataset), and new API routers. Spiral Plot uses Canvas API for performance with large datasets.

## Key Technical Decisions

### Spiral Plot: Canvas over SVG
- **Canvas**: Better performance for dense heatmaps (10K+ data points). Rasterized rendering avoids DOM overhead.
- **SVG**: Better for interactivity (hover, click) and accessibility, but too slow for large datasets.
- **Decision**: Use Canvas for rendering, with a transparent overlay div for mouse interaction (hit detection via coordinate math).

### Sampling Algorithm
- **Strategy**: Stratified random sampling across recordings within a dataset
- **Steps**:
  1. Query all recordings in dataset with their ConfirmedRegions
  2. Build an "unconfirmed interval" list per recording (total duration minus confirmed regions)
  3. Randomly sample N segments of configurable length from unconfirmed intervals
  4. Ensure no overlap with existing ConfirmedRegions
  5. Distribute segments across recordings proportionally to their unconfirmed duration

### Export Architecture
- **Small exports** (<100 clips): Synchronous streaming ZIP response
- **Large exports** (100+ clips): Background job with status polling
  - ExportJob model tracks status (queued/processing/completed/failed)
  - Generated files stored temporarily on disk
  - Download link provided when complete
  - Cleanup after configurable TTL (default 24h)

### Explore Search Performance
- **Species search**: Full-text search on Tag.scientific_name and Tag.common_name via PostgreSQL `ILIKE` or `ts_vector`
- **Site aggregation**: Pre-aggregated counts per site via materialized view or cached query
- **Map rendering**: Client-side H3 hexagon rendering using h3-js (same pattern as H3MapPicker)

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Canvas + overlay div for Spiral Plot | Canvas needed for 10K+ data points | SVG too slow for dense heatmaps |
| Background job for large exports | Audio file slicing for 1000+ clips takes minutes | Synchronous timeout for large exports |

## Dependencies

### External Dependencies (from other features)
- **003-annotation**: Annotation model (new VISION model with start_time/end_time on Recording)
- **004-ml-pipeline**: DetectionRun model, ML-generated annotations
- **003 or new**: ConfirmedRegion model (may need to be created in this feature if not yet available)

### Internal Dependencies (within this feature)
- ConfirmedRegion must exist before SamplingReview
- Annotation/DetectionRun data must exist before Explore search, Spiral Plot, and Export
- Explore API must exist before Sharing (shared data appears in Explore)
