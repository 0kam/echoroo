"""Public system settings endpoints for authenticated users."""

from fastapi import APIRouter

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.system import SystemSettingRepository

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get(
    "/embedding-model",
    summary="Get embedding model setting",
    description=(
        "Return the admin-configured embedding model name. "
        "Any authenticated user can call this endpoint to determine "
        "which embedding model is used for custom model training."
    ),
)
async def get_embedding_model(
    db: DbSession,
    current_user: CurrentUser,  # noqa: ARG001 - used for auth dependency
) -> dict[str, str]:
    """Return the currently configured embedding model.

    Reads the 'embedding_model' system setting, defaulting to 'perch'
    if the setting has not been explicitly configured by an admin.

    Args:
        db: Database session
        current_user: Current authenticated user (required for auth)

    Returns:
        Dictionary with 'embedding_model' key and its value ('perch' or 'birdnet')

    Raises:
        401: Not authenticated
    """
    setting_repo = SystemSettingRepository(db)
    embedding_model = await setting_repo.get_embedding_model()
    return {"embedding_model": embedding_model}
