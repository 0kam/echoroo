# Research: Data Management Feature

**Date**: 2026-01-16
**Feature Branch**: `002-data-management`

## Overview

This document captures research findings and technical decisions for the data management feature implementation.

---

## 1. H3 Geospatial Indexing

### Decision
Use `h3-py` library for Uber H3 hexagonal grid operations.

### Rationale
- H3 is already used in the legacy codebase (`old/back/src/echoroo/models/site.py`)
- `h3-py` is the official Python binding with full API support
- H3 provides hierarchical spatial indexing with consistent cell shapes
- Resolution 5-15 covers village-level to sub-meter precision

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|-----------------|
| PostGIS geometry | H3 already established in codebase, simpler hex-based queries |
| S2 Geometry | H3 more widely adopted in ecology/biodiversity domains |
| Custom grid | Reinventing the wheel, H3 is battle-tested |

### Implementation Notes
- Store H3 index as string (15-character hex string)
- Calculate coordinate uncertainty from H3 cell edge length
- Use `h3.cell_to_latlng()` for centroid extraction
- Use `h3.cell_to_boundary()` for polygon visualization

---

## 2. Audio File Processing

### Decision
Use `soundfile` library for audio metadata extraction and processing.

### Rationale
- `soundfile` is based on libsndfile, supporting WAV, FLAC, OGG natively
- Fast metadata extraction without loading full audio into memory
- Already available via existing dependencies (torchaudio uses libsndfile)
- Memory-efficient stream processing for large files

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|-----------------|
| pydub | Requires ffmpeg, slower for metadata-only operations |
| scipy.io.wavfile | WAV-only, no FLAC/OGG support |
| torchaudio | Heavier dependency, overkill for metadata extraction |
| audioread | Read-only, limited format support |

### Implementation Notes
```python
import soundfile as sf

# Metadata extraction without loading audio
info = sf.info(path)
duration = info.duration
samplerate = info.samplerate
channels = info.channels
subtype = info.subtype  # e.g., 'PCM_16' for bit depth
```

### MP3 Support
- `soundfile` does not natively support MP3
- Use `mutagen` for MP3 metadata extraction
- For MP3 audio data, use `pydub` or convert to WAV on demand

---

## 3. Spectrogram Generation

### Decision
Use `numpy` + `scipy.signal` for spectrogram generation, with caching strategy.

### Rationale
- Pure Python/numpy implementation is portable and fast
- scipy.signal.spectrogram provides configurable STFT parameters
- No heavy ML framework dependency for basic visualization
- Can be cached to filesystem or Redis

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|-----------------|
| librosa | Large dependency, includes ML features we don't need here |
| torchaudio | Requires PyTorch for simple visualization |
| matplotlib specgram | Tied to plotting, not suitable for API response |

### Implementation Notes
- Generate spectrograms on-demand via API endpoint
- Cache generated spectrograms by recording_id + parameters hash
- Support configurable parameters: n_fft, hop_length, freq_range, colormap
- Return as PNG image or numpy array for frontend rendering
- Consider pre-generating thumbnails for list views

### Caching Strategy
```
/cache/spectrograms/{recording_uuid}/{hash_of_params}.png
```
- Hash includes: n_fft, hop_length, freq_min, freq_max, colormap
- Cache invalidation: delete on recording deletion
- TTL: indefinite (content-addressed caching)

---

## 4. Datetime Pattern Extraction from Filenames

### Decision
Use regex-based pattern matching with user-configurable patterns.

### Rationale
- Legacy codebase uses this approach (`DatasetDatetimePattern` model)
- Flexible enough to handle various recording device naming conventions
- User can specify pattern per dataset

### Common Patterns
| Device | Pattern Example | Regex |
|--------|-----------------|-------|
| AudioMoth | `20240315_143000.WAV` | `(\d{8})_(\d{6})` |
| Wildlife Acoustics | `SITE01_20240315$143000.wav` | `_(\d{8})\$(\d{6})` |
| Generic | `rec_2024-03-15_14-30-00.flac` | `(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})` |

### Implementation Notes
- Store pattern as regex string in dataset
- Store datetime format string for parsing (e.g., `%Y%m%d_%H%M%S`)
- Track parsing status per recording: `pending`, `success`, `failed`
- Provide UI for pattern preview/testing before import

---

## 5. HTTP Range Requests for Audio Streaming

### Decision
Implement HTTP Range header support for efficient audio streaming.

### Rationale
- Required for seek functionality in HTML5 audio element
- Prevents loading entire file into memory
- Standard HTTP feature, well-supported

### Implementation Notes
```python
from fastapi.responses import StreamingResponse

@router.get("/recordings/{id}/audio")
async def stream_audio(
    id: UUID,
    request: Request,
):
    range_header = request.headers.get("range")
    if range_header:
        # Parse range, return 206 Partial Content
        ...
    else:
        # Return full file
        ...
```

### Response Headers
- `Accept-Ranges: bytes`
- `Content-Range: bytes start-end/total`
- `Content-Length: chunk_size`
- Status: 206 Partial Content

---

## 6. Ultrasonic Recording Playback

### Decision
Resample ultrasonic recordings (>48kHz) to 48kHz for browser playback.

### Rationale
- Web Audio API supports max 96kHz but browsers typically limit to 48kHz
- Original sample rate preserved for spectrogram generation
- Time expansion factor applied during resampling

### Implementation Notes
```python
import scipy.signal

def resample_for_playback(audio, original_sr, time_expansion=1.0):
    """Resample audio for browser playback."""
    target_sr = 48000
    effective_sr = original_sr / time_expansion

    if effective_sr > target_sr:
        # Downsample
        audio = scipy.signal.resample_poly(audio, target_sr, int(effective_sr))

    return audio, min(target_sr, int(effective_sr))
```

### Playback Speed
- Speed range: 0.1x to 3x
- Output sample rate clamped to 8kHz-96kHz
- Speed < 1x for ultrasonic makes sounds audible

---

## 7. CamtrapDP Export Format

### Decision
Implement CamtrapDP export as specified in the feature spec.

### Rationale
- International standard for biodiversity observation data
- Enables interoperability with other tools
- Well-documented schema

### Implementation Notes
- Use streaming ZIP generation for large exports
- CSV generation with Python `csv` module
- Audio files stored in `Audio/` directory with original structure
- Calculate `coordinateUncertainty` from H3 cell geometry

### Streaming Export
```python
import zipfile
from io import BytesIO

async def export_dataset_camtrapdp(dataset_id: UUID, include_audio: bool):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as zf:
        # Add CSVs (compressed)
        zf.writestr('deployments.csv', generate_deployments_csv(dataset_id))
        zf.writestr('media.csv', generate_media_csv(dataset_id))

        if include_audio:
            # Stream audio files without loading all into memory
            for recording in get_recordings(dataset_id):
                zf.write(recording.path, f'Audio/{recording.relative_path}')

    return buffer
```

---

## 8. Database Schema Decisions

### Decision
Use UUID primary keys for new entities, matching existing pattern.

### Rationale
- Consistent with 001-administration entities (Project, User, etc.)
- Better for distributed systems and API exposure
- Existing `UUIDMixin` available

### Key Relationships
```
Project (existing)
  └── Site (new) [1:N, via project_id FK]
        └── Dataset (new) [1:N, via site_id FK]
              ├── Recording (new) [1:N, via dataset_id FK]
              │     └── Clip (new) [1:N, via recording_id FK]
              ├── Recorder (existing) [N:1, optional FK]
              └── License (existing) [N:1, optional FK]
```

### Migration Strategy
- Create new tables in single migration
- Add foreign keys to existing tables (Recorder, License, Project)
- Use `ondelete="SET NULL"` for optional references
- Use `ondelete="CASCADE"` for required parent-child relationships

---

## 9. Frontend Map Library

### Decision
Use Mapbox GL JS with H3 layer support for site selection.

### Rationale
- Mapbox GL JS is industry standard for web maps
- Native support for H3 hexagons via `h3-js`
- Good Svelte integration via `svelte-mapbox`

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|-----------------|
| Leaflet | Less performant for large datasets, dated API |
| OpenLayers | More complex, overkill for our use case |
| deck.gl | Heavy, more suitable for large-scale visualization |

### Implementation Notes
- Use `h3-js` for client-side H3 operations
- Render hexagons as GeoJSON polygons
- Click-to-select hex cells
- Resolution slider for zoom levels

---

## 10. Audio Player Component

### Decision
Build custom audio player with WaveSurfer.js for spectrogram sync.

### Rationale
- WaveSurfer.js provides spectrogram plugin
- Customizable UI to match Echoroo design
- Already listed in ARCHITECTURE.md

### Features Required
- Play/pause with keyboard shortcut (space)
- Playback speed control (0.1x - 3x)
- Click-to-seek on spectrogram
- Auto-scroll spectrogram during playback
- Time expansion display for ultrasonic

---

## Summary of Dependencies

### Backend (to add to pyproject.toml)
```toml
h3 = "^4.0.0"
soundfile = "^0.12.0"
mutagen = "^1.47.0"  # For MP3 metadata
```

### Frontend (to add to package.json)
```json
"h3-js": "^4.0.0",
"mapbox-gl": "^3.0.0",
"wavesurfer.js": "^7.0.0"
```

---

## Unresolved Questions

None - all technical decisions made.
