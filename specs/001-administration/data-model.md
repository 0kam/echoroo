# Data Model: System Administration

**Date**: 2026-01-16 | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

## Overview

This document defines the data model for the System Administration feature. Models are implemented using SQLAlchemy 2.0 with PostgreSQL-specific features.

## Entity Relationship Diagram

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│      User        │     │     Project      │     │  ProjectMember   │
├──────────────────┤     ├──────────────────┤     ├──────────────────┤
│ id (PK, UUID)    │◄────│ owner_id (FK)    │     │ id (PK, UUID)    │
│ email            │     │ id (PK, UUID)    │◄────│ project_id (FK)  │
│ hashed_password  │     │ name             │     │ user_id (FK)     │────►┌─────────┐
│ display_name     │     │ description      │     │ role (enum)      │     │  User   │
│ organization     │     │ target_taxa      │     │ joined_at        │     └─────────┘
│ is_active        │     │ visibility       │     │ invited_by_id    │
│ is_superuser     │     │ created_at       │     └──────────────────┘
│ is_verified      │     │ updated_at       │
│ last_login_at    │     └──────────────────┘
│ created_at       │
│ updated_at       │     ┌──────────────────┐
└──────────────────┘     │ProjectInvitation │
        │                ├──────────────────┤
        │                │ id (PK, UUID)    │
        ▼                │ project_id (FK)  │
┌──────────────────┐     │ email            │
│    APIToken      │     │ role             │
├──────────────────┤     │ token_hash       │
│ id (PK, UUID)    │     │ invited_by_id    │
│ user_id (FK)     │     │ expires_at       │
│ token_hash       │     │ accepted_at      │
│ name             │     │ created_at       │
│ last_used_at     │     └──────────────────┘
│ expires_at       │
│ is_active        │     ┌──────────────────┐
│ created_at       │     │  SystemSetting   │
└──────────────────┘     ├──────────────────┤
                         │ key (PK)         │
┌──────────────────┐     │ value            │
│   LoginAttempt   │     │ value_type       │
├──────────────────┤     │ description      │
│ id (PK, UUID)    │     │ updated_at       │
│ email            │     │ updated_by_id    │
│ ip_address       │     └──────────────────┘
│ success          │
│ attempted_at     │     ┌──────────────────┐     ┌──────────────────┐
│ user_agent       │     │    Recorder      │     │     License      │
│ user_id (FK)     │     ├──────────────────┤     ├──────────────────┤
└──────────────────┘     │ id (PK, str)     │     │ id (PK, str)     │
                         │ manufacturer     │     │ name             │
                         │ recorder_name    │     │ short_name       │
                         │ version          │     │ url              │
                         │ created_at       │     │ description      │
                         │ updated_at       │     │ created_at       │
                         └──────────────────┘     │ updated_at       │
                                                  └──────────────────┘
```

## Existing Models (Implemented)

### User
**File**: `apps/api/echoroo/models/user.py`
**Status**: ✅ Implemented

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | UUID | No | Primary key |
| email | String(255) | No | Unique email address |
| hashed_password | String(255) | No | bcrypt/argon2 hash |
| display_name | String(100) | Yes | Display name |
| organization | String(200) | Yes | Organization/affiliation |
| is_active | Boolean | No | Account active status |
| is_superuser | Boolean | No | System admin flag |
| is_verified | Boolean | No | Email verified status |
| last_login_at | DateTime | Yes | Last successful login |
| email_verification_token | String(255) | Yes | Verification token |
| email_verification_expires_at | DateTime | Yes | Token expiration |
| password_reset_token | String(255) | Yes | Reset token |
| password_reset_expires_at | DateTime | Yes | Token expiration |
| created_at | DateTime | No | Creation timestamp |
| updated_at | DateTime | No | Update timestamp |

### Project
**File**: `apps/api/echoroo/models/project.py`
**Status**: ✅ Implemented

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | UUID | No | Primary key |
| name | String(200) | No | Project name |
| description | Text | Yes | Project description |
| target_taxa | String(500) | Yes | Target species (comma-separated) |
| visibility | Enum | No | 'private' or 'public' |
| owner_id | UUID (FK) | No | References users.id |
| created_at | DateTime | No | Creation timestamp |
| updated_at | DateTime | No | Update timestamp |

### ProjectMember
**File**: `apps/api/echoroo/models/project.py`
**Status**: ✅ Implemented

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | UUID | No | Primary key |
| user_id | UUID (FK) | No | References users.id |
| project_id | UUID (FK) | No | References projects.id |
| role | Enum | No | 'admin', 'member', or 'viewer' |
| joined_at | DateTime | No | Join timestamp |
| invited_by_id | UUID (FK) | Yes | References users.id |

**Constraints**:
- UNIQUE(user_id, project_id)

### ProjectInvitation
**File**: `apps/api/echoroo/models/project.py`
**Status**: ✅ Implemented

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | UUID | No | Primary key |
| project_id | UUID (FK) | No | References projects.id |
| email | String(255) | No | Invitee email |
| role | Enum | No | Role to assign |
| token_hash | String(255) | No | SHA256 hash |
| invited_by_id | UUID (FK) | No | References users.id |
| expires_at | DateTime | No | Token expiration |
| accepted_at | DateTime | Yes | Acceptance timestamp |
| created_at | DateTime | No | Creation timestamp |

### APIToken
**File**: `apps/api/echoroo/models/user.py`
**Status**: ✅ Implemented

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | UUID | No | Primary key |
| user_id | UUID (FK) | No | References users.id |
| token_hash | String(255) | No | SHA256 hash (unique) |
| name | String(100) | No | Token name |
| last_used_at | DateTime | Yes | Last usage timestamp |
| expires_at | DateTime | Yes | Optional expiration |
| is_active | Boolean | No | Active status |
| created_at | DateTime | No | Creation timestamp |

### LoginAttempt
**File**: `apps/api/echoroo/models/user.py`
**Status**: ✅ Implemented

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | UUID | No | Primary key |
| email | String(255) | No | Attempted email |
| ip_address | String(45) | No | Client IP (IPv6 ready) |
| success | Boolean | No | Login success status |
| attempted_at | DateTime | No | Attempt timestamp |
| user_agent | String(500) | Yes | Browser user agent |
| user_id | UUID (FK) | Yes | References users.id |

**Indexes**:
- (email, attempted_at) - Rate limiting queries
- (ip_address, attempted_at) - Rate limiting queries

### SystemSetting
**File**: `apps/api/echoroo/models/system.py`
**Status**: ✅ Implemented

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| key | String(100) | No | Primary key |
| value | Text | No | Setting value (JSON-encoded) |
| value_type | Enum | No | 'string', 'number', 'boolean', 'json' |
| description | String(500) | Yes | Setting description |
| updated_at | DateTime | No | Update timestamp |
| updated_by_id | UUID (FK) | Yes | References users.id |

## New Models (To Be Implemented)

### Recorder
**File**: `apps/api/echoroo/models/recorder.py`
**Status**: ⬜ Not implemented

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | String(50) | No | Primary key (e.g., 'am120') |
| manufacturer | String(100) | No | Manufacturer name |
| recorder_name | String(100) | No | Device model name |
| version | String(50) | Yes | Version/revision |
| created_at | DateTime | No | Creation timestamp |
| updated_at | DateTime | No | Update timestamp |

**Seed Data**:

| id | manufacturer | recorder_name | version |
|----|--------------|---------------|---------|
| am120 | Open Acoustic Devices | AudioMoth | 1.2.0 |
| smmicro2 | Wildlife Acoustics | Song Meter Micro2 | NULL |
| smmini2li | Wildlife Acoustics | Song Meter Mini2 (Li) | NULL |
| smmini2aa | Wildlife Acoustics | Song Meter Mini2 (AA) | NULL |
| sm4 | Wildlife Acoustics | Song Meter SM4 | NULL |
| sm5 | Wildlife Acoustics | Song Meter SM5 | NULL |

### License
**File**: `apps/api/echoroo/models/license.py`
**Status**: ⬜ Not implemented

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | String(50) | No | Primary key (e.g., 'BY-NC-SA') |
| name | String(200) | No | Full license name |
| short_name | String(50) | No | Short display name |
| url | String(500) | Yes | License URL |
| description | Text | Yes | License description |
| created_at | DateTime | No | Creation timestamp |
| updated_at | DateTime | No | Update timestamp |

**Seed Data**:

| id | name | short_name | url |
|----|------|------------|-----|
| BY-NC-ND | Attribution-NonCommercial-NoDerivatives 4.0 | CC BY-NC-ND 4.0 | https://creativecommons.org/licenses/by-nc-nd/4.0/ |
| BY-NC-SA | Attribution-NonCommercial-ShareAlike 4.0 | CC BY-NC-SA 4.0 | https://creativecommons.org/licenses/by-nc-sa/4.0/ |
| BY-SA | Attribution-ShareAlike 4.0 | CC BY-SA 4.0 | https://creativecommons.org/licenses/by-sa/4.0/ |

## Enums

### ProjectVisibility
**File**: `apps/api/echoroo/models/enums.py`
**Status**: ✅ Implemented

```python
class ProjectVisibility(str, Enum):
    PRIVATE = "private"
    PUBLIC = "public"
```

### ProjectRole
**File**: `apps/api/echoroo/models/enums.py`
**Status**: ✅ Implemented

```python
class ProjectRole(str, Enum):
    ADMIN = "admin"    # Full control
    MEMBER = "member"  # Read/write access
    VIEWER = "viewer"  # Read-only access
```

### SettingType
**File**: `apps/api/echoroo/models/enums.py`
**Status**: ✅ Implemented

```python
class SettingType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"
```

## System Settings (Initial Values)

| Key | Value | Type | Description |
|-----|-------|------|-------------|
| registration_mode | "open" | string | "open", "invitation", or "closed" |
| session_timeout_hours | "2" | number | JWT session timeout in hours |
| setup_completed | "false" | boolean | Initial setup completion flag |

## Migration Strategy

### Phase 1: Core Tables (Already Done)
- users
- projects
- project_members
- project_invitations
- api_tokens
- login_attempts
- system_settings

### Phase 2: Master Data Tables (To Be Done)
1. Create `recorders` table
2. Create `licenses` table
3. Insert seed data for recorders
4. Insert seed data for licenses

### Indexes

**Existing**:
- users(email) - Unique, login lookups
- users(is_active) - Active user queries
- projects(visibility) - Visibility filtering
- projects(owner_id) - Owner queries
- project_members(user_id) - User's projects
- project_members(project_id, user_id) - Membership queries
- login_attempts(email, attempted_at) - Rate limiting
- login_attempts(ip_address, attempted_at) - Rate limiting

**To Be Added**:
- recorders(manufacturer) - Filter by manufacturer
- licenses(short_name) - License lookups
