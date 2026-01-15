import { useCallback, useState } from "react";

import Player from "@/app/components/audio/Player";
import SelectedSoundEventAnnotation from "@/app/components/sound_event_annotations/SelectedSoundEventAnnotation";
import ClipAnnotationCanvas from "@/app/components/spectrograms/ClipAnnotationCanvas";
import SettingsMenu from "@/app/components/spectrograms/SettingsMenu";
import ViewportBar from "@/app/components/spectrograms/ViewportBar";
import ViewportToolbar from "@/app/components/spectrograms/ViewportToolbar";

import useClipAnnotation from "@/app/hooks/api/useClipAnnotation";
import useAnnotationHotkeys from "@/app/hooks/hotkeys/useAnnotationHotkeys";
import useSpectrogramHotkeys from "@/app/hooks/hotkeys/useSpectrogramHotkeys";
import useAudioSettings from "@/app/hooks/settings/useAudioSettings";
import useSpectrogramSettings from "@/app/hooks/settings/useSpectrogramSettings";

import AnnotationControls from "@/lib/components/annotation/AnnotationControls";
import ClipAnnotationSpectrogramBase from "@/lib/components/clip_annotations/ClipAnnotationSpectrogram";
import Empty from "@/lib/components/ui/Empty";
import Button from "@/lib/components/ui/Button";
import Spinner from "@/lib/components/ui/Spinner";
import FreqScaleControl from "@/lib/components/spectrograms/FreqScaleControl";
import TimeScaleControl from "@/lib/components/spectrograms/TimeScaleControl";

import useAnnotationState from "@/lib/hooks/annotation/useAnnotationState";
import useAnnotationTagPallete from "@/lib/hooks/annotation/useAnnotationTagPalette";
import type { ChunkState } from "@/lib/hooks/spectrogram/useSpectrogramChunksState";
import useFreqScaleControl from "@/lib/hooks/spectrogram/useFreqScaleControl";
import useSpectrogramAudio from "@/lib/hooks/spectrogram/useSpectrogramAudio";
import useSpectrogramState from "@/lib/hooks/spectrogram/useSpectrogramState";
import useTimeScaleControl from "@/lib/hooks/spectrogram/useTimeScaleControl";
import useClipViewport from "@/lib/hooks/window/useClipViewport";

import type { ClipAnnotation, SpectrogramWindow, Tag } from "@/lib/types";
import { intervalIntersection } from "@/lib/utils/geometry";

import ProjectTagSearch from "../tags/ProjectTagsSearch";

export default function ClipAnnotationSpectrogram({
  clipAnnotation,
  spectrogramSettings,
  audioSettings,
  tagPalette,
  availableTags = [],
  height,
}: {
  clipAnnotation: ClipAnnotation;
  spectrogramSettings: ReturnType<typeof useSpectrogramSettings>;
  audioSettings: ReturnType<typeof useAudioSettings>;
  tagPalette: ReturnType<typeof useAnnotationTagPallete>;
  availableTags?: Tag[];
  height?: number;
}) {
  const { data = clipAnnotation } = useClipAnnotation({
    uuid: clipAnnotation.uuid,
    clipAnnotation,
  });

  const spectrogramState = useSpectrogramState();

  const annotationState = useAnnotationState({ spectrogramState });

  const [refreshToken, setRefreshToken] = useState(0);
  const [appliedAudioSettings, setAppliedAudioSettings] = useState(
    () => audioSettings.settings,
  );
  const [appliedSpectrogramSettings, setAppliedSpectrogramSettings] = useState(
    () => spectrogramSettings.settings,
  );
  const [isGenerating, setIsGenerating] = useState(false);
  const [hasGenerationError, setHasGenerationError] = useState(false);

  const viewport = useClipViewport({
    clip: data.clip,
    spectrogramSettings: appliedSpectrogramSettings,
    audioSettings: appliedAudioSettings,
  });

  const audio = useSpectrogramAudio({
    viewport,
    recording: data.clip.recording,
    audioSettings: audioSettings.settings,
  });

  useSpectrogramHotkeys({
    spectrogramState,
    audio,
    viewport,
  });

  useAnnotationHotkeys({
    annotationState,
    audio,
    viewport,
    spectrogramState,
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

  const canvasHeight = height ?? appliedSpectrogramSettings.height ?? 400;

  return (
    <ClipAnnotationSpectrogramBase
      ViewportToolbar={
        <div className="flex items-center gap-3">
          <Button onClick={handleRegenerate} disabled={isGenerating}>
            Re-generate Spectrogram
          </Button>
          {isGenerating ? (
            <div className="flex items-center gap-2 text-sm text-stone-500">
              <Spinner className="h-4 w-4" />
              <span>Generating…</span>
            </div>
          ) : hasGenerationError ? (
            <span className="text-sm text-rose-600">
              Failed to render. Please try again.
            </span>
          ) : null}
          <ViewportToolbar
            state={spectrogramState}
            viewport={viewport}
          />
        </div>
      }
      Player={
        <Player
          audio={audio}
          samplerate={data.clip.recording.samplerate}
          onChangeSpeed={(speed) =>
            audioSettings.dispatch({ type: "setSpeed", speed })
          }
        />
      }
      SettingsMenu={
        <SettingsMenu
          samplerate={data.clip.recording.samplerate}
          audioSettings={audioSettings}
          spectrogramSettings={spectrogramSettings}
        />
      }
      ViewportBar={<ViewportBar viewport={viewport} />}
      TimeScaleControl={
        <TimeScaleControl
          value={timeScaleControl.value}
          onChange={timeScaleControl.onPreviewChange}
          onChangeEnd={timeScaleControl.onCommit}
        />
      }
      FreqScaleControl={
        <FreqScaleControl
          value={freqScaleControl.value}
          onChange={freqScaleControl.onPreviewChange}
          onChangeEnd={freqScaleControl.onCommit}
        />
      }
      AnnotationControls={
        <AnnotationControls
          mode={annotationState.mode}
          geometryType={annotationState.geometryType}
          onDraw={annotationState.enableDrawing}
          onDelete={annotationState.enableDeleting}
          onSelect={annotationState.enableSelecting}
          onSelectGeometryType={annotationState.setGeometryType}
        />
      }
      Canvas={
        <ClipAnnotationCanvas
          height={canvasHeight}
          clipAnnotation={data}
          audioSettings={appliedAudioSettings}
          spectrogramSettings={appliedSpectrogramSettings}
          spectrogramState={spectrogramState}
          annotationState={annotationState}
          recording={data.clip.recording}
          audio={audio}
          viewport={viewport}
          defaultTags={tagPalette.tags}
          refreshToken={refreshToken}
          onSegmentsChange={handleSegmentsChange}
          availableTags={availableTags}
          tagSearchComponent={ProjectTagSearch}
        />
      }
      SelectedSoundEvent={
        annotationState.selectedAnnotation != null ? (
          <SelectedSoundEventAnnotation
            soundEventAnnotation={annotationState.selectedAnnotation}
          />
        ) : (
          <Empty>
            No annotation selected, click on an annotation to view details
          </Empty>
        )
      }
    />
  );
}
