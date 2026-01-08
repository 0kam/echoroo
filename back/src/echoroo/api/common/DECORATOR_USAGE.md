# AccessControlDecorator Usage Guide

## Overview

The `require_ml_project_access` decorator consolidates the repetitive "Verify project access" pattern used throughout `routes/ml_projects.py`.

## Before (Repetitive Pattern - 26 occurrences)

```python
@router.get("/{ml_project_uuid}/reference_sounds/{reference_sound_uuid}")
async def get_reference_sound(
    session: Session,
    ml_project_uuid: UUID,
    reference_sound_uuid: UUID,
    user: models.User | None = Depends(optional_user_dep),
) -> schemas.ReferenceSound:
    """Get a specific reference sound."""
    # Verify project access
    await api.ml_projects.get(
        session,
        ml_project_uuid,
        user=user,
    )
    return await api.reference_sounds.get(
        session,
        reference_sound_uuid,
        user=user,
    )
```

## After (With Decorator)

```python
from echoroo.api.common.decorators import require_ml_project_access

@router.get("/{ml_project_uuid}/reference_sounds/{reference_sound_uuid}")
@require_ml_project_access(edit_mode=False)
async def get_reference_sound(
    session: Session,
    ml_project_uuid: UUID,
    reference_sound_uuid: UUID,
    user: models.User | None = Depends(optional_user_dep),
    **kwargs  # ml_project will be added here
) -> schemas.ReferenceSound:
    """Get a specific reference sound."""
    # ml_project is now available in kwargs, access verified
    return await api.reference_sounds.get(
        session,
        reference_sound_uuid,
        user=user,
    )
```

## Benefits

1. **Code Reduction**: Eliminates ~10 lines per endpoint × 26 endpoints = **260 lines saved**
2. **Consistency**: Ensures uniform access control logic across all endpoints
3. **Maintainability**: Single point of modification for access control logic
4. **Type Safety**: Decorator handles parameter extraction and validation
5. **Readability**: Intent is clear from decorator name

## Decorator Parameters

- `edit_mode` (bool, default=False):
  - `False`: Requires view permissions (read-only access)
  - `True`: Requires edit permissions (write access)

## How It Works

1. Extracts `session`, `ml_project_uuid`, and `user` from function kwargs
2. Calls `api.ml_projects.get()` which internally verifies permissions
3. Adds the fetched `ml_project` to kwargs for use in the function
4. Raises appropriate exceptions if access is denied or project not found

## Required Function Parameters

The decorated function MUST have these parameters:
- `session: AsyncSession` (or `Session` as FastAPI dependency)
- `ml_project_uuid: UUID`
- `user: models.User | None`

## Exception Handling

The decorator raises:
- `ValueError`: If required parameters are missing
- `NotFoundError`: If ML project doesn't exist (from api.ml_projects.get)
- `PermissionDeniedError`: If user lacks access (from api.ml_projects.get)

## Integration Points

Currently used in `routes/ml_projects.py` for:
- Reference sounds endpoints (6 occurrences)
- Search sessions endpoints (14 occurrences)
- Custom models endpoints (3 occurrences)
- Inference batches endpoints (3 occurrences)

## Future Enhancements

Potential improvements:
1. Support for batch project access verification
2. Caching of permission checks within request scope
3. Additional decorators for other entity types (datasets, annotation projects)
4. Fine-grained permission levels beyond view/edit
