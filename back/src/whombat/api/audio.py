"""API functions to load audio."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio
import xarray as xr
from soundevent.arrays import ArrayAttrs, Dimensions, create_time_range, extend_dim
from soundevent.audio.attributes import AudioAttrs
from soundevent.audio.io import audio_to_bytes
from torchaudio import functional as taF

from whombat import schemas

__all__ = [
    "load_audio",
    "load_clip_bytes",
]

CHUNK_SIZE = 512 * 1024
HEADER_FORMAT = "<4si4s4sihhiihh4si"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


@dataclass
class _AudioMetadata:
    sample_rate: int
    num_frames: int
    num_channels: int


def _probe_audio(path: Path) -> _AudioMetadata:
    """Extract audio metadata without loading the full file."""
    with sf.SoundFile(str(path)) as sf_file:
        return _AudioMetadata(
            sample_rate=int(sf_file.samplerate),
            num_frames=int(len(sf_file)),
            num_channels=int(sf_file.channels),
        )


def _apply_filters(
    waveform: torch.Tensor,
    samplerate: int,
    low_freq: float | None,
    high_freq: float | None,
    order: int,
) -> torch.Tensor:
    """Apply simple cascaded biquad filters using torchaudio."""
    if samplerate <= 0 or waveform.numel() == 0:
        return waveform

    nyquist = samplerate / 2

    if low_freq is not None:
        if low_freq <= 0:
            raise ValueError("low_freq must be greater than 0 Hz.")
        if low_freq >= nyquist:
            raise ValueError(
                "low_freq must be less than the Nyquist frequency."
            )

    if high_freq is not None:
        if high_freq <= 0:
            raise ValueError("high_freq must be greater than 0 Hz.")
        if high_freq >= nyquist:
            raise ValueError(
                "high_freq must be less than the Nyquist frequency."
            )

    if (
        low_freq is not None
        and high_freq is not None
        and low_freq >= high_freq
    ):
        raise ValueError("low_freq must be less than high_freq.")

    passes = max(1, int(math.ceil(max(order, 1) / 2)))
    filtered = waveform

    if low_freq is not None:
        for _ in range(passes):
            filtered = taF.highpass_biquad(
                filtered,
                samplerate,
                cutoff_freq=low_freq,
                Q=0.707,
            )

    if high_freq is not None:
        for _ in range(passes):
            filtered = taF.lowpass_biquad(
                filtered,
                samplerate,
                cutoff_freq=high_freq,
                Q=0.707,
            )

    return filtered


def load_audio(
    recording: schemas.Recording,
    start_time: float | None = None,
    end_time: float | None = None,
    audio_dir: Path | None = None,
    audio_parameters: schemas.AudioParameters | None = None,
):
    """Load audio.

    Parameters
    ----------
    recording
        The recording to load audio from.
    start_time
        Start time in seconds.
    end_time
        End time in seconds.
    audio_dir
        The directory where the audio files are stored.
    audio_parameters
        Audio parameters.

    Returns
    -------
    bytes
        Audio data.
    """
    if audio_dir is None:
        audio_dir = Path().cwd()

    if audio_parameters is None:
        audio_parameters = schemas.AudioParameters()

    # Set start and end times.
    if start_time is None:
        start_time = 0.0

    if end_time is None:
        end_time = recording.duration

    audio_path = (audio_dir / recording.path).resolve()
    metadata = _probe_audio(audio_path)

    file_samplerate = metadata.sample_rate
    total_frames = metadata.num_frames

    load_start = max(start_time, 0.0)
    load_end = max(end_time, load_start)

    frame_offset = int(math.floor(load_start * file_samplerate))
    frame_offset = max(0, min(frame_offset, total_frames))

    expected_frames = int(
        math.floor((load_end - load_start) * file_samplerate)
    )
    expected_frames = max(expected_frames, 0)
    if frame_offset + expected_frames > total_frames:
        expected_frames = max(total_frames - frame_offset, 0)

    if expected_frames > 0 and frame_offset < total_frames:
        segment, detected_samplerate = torchaudio.load(
            str(audio_path),
            frame_offset=frame_offset,
            num_frames=expected_frames,
        )
        file_samplerate = detected_samplerate
    else:
        segment = torch.zeros(
            (metadata.num_channels, 0),
            dtype=torch.float32,
        )

    segment = segment.to(torch.float32)
    channels = (
        segment.shape[0]
        or metadata.num_channels
        or recording.channels
        or 1
    )

    waveform = torch.zeros(
        (channels, expected_frames),
        dtype=segment.dtype,
    )
    if segment.numel() > 0:
        frames_to_copy = min(segment.shape[1], expected_frames)
        waveform[
            : segment.shape[0], :frames_to_copy
        ] = segment[:, :frames_to_copy]

    current_samplerate = file_samplerate

    # Resample audio.
    if (
        audio_parameters.resample
        and audio_parameters.samplerate != current_samplerate
    ):
        target_samplerate = audio_parameters.samplerate
        if waveform.shape[1] > 0:
            waveform = taF.resample(
                waveform,
                current_samplerate,
                target_samplerate,
            )
        current_samplerate = target_samplerate

    # Filter audio.
    if (
        waveform.shape[1] > 0
        and (
            audio_parameters.low_freq is not None
            or audio_parameters.high_freq is not None
        )
    ):
        waveform = _apply_filters(
            waveform,
            current_samplerate,
            audio_parameters.low_freq,
            audio_parameters.high_freq,
            audio_parameters.filter_order,
        )

    actual_start_time = (
        frame_offset / file_samplerate if file_samplerate > 0 else 0.0
    )
    duration_seconds = (
        waveform.shape[1] / current_samplerate
        if current_samplerate > 0
        else 0.0
    )
    time_coord = create_time_range(
        start_time=actual_start_time,
        end_time=actual_start_time + duration_seconds,
        samplerate=current_samplerate if current_samplerate > 0 else 1,
    )

    data_array = xr.DataArray(
        data=waveform.transpose(1, 0).cpu().numpy(),
        dims=(Dimensions.time.value, Dimensions.channel.value),
        coords={
            Dimensions.time.value: time_coord,
            Dimensions.channel.value: np.arange(waveform.shape[0]),
        },
        attrs={
            AudioAttrs.recording_id.value: str(recording.uuid),
            AudioAttrs.path.value: str(recording.path),
            AudioAttrs.samplerate.value: current_samplerate,
            ArrayAttrs.units.value: "V",
            ArrayAttrs.standard_name.value: "amplitude",
            ArrayAttrs.long_name.value: "Amplitude",
        },
    )

    if start_time < 0:
        data_array = extend_dim(
            data_array,
            Dimensions.time.value,
            start=start_time,
        )

    return data_array


BIT_DEPTH_MAP: dict[str, int] = {
    "PCM_S8": 8,
    "PCM_16": 16,
    "PCM_24": 24,
    "PCM_32": 32,
    "PCM_U8": 8,
    "FLOAT": 32,
    "DOUBLE": 64,
}


def load_clip_bytes(
    path: Path,
    start: int,
    speed: float = 1,
    frames: int = 8192,
    time_expansion: float = 1,
    start_time: float | None = None,
    end_time: float | None = None,
    bit_depth: int = 16,
    target_samplerate: int | None = None,
) -> tuple[bytes, int, int, int]:
    """Load audio.

    Parameters
    ----------
    path
        The path to the audio file.
    start
        Start byte.
    speed
        The factor by which to speed up or slow down the audio.
        By default, it is 1.
    frames
        The number of audio frames to read at a time.
    time_expansion
        Time expansion factor of the audio. By default, it is 1.
    start_time
        The time in seconds at which to start reading the audio.
    end_time
        The time in seconds at which to stop reading the audio.
    bit_depth
        The bit depth of the resulting audio. By default, it is 16 bits.
    target_samplerate
        Optional target sample rate for resampling before applying speed.
        If provided, audio will be resampled to this rate before the speed
        adjustment is applied via the WAV header.

    Returns
    -------
    bytes
        Loaded audio data in bytes
    start
        Start byte
    end
        End byte
    filesize
        Total size of clip in bytes.
    """
    with sf.SoundFile(path) as sf_file:
        samplerate = int(sf_file.samplerate * time_expansion)
        channels = sf_file.channels

        # Calculate start and end frames based on start and end times
        # to ensure that the requested piece of audio is loaded.
        if start_time is None:
            start_time = 0
        start_frame = int(start_time * samplerate)

        end_frame = sf_file.frames
        if end_time is not None:
            end_frame = int(end_time * samplerate)

        # Calculate the total number of frames and the size of the audio
        # data in bytes.
        total_frames = end_frame - start_frame
        bytes_per_frame = channels * bit_depth // 8
        filesize = total_frames * bytes_per_frame

        # Compute the offset, which is the frame at which to start reading
        # the audio data.
        offset = start_frame
        if start != 0:
            # When the start byte is not 0, calculate the offset in frames
            # and add it to the start frame. Note that we need to
            # remove the size of the header from the start byte to correctly
            # calculate the offset in frames.
            offset_frames = (start - HEADER_SIZE) // bytes_per_frame
            offset += offset_frames

        # Make sure that the number of frames to read is not greater than
        # the number of frames requested.
        frames = min(frames, end_frame - offset)

        sf_file.seek(offset)
        audio_data = sf_file.read(frames, fill_value=0, always_2d=True)

        # Resample if target_samplerate is provided
        effective_samplerate = samplerate
        if target_samplerate is not None and target_samplerate != samplerate:
            try:
                waveform = torch.from_numpy(audio_data.T).to(torch.float32)
                if waveform.shape[1] > 0:
                    waveform = taF.resample(
                        waveform,
                        samplerate,
                        target_samplerate,
                    )
                audio_data = waveform.T.cpu().numpy()
                effective_samplerate = target_samplerate
            except Exception as e:
                # Log warning and fallback to original samplerate
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Resampling failed from {samplerate}Hz to {target_samplerate}Hz: {e}. "
                    f"Using original samplerate."
                )
                # Keep original audio_data and samplerate
                effective_samplerate = samplerate

        # Convert the audio data to raw bytes
        audio_bytes = audio_to_bytes(
            audio_data,
            samplerate=effective_samplerate,
            bit_depth=bit_depth,
        )

        # Generate the WAV header if the start byte is 0 and
        # append to the start of the audio data.
        if start == 0:
            header = generate_wav_header(
                samplerate=int(effective_samplerate * speed),
                channels=channels,
                data_size=filesize,
                bit_depth=bit_depth,
            )
            audio_bytes = header + audio_bytes

        return (
            audio_bytes,
            start,
            start + len(audio_bytes),
            filesize + HEADER_SIZE,
        )


def generate_wav_header(
    samplerate: int,
    channels: int,
    data_size: int,
    bit_depth: int = 16,
) -> bytes:
    """Generate the data of a WAV header.

    This function generates the data of a WAV header according to the
    given parameters. The WAV header is a 44-byte string that contains
    information about the audio data, such as the sample rate, the
    number of channels, and the number of samples. The WAV header
    assumes that the audio data is PCM encoded.

    Parameters
    ----------
    samplerate
        Sample rate in Hz.
    channels
        Number of channels.
    samples
        Number of samples.
    bit_depth
        The number of bits per sample. By default, it is 16 bits.

    Notes
    -----
    The structure of the WAV header is described in
    (WAV PCM soundfile format)[http://soundfile.sapp.org/doc/WaveFormat/].
    """
    byte_rate = samplerate * channels * bit_depth // 8
    block_align = channels * bit_depth // 8

    return struct.pack(
        HEADER_FORMAT,
        b"RIFF",  # RIFF chunk id
        data_size + 36,  # Size of the entire file minus 8 bytes
        b"WAVE",  # RIFF chunk id
        b"fmt ",  # fmt chunk id
        16,  # Size of the fmt chunk
        1,  # Audio format (3 corresponds to float)
        channels,  # Number of channels
        samplerate,  # Sample rate in Hz
        byte_rate,  # Byte rate
        block_align,  # Block align
        bit_depth,  # Number of bits per sample
        b"data",  # data chunk id
        data_size,  # Size of the data chunk
    )
