"""API functions to load audio."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import xarray as xr
from soundevent.arrays import ArrayAttrs, Dimensions, create_time_range, extend_dim
from soundevent.audio.attributes import AudioAttrs
from soundevent.audio.io import audio_to_bytes
from torchaudio import functional as taF

from echoroo import schemas

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

    time_expansion = recording.time_expansion or 1.0
    file_samplerate = metadata.sample_rate
    total_frames = metadata.num_frames

    effective_samplerate = recording.samplerate
    if effective_samplerate is None or effective_samplerate <= 0:
        effective_samplerate = int(
            round(file_samplerate * time_expansion)
        ) or file_samplerate

    max_original_time = None
    if file_samplerate > 0 and time_expansion > 0:
        max_original_time = (total_frames / file_samplerate) / time_expansion
    if max_original_time is None:
        max_original_time = getattr(recording, "duration", None)
    if max_original_time is None:
        max_original_time = float("inf")

    read_start = max(min(start_time, max_original_time), 0.0)
    read_end = max(min(end_time, max_original_time), read_start)

    frame_offset = int(math.floor(read_start * effective_samplerate))
    frame_offset = max(0, min(frame_offset, total_frames))

    expected_frames = int(
        math.floor((read_end - read_start) * effective_samplerate)
    )
    expected_frames = max(expected_frames, 0)
    available_frames = max(total_frames - frame_offset, 0)
    if expected_frames > available_frames:
        expected_frames = available_frames

    channels = metadata.num_channels or recording.channels or 1
    waveform = torch.zeros(
        (channels, expected_frames),
        dtype=torch.float32,
    )

    if expected_frames > 0 and frame_offset < total_frames:
        with sf.SoundFile(audio_path) as sf_file:
            sf_file.seek(frame_offset)
            segment = sf_file.read(
                frames=expected_frames,
                dtype="float32",
                always_2d=True,
            )
        if segment.size > 0:
            segment_tensor = torch.from_numpy(segment.T.copy())
            frames_to_copy = min(segment_tensor.shape[1], expected_frames)
            waveform[: segment_tensor.shape[0], :frames_to_copy] = (
                segment_tensor[:, :frames_to_copy]
            )

    current_samplerate = int(effective_samplerate)

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
        frame_offset / effective_samplerate if effective_samplerate > 0 else 0.0
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
    """Load audio bytes for streaming playback.

    This function loads a chunk of audio data from a file and prepares it for
    streaming. It handles:
    - Time-based slicing (start_time, end_time)
    - Byte-based seeking (start parameter for range requests)
    - Optional resampling to a target sample rate
    - Speed adjustment via WAV header manipulation

    Parameters
    ----------
    path
        The path to the audio file.
    start
        Start byte position for range requests. Use 0 for the beginning.
    speed
        Playback speed multiplier (applied via WAV header). Default is 1.
    frames
        Target number of audio frames to read in the output sample rate.
    time_expansion
        Time expansion factor of the original recording. Default is 1.
    start_time
        Start time in seconds (in the time-expanded domain).
    end_time
        End time in seconds (in the time-expanded domain).
    bit_depth
        Bit depth of the output audio. Default is 16 bits.
    target_samplerate
        Target sample rate for resampling. If None, uses file_samplerate.

    Returns
    -------
    tuple[bytes, int, int, int]
        - Audio data bytes (including WAV header if start==0)
        - Start byte position
        - End byte position
        - Total file size in bytes (including header)
    """
    import logging
    logger = logging.getLogger(__name__)

    with sf.SoundFile(path) as sf_file:
        file_samplerate = sf_file.samplerate
        channels = sf_file.channels
        subtype = (sf_file.subtype or "").upper()

        effective_bit_depth = BIT_DEPTH_MAP.get(subtype, bit_depth)
        bytes_per_frame = channels * effective_bit_depth // 8
        bit_depth = effective_bit_depth

        # Determine output sample rate
        # If no target is specified, use the file's sample rate
        output_samplerate = target_samplerate if target_samplerate is not None else file_samplerate

        passthrough = (
            speed == 1
            and time_expansion == 1
            and start_time is None
            and end_time is None
            and (target_samplerate is None or target_samplerate == file_samplerate)
        )

        if passthrough:
            bytes_to_read = frames * bytes_per_frame
            if start == 0:
                bytes_to_read += HEADER_SIZE
            if bytes_to_read <= 0:
                bytes_to_read = -1

            with path.open("rb") as raw_file:
                raw_file.seek(start)
                chunk = raw_file.read(bytes_to_read)

            actual_end = start + len(chunk)
            return (
                chunk,
                start,
                actual_end,
                path.stat().st_size,
            )

        # Calculate time boundaries in file frames
        # start_time and end_time are in the ORIGINAL recording's time domain (after time_expansion)
        # We need to convert to file time: file_time = original_time * time_expansion
        if start_time is None:
            start_time = 0
        if end_time is None:
            # Calculate end time in the original recording's time domain
            end_time = (sf_file.frames / file_samplerate) / time_expansion

        # Convert original recording time to file time
        file_start_time = start_time * time_expansion
        file_end_time = end_time * time_expansion

        start_frame = int(round(file_start_time * file_samplerate))
        end_frame = int(round(file_end_time * file_samplerate))
        start_frame = max(0, min(start_frame, sf_file.frames))
        end_frame = max(start_frame, min(end_frame, sf_file.frames))

        # Total duration in file frames
        total_frames_in_file = end_frame - start_frame

        # Bytes per frame in the output format
        bytes_per_frame = channels * bit_depth // 8

        # Calculate total size in output sample rate
        total_frames_in_output = int(total_frames_in_file * output_samplerate / file_samplerate)
        filesize = total_frames_in_output * bytes_per_frame

        # Determine where to start reading in the file
        offset = start_frame
        if start > HEADER_SIZE:
            # Convert byte offset to frame offset in the output sample rate
            # The byte stream contains data at output_samplerate (after resampling)
            byte_offset = start - HEADER_SIZE
            frame_offset_in_output = byte_offset // bytes_per_frame
            # Convert output frame offset to file frame offset
            # Since we resample from file_samplerate to output_samplerate,
            # the relationship is: file_frames = output_frames * (file_sr / output_sr)
            frame_offset_in_file = int(frame_offset_in_output * file_samplerate / output_samplerate)
            offset = start_frame + frame_offset_in_file

        # Calculate how many frames to read from the file
        # We want 'frames' frames in the output sample rate
        frames_to_read_in_file = int(math.ceil(frames * file_samplerate / output_samplerate))
        frames_to_read_in_file = min(frames_to_read_in_file, end_frame - offset)
        frames_to_read_in_file = max(0, frames_to_read_in_file)

        logger.debug(
            f"load_clip_bytes: start={start}, time_expansion={time_expansion:.2f}, "
            f"original_time=[{start_time:.3f}, {end_time:.3f}], "
            f"file_time=[{file_start_time:.3f}, {file_end_time:.3f}], "
            f"file_sr={file_samplerate}, output_sr={output_samplerate}, "
            f"file_frames=[{start_frame}, {end_frame}], offset={offset}, "
            f"frames_to_read={frames_to_read_in_file}, total_output_frames={total_frames_in_output}"
        )

        # Read audio data from file
        sf_file.seek(offset)
        audio_data = sf_file.read(frames_to_read_in_file, fill_value=0, always_2d=True)

        logger.debug(
            f"Read audio_data: shape={audio_data.shape}, "
            f"min={audio_data.min():.6f}, max={audio_data.max():.6f}, "
            f"mean={audio_data.mean():.6f}, std={audio_data.std():.6f}"
        )

        # Resample if target sample rate differs from file sample rate
        if (
            target_samplerate is not None
            and target_samplerate > 0
            and target_samplerate != file_samplerate
        ):
            try:
                # Convert to torch tensor for resampling
                waveform = torch.from_numpy(audio_data.T).to(torch.float32)
                if waveform.shape[1] > 0:
                    waveform = taF.resample(
                        waveform,
                        file_samplerate,
                        target_samplerate,
                    )
                audio_data = waveform.T.cpu().numpy()
                logger.debug(
                    f"Resampled from {file_samplerate}Hz to {target_samplerate}Hz, "
                    f"output shape: {audio_data.shape}"
                )
            except Exception as e:
                logger.error(
                    f"Resampling failed from {file_samplerate}Hz to {target_samplerate}Hz: {e}. "
                    "Returning original sample rate data."
                )
                # Keep original data without resampling
                # Recalculate output parameters
                output_samplerate = file_samplerate
                total_frames_in_output = total_frames_in_file
                filesize = total_frames_in_output * bytes_per_frame

        # Convert audio data to bytes
        audio_bytes = audio_to_bytes(
            audio_data,
            samplerate=output_samplerate,
            bit_depth=bit_depth,
        )
        data_size = len(audio_bytes)

        logger.debug(
            f"Converted to bytes: len={len(audio_bytes)}, "
            f"expected={(audio_data.shape[0] * audio_data.shape[1] * bit_depth // 8)}"
        )

        # Generate WAV header only at the start of the stream
        if start == 0:
            # Apply speed and time_expansion adjustments to the sample rate in the header
            # This makes the browser play the audio at the correct speed without resampling
            header_samplerate = int(output_samplerate * speed * time_expansion)
            logger.debug(
                f"Generating WAV header: samplerate={header_samplerate}, "
                f"channels={channels}, data_size={filesize}, bit_depth={bit_depth}"
            )
            header = generate_wav_header(
                samplerate=header_samplerate,
                channels=channels,
                data_size=data_size,
                bit_depth=bit_depth,
            )
            audio_bytes = header + audio_bytes
            logger.debug(f"WAV header added: header_len={len(header)}, total_len={len(audio_bytes)}")

        # Calculate actual byte range
        actual_start = start
        actual_end = start + len(audio_bytes)

        return (
            audio_bytes,
            actual_start,
            actual_end,
            data_size + HEADER_SIZE,
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
