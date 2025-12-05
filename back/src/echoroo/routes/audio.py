"""REST API routes for audio."""

from io import BytesIO
from typing import Annotated
from uuid import UUID

import soundfile as sf
from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import StreamingResponse

from echoroo import api, schemas
from echoroo.routes.dependencies import Session, EchorooSettings

__all__ = ["audio_router"]

audio_router = APIRouter()

CHUNK_SIZE = 1024 * 256


@audio_router.get("/stream/")
async def stream_recording_audio(
    session: Session,
    settings: EchorooSettings,
    recording_uuid: UUID,
    start_time: float | None = None,
    end_time: float | None = None,
    speed: float = 1,
    target_samplerate: int | None = None,
    range: str | None = Header(None),
) -> Response:
    """Stream the audio of a recording.

    Parameters
    ----------
    session
        Database session.
    settings
        Echoroo settings.
    recording_uuid
        The ID of the recording.

    Returns
    -------
    Response
        The audio file.
    """
    audio_dir = settings.audio_dir
    recording = await api.recordings.get(
        session,
        recording_uuid,
    )

    # Parse range header if provided, otherwise start from 0
    requested_end = None
    if range is not None:
        range_parts = range.replace("bytes=", "").split("-")
        start = int(range_parts[0])
        if len(range_parts) > 1 and range_parts[1]:
            requested_end = int(range_parts[1])
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Range request: {range}, parsed as start={start}, end={requested_end}")
    else:
        start = 0

    # Calculate how many frames to read based on the range request
    frames_to_read = CHUNK_SIZE
    if requested_end is not None:
        # Calculate the number of bytes requested
        requested_bytes = requested_end - start + 1
        # Convert to frames (assuming 16-bit stereo or mono)
        frames_to_read = min(requested_bytes // 2, CHUNK_SIZE)

    # start_time and end_time are already in the time-expanded domain,
    # so we don't need to multiply by time_expansion here.
    # The time_expansion parameter is passed separately to load_clip_bytes.

    data, start_byte, end_byte, filesize = api.load_clip_bytes(
        path=audio_dir / recording.path,
        start=start,
        frames=frames_to_read,
        speed=speed,
        time_expansion=recording.time_expansion,
        start_time=start_time,
        end_time=end_time,
        target_samplerate=target_samplerate,
    )

    # If a specific end was requested and we got more data than requested,
    # truncate to the exact range
    if requested_end is not None and len(data) > (requested_end - start + 1):
        data = data[: requested_end - start + 1]
        end_byte = start + len(data)

    # If no range header was provided, return 200 OK with full content
    # Otherwise return 206 Partial Content with range information
    if range is None:
        headers = {
            "Content-Length": f"{len(data)}",
            "Accept-Ranges": "bytes",
        }
        return Response(
            content=data,
            status_code=200,
            media_type="audio/wav",
            headers=headers,
        )
    else:
        headers = {
            "Content-Range": f"bytes {start_byte}-{end_byte-1}/{filesize}",
            "Content-Length": f"{len(data)}",
            "Accept-Ranges": "bytes",
        }
        return Response(
            content=data,
            status_code=206,
            media_type="audio/wav",
            headers=headers,
        )


@audio_router.get("/download/")
async def download_recording_audio(
    session: Session,
    settings: EchorooSettings,
    recording_uuid: UUID,
    audio_parameters: Annotated[
        schemas.AudioParameters,  # type: ignore
        Depends(schemas.AudioParameters),
    ],
    start_time: float | None = None,
    end_time: float | None = None,
) -> StreamingResponse:
    """Get audio for a recording.

    Parameters
    ----------
    session
        Database session.
    settings
        Echoroo settings.
    recording_uuid
        The UUID of the recording.
    start_time
        The start time of the audio to return, by default None. If None, the
        audio will start at the beginning of the recording.
    end_time
        The end time of the audio to return, by default None. If None, the
        audio will end at the end of the recording.
    audio_parameters
        Audio parameters to use when processing the audio. Includes
        resampling and filtering parameters.

    Returns
    -------
    Response
        The audio file.
    """
    recording = await api.recordings.get(session, recording_uuid)

    audio = api.load_audio(
        recording,
        start_time=start_time,
        end_time=end_time,
        audio_parameters=audio_parameters,
        audio_dir=settings.audio_dir,
    )

    # Get the samplerate and recording ID.
    samplerate = int(1 / audio.time.attrs["step"])
    id = audio.attrs["recording_id"]

    # Write the audio to a buffer.
    buffer = BytesIO()
    sf.write(buffer, audio.data, samplerate, format="WAV")
    buffer.seek(0)

    # Return the audio.
    return StreamingResponse(
        content=buffer,
        media_type="audio/wav",
        headers={"Content-Disposition": f"attachment; filename={id}.wav"},
    )
