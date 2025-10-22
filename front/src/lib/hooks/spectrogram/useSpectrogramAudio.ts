import { useCallback, useMemo, useState, useEffect, useRef } from "react";

import useRecordingAudio from "@/app/hooks/audio/useRecordingAudio";

import { adjustToRecording } from "@/lib/hooks/settings/useAudioSettings";

import type { AudioSettings, Recording, ViewportController } from "@/lib/types";

/** A custom React hook to manage audio playback synchronized with a
 * spectrogram viewport.
 */
export default function useSpectrogramAudio({
  recording,
  viewport,
  audioSettings,
  onSeek,
  onTimeUpdate,
  ...handlers
}: {
  /** The viewport controller. */
  viewport: ViewportController;
  /** The recording object. */
  recording: Recording;
  /** The audio settings. */
  audioSettings: AudioSettings;
  onPlay?: () => void;
  onPause?: () => void;
  onEnded?: () => void;
  onError?: () => void;
  onTimeUpdate?: (time: number) => void;
  onVolumeChange?: (volume: number) => void;
  onSeek?: (time: number) => void;
  onSeeking?: () => void;
  onWaiting?: () => void;
  onLoadStart?: () => void;
  onLoadedData?: () => void;
  onCanPlay?: () => void;
  onCanPlayThrough?: () => void;
  onAbort?: () => void;
}) {
  const { viewport: current, centerOn, bounds } = viewport;

  // Adjust audio settings for compatibility with the recording
  const adjustedAudioSettings = useMemo(() => {
    const adjusted = adjustToRecording(audioSettings, recording);
    
    // For ultrasonic recordings, dynamically resample based on playback speed
    // to ensure the effective samplerate stays within browser limits
    const MAX_BROWSER_SAMPLERATE = 96000;
    const effectiveSamplerate = recording.samplerate * adjusted.speed;
    
    if (effectiveSamplerate > MAX_BROWSER_SAMPLERATE) {
      // Calculate target samplerate that will result in MAX_BROWSER_SAMPLERATE when played at current speed
      // target * speed = MAX_BROWSER_SAMPLERATE
      // target = MAX_BROWSER_SAMPLERATE / speed
      const targetSamplerate = Math.floor(MAX_BROWSER_SAMPLERATE / adjusted.speed);
      
      return {
        ...adjusted,
        resample: true,
        samplerate: targetSamplerate,
      };
    }
    
    return adjusted;
  }, [audioSettings, recording]);

  // Callback function to be executed when the audio playback time updates.
  // If the playback time is close to the edge of the current viewport,
  // this function will shift the viewport to keep the playback time visible.
  const handleTimeUpdate = useCallback(
    (time: number) => {
      const { min, max } = current.time;
      const duration = max - min;
      if (time >= max - 0.1 * duration) {
        centerOn({ time: time + 0.4 * duration });
      } else if (time <= min + 0.1 * duration) {
        centerOn({ time: time - 0.4 * duration });
      }
      onTimeUpdate?.(time);
    },
    [current.time, centerOn, onTimeUpdate],
  );

  // Track the target seek position to dynamically adjust audio range
  const [targetSeekTime, setTargetSeekTime] = useState<number | null>(null);

  // Calculate audio range with dynamic adjustment based on seek position
  const audioRange = useMemo(() => {
    const boundsDuration = bounds.time.max - bounds.time.min;
    const maxAudioDuration = 300; // Maximum 5 minutes of audio at once

    // If bounds is small enough, use it directly
    if (boundsDuration <= maxAudioDuration) {
      return { min: bounds.time.min, max: bounds.time.max };
    }

    // If user has seeked to a specific position, center the audio range around it
    if (targetSeekTime !== null) {
      const halfWindow = maxAudioDuration / 2;
      let audioStart = Math.max(bounds.time.min, targetSeekTime - halfWindow);
      let audioEnd = Math.min(bounds.time.max, targetSeekTime + halfWindow);

      // Adjust if we're near boundaries
      if (audioEnd - audioStart < maxAudioDuration) {
        if (audioStart === bounds.time.min) {
          audioEnd = Math.min(bounds.time.max, audioStart + maxAudioDuration);
        } else if (audioEnd === bounds.time.max) {
          audioStart = Math.max(bounds.time.min, audioEnd - maxAudioDuration);
        }
      }

      return { min: audioStart, max: audioEnd };
    }

    // Default: use the beginning of bounds
    return {
      min: bounds.time.min,
      max: Math.min(bounds.time.max, bounds.time.min + maxAudioDuration),
    };
  }, [bounds.time.min, bounds.time.max, targetSeekTime]);

  const audioController = useRecordingAudio({
    recording,
    startTime: audioRange.min,
    endTime: audioRange.max,
    audioSettings: adjustedAudioSettings,
    onTimeUpdate: handleTimeUpdate,
    onSeek,
    ...handlers,
  });

  // Store audioController in ref to avoid dependency issues
  const audioControllerRef = useRef(audioController);
  audioControllerRef.current = audioController;

  // Override the seek function to handle range changes
  const customSeek = useCallback(
    (time: number) => {
      // Check if the seek position is outside the current audio range
      const isOutsideRange = time < audioRange.min || time > audioRange.max;

      if (isOutsideRange) {
        // Store the target seek time and trigger audio reload
        setTargetSeekTime(time);
      } else {
        // Within range, seek directly
        audioControllerRef.current.seek(time);
      }

      // Always center the viewport and call onSeek
      centerOn({ time });
      onSeek?.(time);
    },
    [audioRange.min, audioRange.max, centerOn, onSeek],
  );

  // When audio range changes due to seeking outside range,
  // automatically seek to the target position after audio reloads
  useEffect(() => {
    if (targetSeekTime !== null && audioRange.min <= targetSeekTime && targetSeekTime <= audioRange.max) {
      // Audio has been reloaded with the new range that includes targetSeekTime
      // Now seek to the target position
      const timer = setTimeout(() => {
        audioControllerRef.current.seek(targetSeekTime);
        setTargetSeekTime(null); // Clear target after seeking
      }, 200); // Delay to ensure audio is loaded

      return () => clearTimeout(timer);
    }
  }, [targetSeekTime, audioRange.min, audioRange.max]);

  return {
    ...audioController,
    seek: customSeek,
  };
}
