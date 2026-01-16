# Quickstart: Data Management Feature

**Branch**: `002-data-management`
**Date**: 2026-01-16

## Prerequisites

1. Development environment running (`./scripts/docker.sh dev`)
2. 001-administration feature implemented (Projects, Users, Licenses, Recorders)
3. Audio files for testing (WAV, FLAC, MP3, or OGG)

## Setup Steps

### 1. Install New Dependencies

**Backend** (apps/api/pyproject.toml):
```toml
[project.dependencies]
# ... existing deps ...
h3 = "^4.0.0"
soundfile = "^0.12.0"
mutagen = "^1.47.0"
```

**Frontend** (apps/web/package.json):
```json
{
  "dependencies": {
    "h3-js": "^4.0.0",
    "mapbox-gl": "^3.0.0",
    "wavesurfer.js": "^7.0.0"
  }
}
```

### 2. Run Database Migrations

```bash
cd apps/api
uv run alembic upgrade head
```

### 3. Verify API Endpoints

After implementation, verify the following endpoints work:

**Sites:**
- `GET /api/v1/projects/{id}/sites` - List sites
- `POST /api/v1/projects/{id}/sites` - Create site
- `GET /api/v1/projects/{id}/sites/{id}` - Get site details
- `PATCH /api/v1/projects/{id}/sites/{id}` - Update site
- `DELETE /api/v1/projects/{id}/sites/{id}` - Delete site

**Datasets:**
- `GET /api/v1/projects/{id}/datasets` - List datasets
- `POST /api/v1/projects/{id}/datasets` - Create dataset
- `POST /api/v1/projects/{id}/datasets/{id}/import` - Start import
- `GET /api/v1/projects/{id}/datasets/{id}/statistics` - Get stats

**Recordings:**
- `GET /api/v1/projects/{id}/datasets/{id}/recordings` - List recordings
- `GET /api/v1/recordings/{id}` - Get recording details
- `GET /api/v1/recordings/{id}/audio` - Stream audio
- `GET /api/v1/recordings/{id}/spectrogram` - Get spectrogram

**Clips:**
- `GET /api/v1/recordings/{id}/clips` - List clips
- `POST /api/v1/recordings/{id}/clips` - Create clip
- `POST /api/v1/recordings/{id}/clips/generate` - Auto-generate clips

## Quick Test Workflow

### 1. Create a Site

```bash
curl -X POST http://localhost:8000/api/v1/projects/{project_id}/sites \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Site",
    "h3_index": "8a2a100d2c57fff"
  }'
```

### 2. Create a Dataset

```bash
curl -X POST http://localhost:8000/api/v1/projects/{project_id}/datasets \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "site_id": "{site_id}",
    "name": "Test Dataset",
    "audio_dir": "test_audio",
    "datetime_pattern": "^(\\d{8})_(\\d{6})\\.",
    "datetime_format": "%Y%m%d_%H%M%S"
  }'
```

### 3. Start Import

```bash
curl -X POST http://localhost:8000/api/v1/projects/{project_id}/datasets/{dataset_id}/import \
  -H "Authorization: Bearer {token}"
```

### 4. View Recordings

```bash
curl http://localhost:8000/api/v1/projects/{project_id}/datasets/{dataset_id}/recordings \
  -H "Authorization: Bearer {token}"
```

### 5. Get Spectrogram

```bash
curl "http://localhost:8000/api/v1/recordings/{recording_id}/spectrogram?colormap=viridis" \
  -H "Authorization: Bearer {token}" \
  --output spectrogram.png
```

## Key Files to Implement

### Backend (Priority Order)

1. **Models** (apps/api/echoroo/models/)
   - `site.py` - Site model
   - `dataset.py` - Dataset model with status tracking
   - `recording.py` - Recording model
   - `clip.py` - Clip model
   - `note.py` - Note model

2. **Schemas** (apps/api/echoroo/schemas/)
   - `site.py` - Site Pydantic schemas
   - `dataset.py` - Dataset Pydantic schemas
   - `recording.py` - Recording Pydantic schemas
   - `clip.py` - Clip Pydantic schemas

3. **Repositories** (apps/api/echoroo/repositories/)
   - `site.py` - Site data access
   - `dataset.py` - Dataset data access
   - `recording.py` - Recording data access
   - `clip.py` - Clip data access

4. **Services** (apps/api/echoroo/services/)
   - `site.py` - Site business logic
   - `dataset.py` - Dataset business logic + import
   - `recording.py` - Recording business logic
   - `clip.py` - Clip business logic
   - `audio.py` - Audio processing utilities

5. **API Endpoints** (apps/api/echoroo/api/v1/)
   - `sites.py` - Site endpoints
   - `datasets.py` - Dataset endpoints
   - `recordings.py` - Recording endpoints
   - `clips.py` - Clip endpoints

6. **Workers** (apps/api/echoroo/workers/)
   - `import_task.py` - Celery task for async import

### Frontend (Priority Order)

1. **API Clients** (apps/web/src/lib/api/)
   - `sites.ts` - Site API
   - `datasets.ts` - Dataset API
   - `recordings.ts` - Update existing
   - `clips.ts` - Clip API

2. **Types** (apps/web/src/lib/types/)
   - `data.ts` - TypeScript types

3. **Components** (apps/web/src/lib/components/)
   - `map/H3Picker.svelte` - H3 hex picker
   - `audio/AudioPlayer.svelte` - Audio player with spectrogram
   - `data/RecordingList.svelte` - Recording list view

4. **Pages** (apps/web/src/routes/(app)/projects/[id]/)
   - `sites/+page.svelte` - Site management
   - `datasets/+page.svelte` - Dataset management
   - `recordings/+page.svelte` - Recording browser

## Type Checking

After implementation, run type checks:

```bash
# Backend
cd apps/api
uv run mypy .

# Frontend
cd apps/web
npm run check
```

## Testing

Run tests after implementation:

```bash
# Backend
cd apps/api
uv run pytest tests/contract/test_sites.py -v
uv run pytest tests/contract/test_datasets.py -v
uv run pytest tests/contract/test_recordings.py -v
uv run pytest tests/contract/test_clips.py -v

# Frontend
cd apps/web
npm run test
```

## Common Issues

### H3 Index Validation
Use `h3.h3_is_valid()` to validate H3 indexes before storing.

### Audio File Access
Ensure `AUDIO_ROOT` environment variable is set to the base audio directory.

### Large File Uploads
Configure Nginx/FastAPI for streaming uploads. Don't load entire files into memory.

### Spectrogram Caching
Implement caching to avoid regenerating spectrograms on every request.

## Environment Variables

Add to `.env`:
```
AUDIO_ROOT=/path/to/audio/files
SPECTROGRAM_CACHE_DIR=/path/to/cache
```
