"""Routes related to initial application setup."""

from pathlib import Path

from fastapi import APIRouter, HTTPException

from whombat import exceptions, schemas
from whombat.system.settings import (
    Settings,
    load_settings_from_file,
    write_settings_to_file,
)

__all__ = ["get_setup_router"]


def get_setup_router() -> APIRouter:
    """Create a router exposing setup utilities."""
    router = APIRouter()

    @router.get(
        "/audio_dir/",
        response_model=schemas.AudioDirectory,
        tags=["setup"],
    )
    async def get_audio_directory() -> schemas.AudioDirectory:
        """Return the currently configured audio directory."""
        current_settings = load_settings_from_file()
        return schemas.AudioDirectory(audio_dir=current_settings.audio_dir)

    @router.post(
        "/audio_dir/",
        response_model=schemas.AudioDirectory,
        tags=["setup"],
    )
    async def update_audio_directory(
        payload: schemas.AudioDirectoryUpdate,
    ) -> schemas.AudioDirectory:
        """Persist a new audio directory in the application settings."""
        target = payload.audio_dir

        if not target.exists() or not target.is_dir():
            # DirectoryPath should have already validated this, but guard just in case.
            raise HTTPException(
                status_code=422,
                detail="Provided path is not a directory.",
            )

        try:
            current_settings = load_settings_from_file()
        except Exception as error:  # pragma: no cover - safety net
            raise HTTPException(
                status_code=500,
                detail="Unable to load current application settings.",
            ) from error

        updated_settings = Settings.model_validate(
            current_settings.model_dump()
        ).model_copy(
            update={"audio_dir": Path(target).resolve()}
        )

        try:
            write_settings_to_file(updated_settings)
        except exceptions.MissingDatabaseError as error:  # pragma: no cover
            raise HTTPException(
                status_code=500,
                detail="Failed to persist application settings.",
            ) from error

        return schemas.AudioDirectory(audio_dir=updated_settings.audio_dir)

    return router
