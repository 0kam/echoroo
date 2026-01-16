# Data Model: Data Management Feature

**Date**: 2026-01-16
**Feature Branch**: `002-data-management`

## Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXISTING ENTITIES                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  Project (UUID)          Recorder (String ID)       License (String ID)     │
│  - name                  - manufacturer             - name                   │
│  - description           - recorder_name            - short_name             │
│  - owner_id              - version                  - url                    │
│  - visibility                                       - description            │
└─────────────────────────────────────────────────────────────────────────────┘
         │ 1                      │ 0..1                    │ 0..1
         │                        │                         │
         ▼ N                      │                         │
┌─────────────────┐               │                         │
│      Site       │               │                         │
├─────────────────┤               │                         │
│ PK id: UUID     │               │                         │
│ FK project_id   │───────────────┘                         │
│    name         │                                         │
│    h3_index     │                                         │
│    created_at   │                                         │
│    updated_at   │                                         │
└─────────────────┘                                         │
         │ 1                                                │
         │                                                  │
         ▼ N                                                │
┌─────────────────────────────────────────────────────────────┐
│                         Dataset                              │
├─────────────────────────────────────────────────────────────┤
│ PK id: UUID                                                  │
│ FK site_id: UUID (required)                                  │
│ FK project_id: UUID (required, denormalized for queries)     │
│ FK recorder_id: String (optional) ─────────────────────────┘ │
│ FK license_id: String (optional) ──────────────────────────┘ │
│ FK created_by_id: UUID (required)                            │
│    name: String (unique per project)                         │
│    description: Text (optional)                              │
│    audio_dir: String (relative path)                         │
│    visibility: Enum (private, public)                        │
│    status: Enum (pending, scanning, processing, completed,   │
│            failed)                                           │
│    doi: String (optional)                                    │
│    gain: Float (optional, dB)                                │
│    note: Text (optional, internal)                           │
│    datetime_pattern: String (optional, regex)                │
│    datetime_format: String (optional, strftime)              │
│    total_files: Integer                                      │
│    processed_files: Integer                                  │
│    processing_error: Text (optional)                         │
│    created_at: DateTime                                      │
│    updated_at: DateTime                                      │
└─────────────────────────────────────────────────────────────┘
         │ 1
         │
         ▼ N
┌─────────────────────────────────────────────────────────────┐
│                        Recording                             │
├─────────────────────────────────────────────────────────────┤
│ PK id: UUID                                                  │
│ FK dataset_id: UUID (required)                               │
│    filename: String                                          │
│    path: String (relative to audio_dir, unique per dataset)  │
│    hash: String (MD5, for deduplication)                     │
│    duration: Float (seconds)                                 │
│    samplerate: Integer (Hz)                                  │
│    channels: Integer                                         │
│    bit_depth: Integer (optional)                             │
│    datetime: DateTime (optional, parsed from filename)       │
│    datetime_parse_status: Enum (pending, success, failed)    │
│    datetime_parse_error: Text (optional)                     │
│    time_expansion: Float (default 1.0)                       │
│    note: Text (optional)                                     │
│    created_at: DateTime                                      │
│    updated_at: DateTime                                      │
└─────────────────────────────────────────────────────────────┘
         │ 1
         │
         ▼ N
┌─────────────────────────────────────────────────────────────┐
│                          Clip                                │
├─────────────────────────────────────────────────────────────┤
│ PK id: UUID                                                  │
│ FK recording_id: UUID (required)                             │
│    start_time: Float (seconds)                               │
│    end_time: Float (seconds)                                 │
│    note: Text (optional)                                     │
│    created_at: DateTime                                      │
│    updated_at: DateTime                                      │
│ UNIQUE(recording_id, start_time, end_time)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Entity Definitions

### Site

Geographic location for field recordings, defined by an Uber H3 hexagonal cell.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | Unique identifier |
| `project_id` | UUID | FK projects.id, NOT NULL, ON DELETE CASCADE | Parent project |
| `name` | String(200) | NOT NULL | Human-readable site name |
| `h3_index` | String(32) | NOT NULL, INDEX | Uber H3 cell identifier (resolution 5-15) |
| `created_at` | DateTime | NOT NULL, default now() | Creation timestamp |
| `updated_at` | DateTime | NOT NULL, auto-update | Last update timestamp |

**Constraints:**
- `UNIQUE(project_id, name)` - Site names unique within project
- `UNIQUE(project_id, h3_index)` - H3 index unique within project

**Relationships:**
- `project` → Project (many-to-one)
- `datasets` → Dataset[] (one-to-many)

**Validation Rules:**
- `name`: 1-200 characters, trimmed
- `h3_index`: Valid H3 index string (validated via h3-py)
- H3 resolution must be between 5-15

---

### Dataset

Collection of audio recordings imported from a directory.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | Unique identifier |
| `site_id` | UUID | FK sites.id, NOT NULL, ON DELETE CASCADE | Parent site (required) |
| `project_id` | UUID | FK projects.id, NOT NULL, ON DELETE CASCADE | Parent project (denormalized) |
| `recorder_id` | String(50) | FK recorders.id, ON DELETE SET NULL | Recording device |
| `license_id` | String(50) | FK licenses.id, ON DELETE SET NULL | Content license |
| `created_by_id` | UUID | FK users.id, NOT NULL | User who created dataset |
| `name` | String(200) | NOT NULL | Dataset name |
| `description` | Text | | Optional description |
| `audio_dir` | String(500) | NOT NULL | Relative path to audio directory |
| `visibility` | Enum | NOT NULL, default 'private' | private, public |
| `status` | Enum | NOT NULL, default 'pending' | pending, scanning, processing, completed, failed |
| `doi` | String(255) | | Digital Object Identifier |
| `gain` | Float | | Recording gain in dB |
| `note` | Text | | Internal notes |
| `datetime_pattern` | String(500) | | Regex for datetime extraction |
| `datetime_format` | String(100) | | strftime format string |
| `total_files` | Integer | NOT NULL, default 0 | Total audio files discovered |
| `processed_files` | Integer | NOT NULL, default 0 | Files successfully imported |
| `processing_error` | Text | | Error message if failed |
| `created_at` | DateTime | NOT NULL, default now() | Creation timestamp |
| `updated_at` | DateTime | NOT NULL, auto-update | Last update timestamp |

**Constraints:**
- `UNIQUE(project_id, name)` - Dataset names unique within project

**Relationships:**
- `site` → Site (many-to-one)
- `project` → Project (many-to-one)
- `recorder` → Recorder (many-to-one, optional)
- `license` → License (many-to-one, optional)
- `created_by` → User (many-to-one)
- `recordings` → Recording[] (one-to-many)

**Validation Rules:**
- `name`: 1-200 characters, trimmed
- `audio_dir`: Valid relative path, no ".." traversal
- `gain`: -100 to +100 dB range
- `doi`: Valid DOI format if provided (10.xxxx/...)
- `visibility`: Must be 'private' or 'public'
- `status`: Must be valid status enum value

**State Transitions:**
```
pending → scanning → processing → completed
                  ↓              ↓
                  └──→ failed ←──┘
```

---

### Recording

Single audio file with extracted metadata.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | Unique identifier |
| `dataset_id` | UUID | FK datasets.id, NOT NULL, ON DELETE CASCADE | Parent dataset |
| `filename` | String(255) | NOT NULL | Original filename |
| `path` | String(500) | NOT NULL | Relative path within audio_dir |
| `hash` | String(64) | NOT NULL, INDEX | MD5 hash for deduplication |
| `duration` | Float | NOT NULL | Duration in seconds |
| `samplerate` | Integer | NOT NULL | Sample rate in Hz |
| `channels` | Integer | NOT NULL | Number of audio channels |
| `bit_depth` | Integer | | Bits per sample (16, 24, 32) |
| `datetime` | DateTime(tz) | | Recording date/time (parsed) |
| `datetime_parse_status` | Enum | NOT NULL, default 'pending' | pending, success, failed |
| `datetime_parse_error` | Text | | Parse error details |
| `time_expansion` | Float | NOT NULL, default 1.0 | Time expansion factor |
| `note` | Text | | User notes |
| `created_at` | DateTime | NOT NULL, default now() | Import timestamp |
| `updated_at` | DateTime | NOT NULL, auto-update | Last update timestamp |

**Constraints:**
- `UNIQUE(dataset_id, path)` - Path unique within dataset
- `INDEX(dataset_id, datetime)` - For time-based queries

**Relationships:**
- `dataset` → Dataset (many-to-one)
- `clips` → Clip[] (one-to-many)

**Validation Rules:**
- `filename`: 1-255 characters
- `path`: Valid relative path, no ".." traversal
- `duration`: > 0
- `samplerate`: 1-384000 Hz (covers ultrasonic)
- `channels`: 1-8
- `bit_depth`: 8, 16, 24, or 32
- `time_expansion`: 0.1-100.0

**Computed Properties:**
- `effective_duration` = duration * time_expansion
- `file_path` = dataset.audio_dir / path

---

### Clip

Time segment within a recording.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | Unique identifier |
| `recording_id` | UUID | FK recordings.id, NOT NULL, ON DELETE CASCADE | Parent recording |
| `start_time` | Float | NOT NULL | Start time in seconds |
| `end_time` | Float | NOT NULL | End time in seconds |
| `note` | Text | | User notes |
| `created_at` | DateTime | NOT NULL, default now() | Creation timestamp |
| `updated_at` | DateTime | NOT NULL, auto-update | Last update timestamp |

**Constraints:**
- `UNIQUE(recording_id, start_time, end_time)` - No duplicate clips
- `CHECK(end_time > start_time)` - Valid time range
- `INDEX(recording_id)` - For parent lookups

**Relationships:**
- `recording` → Recording (many-to-one)

**Validation Rules:**
- `start_time`: >= 0
- `end_time`: > start_time
- `end_time`: <= recording.duration (validated at service layer)

**Computed Properties:**
- `duration` = end_time - start_time

---

## Enum Definitions

### DatasetVisibility
```python
class DatasetVisibility(str, Enum):
    PRIVATE = "private"  # Only owner can access
    PUBLIC = "public"    # All authenticated users can view
```

### DatasetStatus
```python
class DatasetStatus(str, Enum):
    PENDING = "pending"        # Created, not yet scanning
    SCANNING = "scanning"      # Discovering audio files
    PROCESSING = "processing"  # Importing recordings
    COMPLETED = "completed"    # Import finished successfully
    FAILED = "failed"          # Import failed with error
```

### DatetimeParseStatus
```python
class DatetimeParseStatus(str, Enum):
    PENDING = "pending"  # Not yet attempted
    SUCCESS = "success"  # Parsed successfully
    FAILED = "failed"    # Parse failed
```

---

## Index Strategy

### Site
- `ix_sites_project_id` - Filter by project
- `ix_sites_h3_index` - Geospatial queries

### Dataset
- `ix_datasets_project_id` - Filter by project
- `ix_datasets_site_id` - Filter by site
- `ix_datasets_status` - Filter by import status
- `ix_datasets_visibility` - Filter by visibility

### Recording
- `ix_recordings_dataset_id` - Filter by dataset
- `ix_recordings_hash` - Deduplication lookup
- `ix_recordings_datetime` - Time-based queries
- `ix_recordings_dataset_id_datetime` - Compound for date filtering

### Clip
- `ix_clips_recording_id` - Filter by recording

---

## Migration Plan

### Migration 001: Create Sites Table
```sql
CREATE TABLE sites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    h3_index VARCHAR(32) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, name),
    UNIQUE(project_id, h3_index)
);
CREATE INDEX ix_sites_project_id ON sites(project_id);
CREATE INDEX ix_sites_h3_index ON sites(h3_index);
```

### Migration 002: Create Datasets Table
```sql
CREATE TYPE dataset_visibility AS ENUM ('private', 'public');
CREATE TYPE dataset_status AS ENUM ('pending', 'scanning', 'processing', 'completed', 'failed');

CREATE TABLE datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    recorder_id VARCHAR(50) REFERENCES recorders(id) ON DELETE SET NULL,
    license_id VARCHAR(50) REFERENCES licenses(id) ON DELETE SET NULL,
    created_by_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    audio_dir VARCHAR(500) NOT NULL,
    visibility dataset_visibility NOT NULL DEFAULT 'private',
    status dataset_status NOT NULL DEFAULT 'pending',
    doi VARCHAR(255),
    gain FLOAT,
    note TEXT,
    datetime_pattern VARCHAR(500),
    datetime_format VARCHAR(100),
    total_files INTEGER NOT NULL DEFAULT 0,
    processed_files INTEGER NOT NULL DEFAULT 0,
    processing_error TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, name)
);
CREATE INDEX ix_datasets_project_id ON datasets(project_id);
CREATE INDEX ix_datasets_site_id ON datasets(site_id);
CREATE INDEX ix_datasets_status ON datasets(status);
CREATE INDEX ix_datasets_visibility ON datasets(visibility);
```

### Migration 003: Create Recordings Table
```sql
CREATE TYPE datetime_parse_status AS ENUM ('pending', 'success', 'failed');

CREATE TABLE recordings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    path VARCHAR(500) NOT NULL,
    hash VARCHAR(64) NOT NULL,
    duration FLOAT NOT NULL,
    samplerate INTEGER NOT NULL,
    channels INTEGER NOT NULL,
    bit_depth INTEGER,
    datetime TIMESTAMP WITH TIME ZONE,
    datetime_parse_status datetime_parse_status NOT NULL DEFAULT 'pending',
    datetime_parse_error TEXT,
    time_expansion FLOAT NOT NULL DEFAULT 1.0,
    note TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(dataset_id, path)
);
CREATE INDEX ix_recordings_dataset_id ON recordings(dataset_id);
CREATE INDEX ix_recordings_hash ON recordings(hash);
CREATE INDEX ix_recordings_datetime ON recordings(datetime);
CREATE INDEX ix_recordings_dataset_id_datetime ON recordings(dataset_id, datetime);
```

### Migration 004: Create Clips Table
```sql
CREATE TABLE clips (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recording_id UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    start_time FLOAT NOT NULL,
    end_time FLOAT NOT NULL,
    note TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(recording_id, start_time, end_time),
    CHECK(end_time > start_time)
);
CREATE INDEX ix_clips_recording_id ON clips(recording_id);
```

---

## Query Patterns

### Common Queries

1. **List sites for project**
```sql
SELECT * FROM sites WHERE project_id = ? ORDER BY name;
```

2. **List datasets for site with stats**
```sql
SELECT d.*,
       COUNT(r.id) as recording_count,
       SUM(r.duration) as total_duration,
       MIN(r.datetime) as start_date,
       MAX(r.datetime) as end_date
FROM datasets d
LEFT JOIN recordings r ON r.dataset_id = d.id
WHERE d.site_id = ?
GROUP BY d.id
ORDER BY d.created_at DESC;
```

3. **List recordings with pagination and filtering**
```sql
SELECT * FROM recordings
WHERE dataset_id = ?
  AND (datetime >= ? OR ? IS NULL)
  AND (datetime <= ? OR ? IS NULL)
ORDER BY datetime DESC NULLS LAST
LIMIT ? OFFSET ?;
```

4. **Search recordings across project**
```sql
SELECT r.*, d.name as dataset_name, s.name as site_name
FROM recordings r
JOIN datasets d ON d.id = r.dataset_id
JOIN sites s ON s.id = d.site_id
WHERE d.project_id = ?
  AND (r.datetime BETWEEN ? AND ?)
ORDER BY r.datetime;
```

5. **Get clips for recording**
```sql
SELECT * FROM clips
WHERE recording_id = ?
ORDER BY start_time;
```

---

## Data Integrity Rules

1. **Cascading Deletes:**
   - Delete Project → Delete Sites → Delete Datasets → Delete Recordings → Delete Clips
   - Delete Site → Delete Datasets → Delete Recordings → Delete Clips
   - Delete Dataset → Delete Recordings → Delete Clips
   - Delete Recording → Delete Clips

2. **Optional References:**
   - Delete Recorder → Set Dataset.recorder_id to NULL
   - Delete License → Set Dataset.license_id to NULL

3. **Audit Trail:**
   - All entities have `created_at` and `updated_at` timestamps
   - Dataset tracks `created_by_id` for ownership
