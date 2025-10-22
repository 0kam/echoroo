import { useCallback, useMemo } from "react";

import api from "@/app/api";

import useAudio from "@/lib/hooks/audio/useAudio";

import type { AudioController, AudioSettings, Recording } from "@/lib/types";

export default function useRecordingAudio({
  recording,
  startTime,
  endTime,
  audioSettings,
  onTimeUpdate,
  onSeek,
  ...handlers
}: {
  recording: Recording;
  startTime: number;
  endTime: number;
  audioSettings: AudioSettings;
  onSeek?: (time: number) => void;
  onPlay?: () => void;
  onPause?: () => void;
  onEnded?: () => void;
  onError?: () => void;
  onTimeUpdate?: (time: number) => void;
  onVolumeChange?: (volume: number) => void;
  onSeeking?: () => void;
  onWaiting?: () => void;
  onLoadStart?: () => void;
  onLoadedData?: () => void;
  onCanPlay?: () => void;
  onCanPlayThrough?: () => void;
  onAbort?: () => void;
}): AudioController {
  const { speed } = audioSettings;

  const url = useMemo(
    () => {
      // Use download endpoint instead of streaming for better compatibility
      // This loads the entire audio segment at once, avoiding chunked streaming issues
      // Note: speed is handled via playbackRate in the audio element, not in the download
      const downloadUrl = api.audio.getDownloadUrl({
        recording,
        segment: { min: startTime, max: endTime },
        parameters: {
          resample: audioSettings.resample,
          samplerate: audioSettings.samplerate,
          low_freq: audioSettings.low_freq,
          high_freq: audioSettings.high_freq,
          filter_order: audioSettings.filter_order,
          channel: audioSettings.channel,
          speed: 1, // Speed is handled by playbackRate in the audio element
        },
      });
      console.log('Generated audio download URL:', downloadUrl);
      return downloadUrl;
    },
    [recording, startTime, endTime, audioSettings.resample, audioSettings.samplerate, audioSettings.low_freq, audioSettings.high_freq, audioSettings.filter_order, audioSettings.channel],
  );

  const handleTimeUpdate = useCallback(
    (time: number) => {
      onTimeUpdate?.(time * speed + startTime);
    },
    [onTimeUpdate, speed, startTime],
  );

  const audio = useAudio({
    url,
    playbackRate: speed,
    onTimeUpdate: handleTimeUpdate,
    ...handlers,
  });

  const seek = useCallback(
    (time: number) => {
      let adjustedTime = (time - startTime) / speed;
      audio.seek(adjustedTime);
      onSeek?.(time);
    },
    [audio, speed, startTime, onSeek],
  );

  return {
    recording,
    startTime,
    endTime,
    speed,
    currentTime: audio.currentTime * speed + startTime,
    volume: audio.volume,
    loop: audio.loop,
    isPlaying: audio.isPlaying,
    togglePlay: audio.togglePlay,
    play: audio.play,
    pause: audio.pause,
    stop: audio.stop,
    setVolume: audio.setVolume,
    toggleLoop: audio.toggleLoop,
    seek,
  };
}
