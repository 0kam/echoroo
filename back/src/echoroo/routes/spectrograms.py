"""REST API routes for spectrograms."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from echoroo import api, schemas
from echoroo.core import images
from echoroo.routes.dependencies import Session, EchorooSettings

__all__ = ["spectrograms_router"]

spectrograms_router = APIRouter()


@spectrograms_router.get(
    "/",
)
async def get_spectrogram(
    session: Session,
    settings: EchorooSettings,
    recording_uuid: UUID,
    start_time: float,
    end_time: float,
    audio_parameters: Annotated[
        schemas.AudioParameters, Depends(schemas.AudioParameters)
    ],
    spectrogram_parameters: Annotated[
        schemas.SpectrogramParameters,
        Depends(schemas.SpectrogramParameters),
    ],
) -> Response:
    """Get a spectrogram for a recording.

    Parameters
    ----------
    session : Session
        SQLAlchemy session.
    recording_id : int
        Recording ID.
    start_time : float
        Start time in seconds.
    end_time : float
        End time in seconds.
    parameters : SpectrogramParameters
        Spectrogram parameters.

    Returns
    -------
    Response
        Spectrogram image.

    """
    recording = await api.recordings.get(session, recording_uuid)

    data = api.compute_spectrogram(
        recording,
        start_time,
        end_time,
        audio_parameters,
        spectrogram_parameters,
        audio_dir=settings.audio_dir,
    )

    # Normalize.
    if spectrogram_parameters.normalize:
        data_min = data.min()
        data_max = data.max()
        data = data - data_min
        data_range = data_max - data_min
        if data_range > 0:
            data = data / data_range

    # Calculate resize dimensions (default 2x for better quality)
    height, width = data.shape
    time_scale = spectrogram_parameters.time_scale
    freq_scale = spectrogram_parameters.freq_scale
    resize_dims = (int(width * time_scale), int(height * freq_scale))

    image = images.array_to_image(
        data,
        cmap=spectrogram_parameters.cmap,
        resize=resize_dims,
    )

    buffer = images.image_to_buffer(image)

    return Response(
        content=buffer.read(),
        media_type="image/png",
    )
