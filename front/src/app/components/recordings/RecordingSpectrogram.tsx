import { useCallback, useState } from "react";

import Player from "@/app/components/audio/Player";
import RecordingCanvas from "@/app/components/spectrograms/RecordingCanvas";
import SettingsMenu from "@/app/components/spectrograms/SettingsMenu";
import ViewportBar from "@/app/components/spectrograms/ViewportBar";
import ViewportToolbar from "@/app/components/spectrograms/ViewportToolbar";

import useSpectrogramHotkeys from "@/app/hooks/hotkeys/useSpectrogramHotkeys";
import useAudioSettings from "@/app/hooks/settings/useAudioSettings";
import useSpectrogramSettings from "@/app/hooks/settings/useSpectrogramSettings";

import RecordingSpectrogramBase from "@/lib/components/recordings/RecordingSpectrogram";
import FreqScaleControl from "@/lib/components/spectrograms/FreqScaleControl";
import TimeScaleControl from "@/lib/components/spectrograms/TimeScaleControl";

import useFreqScaleControl from "@/lib/hooks/spectrogram/useFreqScaleControl";
import useSpectrogramAudio from "@/lib/hooks/spectrogram/useSpectrogramAudio";
import useSpectrogramState from "@/lib/hooks/spectrogram/useSpectrogramState";
import useTimeScaleControl from "@/lib/hooks/spectrogram/useTimeScaleControl";
import useRecordingViewport from "@/lib/hooks/window/useRecordingViewport";

import Button from "@/lib/components/ui/Button";
import Spinner from "@/lib/components/ui/Spinner";
import type { Recording, SpectrogramProps, SpectrogramWindow } from "@/lib/types";
import type { ChunkState } from "@/lib/hooks/spectrogram/useSpectrogramChunksState";
import { intervalIntersection } from "@/lib/utils/geometry";

export default function RecordingSpectrogram({
  recording,
  ...props
}: {
  recording: Recording;
} & SpectrogramProps) {
  const state = useSpectrogramState();

  const audioSettings = useAudioSettings();

  const spectrogramSettings = useSpectrogramSettings();

  const [refreshToken, setRefreshToken] = useState(0);
  const [appliedAudioSettings, setAppliedAudioSettings] = useState(
    () => audioSettings.settings,
  );
  const [appliedSpectrogramSettings, setAppliedSpectrogramSettings] = useState(
    () => spectrogramSettings.settings,
  );
  const [isGenerating, setIsGenerating] = useState(false);
  const [hasGenerationError, setHasGenerationError] = useState(false);

  const viewport = useRecordingViewport({
    recording,
    spectrogramSettings: appliedSpectrogramSettings,
    audioSettings: appliedAudioSettings,
  });

  const audio = useSpectrogramAudio({
    viewport,
    recording,
    audioSettings: audioSettings.settings,
  });

  const {
    withControls = true,
    withViewportBar = true,
    withHotKeys = true,
  } = props;

  const handleRegenerate = useCallback(() => {
    setAppliedAudioSettings(audioSettings.settings);
    setAppliedSpectrogramSettings(spectrogramSettings.settings);
    setRefreshToken((token) => token + 1);
    setIsGenerating(true);
    setHasGenerationError(false);
  }, [audioSettings.settings, spectrogramSettings.settings]);

  const handleSegmentsChange = useCallback(
    (segments: ChunkState[], currentViewport: SpectrogramWindow) => {
      if (segments.length === 0) {
        setIsGenerating(true);
        setHasGenerationError(false);
        return;
      }

      const visibleSegments = segments.filter(
        (segment) =>
          intervalIntersection(segment.interval, currentViewport.time) != null,
      );

      if (visibleSegments.length === 0) {
        setIsGenerating(true);
        setHasGenerationError(false);
        return;
      }

      const hasError = visibleSegments.some((segment) => segment.isError);
      setHasGenerationError(hasError);

      const allVisibleComplete = visibleSegments.every(
        (segment) => segment.isReady || segment.isError,
      );

      setIsGenerating(!allVisibleComplete);
    },
    [],
  );

  useSpectrogramHotkeys({
    spectrogramState: state,
    audio,
    viewport,
    enabled: withHotKeys,
  });

  const timeScaleControl = useTimeScaleControl({
    viewport,
    spectrogramSettings,
    playbackSpeed: audioSettings.settings.speed,
  });

  const freqScaleControl = useFreqScaleControl({
    viewport,
    spectrogramSettings,
  });

  const canvasHeight =
    props.height ?? appliedSpectrogramSettings.height ?? 400;

  return (
    <RecordingSpectrogramBase
      ViewportToolbar={
        withControls ? (
          <div className="flex items-center gap-3">
            <Button
              onClick={handleRegenerate}
              disabled={isGenerating}
            >
              Re-generate Spectrogram
            </Button>
            {isGenerating ? (
              <div className="flex items-center gap-2 text-sm text-stone-500">
                <Spinner className="h-5 w-5" />
                <span>Generating...</span>
              </div>
            ) : hasGenerationError ? (
              <span className="text-sm text-rose-600">
                Failed to render. Please try again.
              </span>
            ) : null}
            <ViewportToolbar
              state={state}
              viewport={viewport}
            />
          </div>
        ) : undefined
      }
      TimeScaleControl={
        withControls ? (
          <TimeScaleControl
            value={timeScaleControl.value}
            onChange={timeScaleControl.onPreviewChange}
            onChangeEnd={timeScaleControl.onCommit}
          />
        ) : undefined
      }
      FreqScaleControl={
        withControls ? (
          <FreqScaleControl
            value={freqScaleControl.value}
            onChange={freqScaleControl.onPreviewChange}
            onChangeEnd={freqScaleControl.onCommit}
          />
        ) : undefined
      }
      Player={
        withControls ? (
          <Player
            audio={audio}
            samplerate={recording.samplerate}
            onChangeSpeed={(speed) =>
              audioSettings.dispatch({ type: "setSpeed", speed })
            }
          />
        ) : undefined
      }
      SettingsMenu={
        withControls ? (
          <SettingsMenu
            samplerate={recording.samplerate}
            audioSettings={audioSettings}
            spectrogramSettings={spectrogramSettings}
          />
        ) : undefined
      }
      ViewportBar={
        withViewportBar ? <ViewportBar viewport={viewport} /> : undefined
      }
      Canvas={
        <RecordingCanvas
          audioSettings={appliedAudioSettings}
          spectrogramSettings={appliedSpectrogramSettings}
          state={state}
          recording={recording}
          audio={audio}
          viewport={viewport}
          height={canvasHeight}
          refreshToken={refreshToken}
          onSegmentsChange={handleSegmentsChange}
        />
      }
    />
  );
}
