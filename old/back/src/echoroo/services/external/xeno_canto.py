"""Xeno-Canto external service for audio data integration."""

import io
import re
from typing import Tuple

import httpx
import soundfile as sf
import numpy as np

__all__ = ["XenoCantoService"]


class XenoCantoService:
    """Service for interacting with Xeno-Canto API."""

    BASE_URL = "https://xeno-canto.org"
    AUDIO_DOWNLOAD_URL = f"{BASE_URL}/{{recording_id}}/download"

    def __init__(self):
        self.client = httpx.AsyncClient(follow_redirects=True, timeout=60.0)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def download_audio(
        self,
        xeno_canto_id: str | int,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> Tuple[bytes, str]:
        """Download audio from Xeno-Canto.

        Args:
            xeno_canto_id: Xeno-Canto recording ID
            start_time: Start time in seconds (optional)
            end_time: End time in seconds (optional)

        Returns:
            Tuple of (audio_bytes, content_type)

        Raises:
            httpx.HTTPStatusError: If download fails
        """
        normalized_id = self.normalize_id(xeno_canto_id)
        url = self.AUDIO_DOWNLOAD_URL.format(recording_id=normalized_id)

        response = await self.client.get(url)
        if response.status_code != 200:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to download Xeno-Canto recording {xeno_canto_id}",
            )

        audio_bytes = response.content
        content_type = response.headers.get("content-type", "audio/mpeg")

        # Extract time segment if needed
        if start_time is not None or end_time is not None:
            audio_bytes, content_type = self._extract_time_segment(
                audio_bytes, start_time, end_time
            )

        return audio_bytes, content_type

    async def get_audio_duration(self, xeno_canto_id: str | int) -> float:
        """Get audio duration in seconds.

        Args:
            xeno_canto_id: Xeno-Canto recording ID

        Returns:
            Duration in seconds
        """
        audio_bytes, _ = await self.download_audio(xeno_canto_id)
        with io.BytesIO(audio_bytes) as audio_buffer:
            info = sf.info(audio_buffer)
            return info.duration

    @staticmethod
    def normalize_id(xeno_canto_id: str | int) -> str:
        """Normalize Xeno-Canto ID to string format.

        Args:
            xeno_canto_id: ID as string or int

        Returns:
            Normalized ID string
        """
        if isinstance(xeno_canto_id, int):
            return str(xeno_canto_id)
        # Remove "XC" prefix and any non-digit characters
        xc_str = str(xeno_canto_id).upper()
        if xc_str.startswith("XC"):
            xc_str = xc_str[2:]
        return re.sub(r"\D", "", xc_str)

    def _extract_time_segment(
        self,
        audio_bytes: bytes,
        start_time: float | None,
        end_time: float | None,
    ) -> Tuple[bytes, str]:
        """Extract time segment from audio.

        Args:
            audio_bytes: Original audio bytes
            start_time: Start time in seconds
            end_time: End time in seconds

        Returns:
            Tuple of (segmented audio bytes, content_type)
        """
        # Load full audio
        with io.BytesIO(audio_bytes) as audio_buffer:
            data, samplerate = sf.read(audio_buffer, always_2d=True)

        # Determine time range
        if start_time is None:
            start_time = 0.0
        if end_time is None:
            end_time = len(data) / samplerate

        # Validate time range
        if start_time < 0:
            start_time = 0.0
        if end_time > len(data) / samplerate:
            end_time = len(data) / samplerate
        if start_time >= end_time:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail=f"Invalid time range: start_time ({start_time}) must be less than end_time ({end_time})",
            )

        # Calculate sample indices
        start_sample = int(start_time * samplerate)
        end_sample = int(end_time * samplerate)

        # Clamp to valid range
        start_sample = max(0, min(start_sample, len(data)))
        end_sample = max(start_sample, min(end_sample, len(data)))

        # Extract segment
        segment = data[start_sample:end_sample]

        # Convert back to bytes (WAV format for consistency)
        output_buffer = io.BytesIO()
        sf.write(output_buffer, segment, samplerate, format="WAV")
        audio_bytes = output_buffer.getvalue()
        content_type = "audio/wav"

        return audio_bytes, content_type
