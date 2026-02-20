# Data Model: Annotation Feature

**Date**: 2026-02-19
**Feature Branch**: `003-annotation`

## Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXISTING ENTITIES                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  Project (UUID)      User (UUID)       Clip (UUID)       Dataset (UUID)     │
│  - name              - username        - recording_id     - project_id      │
│  - description       - email           - start_time       - name            │
│  - owner_id                            - end_time                           │
└─────────────────────────────────────────────────────────────────────────────┘
         │ 1                │ 1                │ 1               │ N
         │                  │                  │                 │
         ▼ N                │                  │                 │
┌─────────────────────┐     │                  │                 │
│  AnnotationProject  │     │                  │                 │
├─────────────────────┤     │                  │                 │
│ PK id: UUID         │     │                  │                 │
│ FK project_id       │─────┘                  │                 │
│ FK created_by_id    │                        │                 │
│    name             │                        │                 │
│    description      │                        │                 │
│    instructions     │                        │                 │
│    visibility       │                        │                 │
│    created_at       │                        │                 │
│    updated_at       │                        │                 │
└─────────────────────┘                        │                 │
    │ N          │ 1                           │                 │
    │            │                             │                 │
    │            ▼ N                           │                 │
    │   ┌──────────────────────────┐           │                 │
    │   │AnnotationProjectDataset │           │                 │
    │   ├──────────────────────────┤           │                 │
    │   │ FK annotation_project_id │           │                 │
    │   │ FK dataset_id            │───────────┼─────────────────┘
    │   └──────────────────────────┘           │
    │                                          │
    ▼ N                                        │
┌─────────────────────┐                        │
│   AnnotationTask    │                        │
├─────────────────────┤                        │
│ PK id: UUID         │                        │
│ FK annotation_      │                        │
│    project_id       │                        │
│ FK clip_id          │────────────────────────┘
│ FK assigned_to_id   │
│    status           │
│    priority         │
│    created_at       │
│    updated_at       │
└─────────────────────┘
         │ 1
         │
         ▼ 0..1
┌─────────────────────┐
│   ClipAnnotation    │
├─────────────────────┤
│ PK id: UUID         │
│ FK task_id          │
│ FK clip_id          │
│ FK created_by_id    │
│    review_status    │
│ FK reviewed_by_id   │
│    reviewed_at      │
│    created_at       │
│    updated_at       │
└─────────────────────┘
    │ N          │ N
    │            │
    │            ▼ N
    │   ┌─────────────────────────┐
    │   │ SoundEventAnnotation    │
    │   ├─────────────────────────┤
    │   │ PK id: UUID             │
    │   │ FK clip_annotation_id   │
    │   │ FK created_by_id        │
    │   │    geometry             │
    │   │    source               │
    │   │    confidence           │
    │   │    created_at           │
    │   │    updated_at           │
    │   └─────────────────────────┘
    │            │ N
    │            │
    │            ▼ N (via sound_event_annotation_tag)
    │   ┌─────────────────────┐
    │   │        Tag          │
    │   ├─────────────────────┤
    │   │ PK id: UUID         │
    │   │ FK project_id       │
    │   │ FK parent_id        │──→ self (hierarchy)
    │   │    name             │
    │   │    category         │
    │   │    gbif_taxon_key   │
    │   │    scientific_name  │
    │   │    common_name      │
    │   │    created_at       │
    │   │    updated_at       │
    │   └─────────────────────┘
    │
    ▼ N (via clip_annotation_tag)
    (Tag - same entity above)

┌─────────────────────┐
│        Note         │
├─────────────────────┤
│ PK id: UUID         │
│ FK created_by_id    │
│ FK clip_annotation_id (nullable) │
│ FK sound_event_annotation_id (nullable) │
│    content          │
│    is_review        │
│    created_at       │
│    updated_at       │
└─────────────────────┘
```

---

## Entity Definitions

### Tag

Classification label for annotations. Supports hierarchical structure and GBIF integration.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | Unique identifier |
| `project_id` | UUID | FK projects.id, NOT NULL, ON DELETE CASCADE | Parent project |
| `parent_id` | UUID | FK tags.id, ON DELETE SET NULL | Parent tag for hierarchy |
| `name` | String(200) | NOT NULL | Display name |
| `category` | Enum | NOT NULL | species, sound_type, quality |
| `gbif_taxon_key` | Integer | nullable | GBIF Backbone Taxonomy key |
| `scientific_name` | String(300) | nullable | Scientific name from GBIF |
| `common_name` | String(300) | nullable | Common/vernacular name |
| `created_at` | DateTime | NOT NULL, default now() | Creation timestamp |
| `updated_at` | DateTime | NOT NULL, auto-update | Last update timestamp |

**Constraints:**
- `UNIQUE(project_id, name, category)` - Tag names unique within project+category

**Relationships:**
- `project` → Project (many-to-one)
- `parent` → Tag (self-referential, many-to-one)
- `children` → Tag[] (one-to-many)

**Validation Rules:**
- `name`: 1-200 characters, trimmed
- `category`: Must be valid TagCategory enum
- `gbif_taxon_key`: Positive integer if provided

---

### AnnotationProject

Manages an annotation workflow targeting specific species or sound types.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | Unique identifier |
| `project_id` | UUID | FK projects.id, NOT NULL, ON DELETE CASCADE | Parent project |
| `created_by_id` | UUID | FK users.id, NOT NULL | Creator |
| `name` | String(200) | NOT NULL | Project name |
| `description` | Text | nullable | Description |
| `instructions` | Text | nullable | Annotation guidelines for annotators |
| `visibility` | Enum | NOT NULL, default 'private' | private, public |
| `created_at` | DateTime | NOT NULL, default now() | Creation timestamp |
| `updated_at` | DateTime | NOT NULL, auto-update | Last update timestamp |

**Constraints:**
- `UNIQUE(project_id, name)` - Name unique within parent project

**Relationships:**
- `project` → Project (many-to-one)
- `created_by` → User (many-to-one)
- `datasets` → Dataset[] (many-to-many via annotation_project_datasets)
- `tags` → Tag[] (many-to-many via annotation_project_tags)
- `tasks` → AnnotationTask[] (one-to-many)

**Validation Rules:**
- `name`: 1-200 characters, trimmed

---

### AnnotationProjectDataset (Association Table)

Links annotation projects to datasets.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `annotation_project_id` | UUID | FK, PK, ON DELETE CASCADE | Annotation project |
| `dataset_id` | UUID | FK, PK, ON DELETE CASCADE | Dataset |

---

### AnnotationProjectTag (Association Table)

Links annotation projects to target tags.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `annotation_project_id` | UUID | FK, PK, ON DELETE CASCADE | Annotation project |
| `tag_id` | UUID | FK, PK, ON DELETE CASCADE | Target tag |

---

### AnnotationTask

Individual annotation work unit linked to a clip.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | Unique identifier |
| `annotation_project_id` | UUID | FK annotation_projects.id, NOT NULL, ON DELETE CASCADE | Parent project |
| `clip_id` | UUID | FK clips.id, NOT NULL, ON DELETE CASCADE | Target clip |
| `assigned_to_id` | UUID | FK users.id, ON DELETE SET NULL | Assigned annotator |
| `status` | Enum | NOT NULL, default 'pending' | Task status |
| `priority` | Integer | NOT NULL, default 0 | Priority (higher = more urgent) |
| `created_at` | DateTime | NOT NULL, default now() | Creation timestamp |
| `updated_at` | DateTime | NOT NULL, auto-update | Last update timestamp |

**Constraints:**
- `UNIQUE(annotation_project_id, clip_id)` - One task per clip per project
- `INDEX(annotation_project_id, status)` - For filtered task lists

**Relationships:**
- `annotation_project` → AnnotationProject (many-to-one)
- `clip` → Clip (many-to-one)
- `assigned_to` → User (many-to-one, optional)
- `clip_annotation` → ClipAnnotation (one-to-one, optional)

**Validation Rules:**
- `priority`: 0-100
- `status`: Must be valid TaskStatus enum

**State Transitions:**
```
pending → in_progress → completed
pending → in_progress → review_pending → completed
                     ↓
               review_pending → in_progress (rejected, re-work)
```

---

### ClipAnnotation

Annotation result for a clip (created when annotator works on a task).

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | Unique identifier |
| `task_id` | UUID | FK annotation_tasks.id, NOT NULL, UNIQUE, ON DELETE CASCADE | Parent task |
| `clip_id` | UUID | FK clips.id, NOT NULL, ON DELETE CASCADE | Annotated clip |
| `created_by_id` | UUID | FK users.id, NOT NULL | Annotator |
| `review_status` | Enum | NOT NULL, default 'unreviewed' | Review state |
| `reviewed_by_id` | UUID | FK users.id, ON DELETE SET NULL | Reviewer |
| `reviewed_at` | DateTime | nullable | Review timestamp |
| `created_at` | DateTime | NOT NULL, default now() | Creation timestamp |
| `updated_at` | DateTime | NOT NULL, auto-update | Last update timestamp |

**Constraints:**
- `UNIQUE(task_id)` - One annotation per task

**Relationships:**
- `task` → AnnotationTask (one-to-one)
- `clip` → Clip (many-to-one)
- `created_by` → User (many-to-one)
- `reviewed_by` → User (many-to-one, optional)
- `tags` → Tag[] (many-to-many via clip_annotation_tags)
- `sound_events` → SoundEventAnnotation[] (one-to-many)
- `notes` → Note[] (one-to-many)

---

### ClipAnnotationTag (Association Table)

Clip-level tags (presence/absence classification).

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `clip_annotation_id` | UUID | FK, PK, ON DELETE CASCADE | Clip annotation |
| `tag_id` | UUID | FK, PK, ON DELETE CASCADE | Tag |

---

### SoundEventAnnotation

Fine-grained annotation of a sound event within a clip.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | Unique identifier |
| `clip_annotation_id` | UUID | FK clip_annotations.id, NOT NULL, ON DELETE CASCADE | Parent annotation |
| `created_by_id` | UUID | FK users.id, NOT NULL | Creator |
| `geometry` | JSONB | NOT NULL | Geometry data (BoundingBox or TimeInterval) |
| `source` | Enum | NOT NULL, default 'human' | human or model |
| `confidence` | Float | nullable, 0.0-1.0 | Confidence score |
| `created_at` | DateTime | NOT NULL, default now() | Creation timestamp |
| `updated_at` | DateTime | NOT NULL, auto-update | Last update timestamp |

**Relationships:**
- `clip_annotation` → ClipAnnotation (many-to-one)
- `created_by` → User (many-to-one)
- `tags` → Tag[] (many-to-many via sound_event_annotation_tags)
- `notes` → Note[] (one-to-many)

**Validation Rules:**
- `geometry`: Must be valid geometry JSON: `{"type": "BoundingBox", "coordinates": [t1, f1, t2, f2]}` or `{"type": "TimeInterval", "coordinates": [t1, t2]}`
- `confidence`: 0.0-1.0 if provided
- `source`: Must be AnnotationSource enum

---

### SoundEventAnnotationTag (Association Table)

Tags for sound event annotations.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `sound_event_annotation_id` | UUID | FK, PK, ON DELETE CASCADE | Sound event annotation |
| `tag_id` | UUID | FK, PK, ON DELETE CASCADE | Tag |

---

### Note

Comments on annotations, supporting review feedback.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK, default uuid4 | Unique identifier |
| `created_by_id` | UUID | FK users.id, NOT NULL | Author |
| `clip_annotation_id` | UUID | FK clip_annotations.id, ON DELETE CASCADE | nullable |
| `sound_event_annotation_id` | UUID | FK sound_event_annotations.id, ON DELETE CASCADE | nullable |
| `content` | Text | NOT NULL | Note content |
| `is_review` | Boolean | NOT NULL, default false | Whether this is review feedback |
| `created_at` | DateTime | NOT NULL, default now() | Creation timestamp |
| `updated_at` | DateTime | NOT NULL, auto-update | Last update timestamp |

**Constraints:**
- `CHECK` - Exactly one of `clip_annotation_id` or `sound_event_annotation_id` must be non-null

**Validation Rules:**
- `content`: 1-5000 characters

---

## Enum Definitions

### TagCategory
```python
class TagCategory(str, Enum):
    SPECIES = "species"
    SOUND_TYPE = "sound_type"
    QUALITY = "quality"
```

### AnnotationProjectVisibility
```python
class AnnotationProjectVisibility(str, Enum):
    PRIVATE = "private"
    PUBLIC = "public"
```

### AnnotationTaskStatus
```python
class AnnotationTaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REVIEW_PENDING = "review_pending"
```

### ReviewStatus
```python
class ReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
```

### AnnotationSource
```python
class AnnotationSource(str, Enum):
    HUMAN = "human"
    MODEL = "model"
```

### GeometryType
```python
class GeometryType(str, Enum):
    BOUNDING_BOX = "BoundingBox"
    TIME_INTERVAL = "TimeInterval"
```

---

## Index Strategy

### Tag
- `ix_tags_project_id` - Filter by project
- `ix_tags_category` - Filter by category
- `ix_tags_gbif_taxon_key` - GBIF lookup

### AnnotationProject
- `ix_annotation_projects_project_id` - Filter by parent project

### AnnotationTask
- `ix_annotation_tasks_project_id` - Filter by annotation project
- `ix_annotation_tasks_status` - Filter by status
- `ix_annotation_tasks_assigned_to_id` - Filter by assignee
- `ix_annotation_tasks_project_status` - Compound index for filtered lists

### ClipAnnotation
- `ix_clip_annotations_clip_id` - Filter by clip
- `ix_clip_annotations_review_status` - Filter by review status

### SoundEventAnnotation
- `ix_sound_event_annotations_clip_annotation_id` - Filter by parent

### Note
- `ix_notes_clip_annotation_id` - Filter by clip annotation
- `ix_notes_sound_event_annotation_id` - Filter by sound event annotation

---

## Migration Plan

### Migration: Create Tags Table
```sql
CREATE TYPE tag_category AS ENUM ('species', 'sound_type', 'quality');

CREATE TABLE tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_id UUID REFERENCES tags(id) ON DELETE SET NULL,
    name VARCHAR(200) NOT NULL,
    category tag_category NOT NULL,
    gbif_taxon_key INTEGER,
    scientific_name VARCHAR(300),
    common_name VARCHAR(300),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, name, category)
);
CREATE INDEX ix_tags_project_id ON tags(project_id);
CREATE INDEX ix_tags_category ON tags(category);
CREATE INDEX ix_tags_gbif_taxon_key ON tags(gbif_taxon_key);
```

### Migration: Create Annotation Projects Table
```sql
CREATE TYPE annotation_project_visibility AS ENUM ('private', 'public');

CREATE TABLE annotation_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_by_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    instructions TEXT,
    visibility annotation_project_visibility NOT NULL DEFAULT 'private',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, name)
);
CREATE INDEX ix_annotation_projects_project_id ON annotation_projects(project_id);

CREATE TABLE annotation_project_datasets (
    annotation_project_id UUID NOT NULL REFERENCES annotation_projects(id) ON DELETE CASCADE,
    dataset_id UUID NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    PRIMARY KEY (annotation_project_id, dataset_id)
);

CREATE TABLE annotation_project_tags (
    annotation_project_id UUID NOT NULL REFERENCES annotation_projects(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (annotation_project_id, tag_id)
);
```

### Migration: Create Annotation Tasks Table
```sql
CREATE TYPE annotation_task_status AS ENUM ('pending', 'in_progress', 'completed', 'review_pending');

CREATE TABLE annotation_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    annotation_project_id UUID NOT NULL REFERENCES annotation_projects(id) ON DELETE CASCADE,
    clip_id UUID NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    assigned_to_id UUID REFERENCES users(id) ON DELETE SET NULL,
    status annotation_task_status NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(annotation_project_id, clip_id)
);
CREATE INDEX ix_annotation_tasks_project_id ON annotation_tasks(annotation_project_id);
CREATE INDEX ix_annotation_tasks_status ON annotation_tasks(status);
CREATE INDEX ix_annotation_tasks_assigned_to_id ON annotation_tasks(assigned_to_id);
CREATE INDEX ix_annotation_tasks_project_status ON annotation_tasks(annotation_project_id, status);
```

### Migration: Create Clip Annotations Table
```sql
CREATE TYPE review_status AS ENUM ('unreviewed', 'approved', 'rejected');

CREATE TABLE clip_annotations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL UNIQUE REFERENCES annotation_tasks(id) ON DELETE CASCADE,
    clip_id UUID NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    created_by_id UUID NOT NULL REFERENCES users(id),
    review_status review_status NOT NULL DEFAULT 'unreviewed',
    reviewed_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_clip_annotations_clip_id ON clip_annotations(clip_id);
CREATE INDEX ix_clip_annotations_review_status ON clip_annotations(review_status);

CREATE TABLE clip_annotation_tags (
    clip_annotation_id UUID NOT NULL REFERENCES clip_annotations(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (clip_annotation_id, tag_id)
);
```

### Migration: Create Sound Event Annotations Table
```sql
CREATE TYPE annotation_source AS ENUM ('human', 'model');

CREATE TABLE sound_event_annotations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clip_annotation_id UUID NOT NULL REFERENCES clip_annotations(id) ON DELETE CASCADE,
    created_by_id UUID NOT NULL REFERENCES users(id),
    geometry JSONB NOT NULL,
    source annotation_source NOT NULL DEFAULT 'human',
    confidence FLOAT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0))
);
CREATE INDEX ix_sound_event_annotations_clip_annotation_id ON sound_event_annotations(clip_annotation_id);

CREATE TABLE sound_event_annotation_tags (
    sound_event_annotation_id UUID NOT NULL REFERENCES sound_event_annotations(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (sound_event_annotation_id, tag_id)
);
```

### Migration: Create Notes Table
```sql
CREATE TABLE notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_by_id UUID NOT NULL REFERENCES users(id),
    clip_annotation_id UUID REFERENCES clip_annotations(id) ON DELETE CASCADE,
    sound_event_annotation_id UUID REFERENCES sound_event_annotations(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    is_review BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CHECK (
        (clip_annotation_id IS NOT NULL AND sound_event_annotation_id IS NULL) OR
        (clip_annotation_id IS NULL AND sound_event_annotation_id IS NOT NULL)
    )
);
CREATE INDEX ix_notes_clip_annotation_id ON notes(clip_annotation_id);
CREATE INDEX ix_notes_sound_event_annotation_id ON notes(sound_event_annotation_id);
```

---

## Query Patterns

### Common Queries

1. **List tasks for annotation project with pagination**
```sql
SELECT at.*, c.start_time, c.end_time, r.filename, ca.review_status
FROM annotation_tasks at
JOIN clips c ON c.id = at.clip_id
JOIN recordings r ON r.id = c.recording_id
LEFT JOIN clip_annotations ca ON ca.task_id = at.id
WHERE at.annotation_project_id = ?
  AND (at.status = ? OR ? IS NULL)
  AND (at.assigned_to_id = ? OR ? IS NULL)
ORDER BY at.priority DESC, at.created_at
LIMIT ? OFFSET ?;
```

2. **Get annotation project progress**
```sql
SELECT
    COUNT(*) as total_tasks,
    COUNT(*) FILTER (WHERE status = 'completed') as completed_tasks,
    COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress_tasks,
    COUNT(*) FILTER (WHERE status = 'pending') as pending_tasks,
    COUNT(*) FILTER (WHERE status = 'review_pending') as review_pending_tasks
FROM annotation_tasks
WHERE annotation_project_id = ?;
```

3. **Get clip annotation with all sound events and tags**
```sql
SELECT ca.*,
       json_agg(DISTINCT jsonb_build_object('id', t.id, 'name', t.name)) as clip_tags,
       json_agg(DISTINCT jsonb_build_object(
           'id', sea.id, 'geometry', sea.geometry, 'confidence', sea.confidence,
           'tags', (SELECT json_agg(jsonb_build_object('id', t2.id, 'name', t2.name))
                    FROM sound_event_annotation_tags seat2
                    JOIN tags t2 ON t2.id = seat2.tag_id
                    WHERE seat2.sound_event_annotation_id = sea.id)
       )) as sound_events
FROM clip_annotations ca
LEFT JOIN clip_annotation_tags cat ON cat.clip_annotation_id = ca.id
LEFT JOIN tags t ON t.id = cat.tag_id
LEFT JOIN sound_event_annotations sea ON sea.clip_annotation_id = ca.id
WHERE ca.id = ?
GROUP BY ca.id;
```

4. **Tag usage statistics**
```sql
SELECT t.id, t.name, t.category,
    (SELECT COUNT(*) FROM clip_annotation_tags cat WHERE cat.tag_id = t.id) +
    (SELECT COUNT(*) FROM sound_event_annotation_tags seat WHERE seat.tag_id = t.id) as usage_count
FROM tags t
WHERE t.project_id = ?
ORDER BY usage_count DESC;
```

---

## Data Integrity Rules

1. **Cascading Deletes:**
   - Delete Project → Delete AnnotationProjects → Delete Tasks → Delete ClipAnnotations → Delete SoundEventAnnotations → Delete Notes
   - Delete Clip → Delete AnnotationTasks → Delete ClipAnnotations → ...
   - Delete AnnotationProject → Delete Tasks → ...

2. **Optional References:**
   - Delete User (assigned_to) → Set AnnotationTask.assigned_to_id to NULL
   - Delete User (reviewer) → Set ClipAnnotation.reviewed_by_id to NULL
   - Delete Tag (parent) → Set Tag.parent_id to NULL

3. **Audit Trail:**
   - All entities have `created_at` and `updated_at` timestamps
   - ClipAnnotation tracks `created_by_id` for annotator
   - ClipAnnotation tracks `reviewed_by_id` and `reviewed_at` for review
   - SoundEventAnnotation tracks `source` (human vs model)
