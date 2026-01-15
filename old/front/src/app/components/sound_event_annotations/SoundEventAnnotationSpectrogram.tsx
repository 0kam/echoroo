import Player from "@/app/components/audio/Player";
import SettingsMenu from "@/app/components/spectrograms/SettingsMenu";
import SoundEventAnnotationCanvas from "@/app/components/spectrograms/SoundEventAnnotationCanvas";
import ViewportBar from "@/app/components/spectrograms/ViewportBar";
import ViewportToolbar from "@/app/components/spectrograms/ViewportToolbar";

import useSoundEventAnnotation from "@/app/hooks/api/useSoundEventAnnotation";
import useSpectrogramHotkeys from "@/app/hooks/hotkeys/useSpectrogramHotkeys";
import useAudioSettings from "@/app/hooks/settings/useAudioSettings";
import useSpectrogramSettings from "@/app/hooks/settings/useSpectrogramSettings";

import Error from "@/app/error";

import ClipAnnotationSpectrogramBase from "@/lib/components/clip_annotations/ClipAnnotationSpectrogram";
import Loading from "@/lib/components/ui/Loading";
import FreqScaleControl from "@/lib/components/spectrograms/FreqScaleControl";
import TimeScaleControl from "@/lib/components/spectrograms/TimeScaleControl";

import useFreqScaleControl from "@/lib/hooks/spectrogram/useFreqScaleControl";
import useSpectrogramAudio from "@/lib/hooks/spectrogram/useSpectrogramAudio";
import useSpectrogramState from "@/lib/hooks/spectrogram/useSpectrogramState";
import useTimeScaleControl from "@/lib/hooks/spectrogram/useTimeScaleControl";
import useSoundEventViewport from "@/lib/hooks/window/useSoundEventViewport";

import type { Recording, SoundEventAnnotation } from "@/lib/types";

type SoundEventAnnotationProps = {
  height?: number;
  withAnnotationControls?: boolean;
  withAnnotations?: boolean;
  withControls?: boolean;
  withViewportBar?: boolean;
  withHotKeys?: boolean;
  withPlayer?: boolean;
  withSoundEvents?: boolean;
  enabled?: boolean;
  context?: number;
};

export default function SoundEventAnnotationSpectrogram({
  soundEventAnnotation,
  ...props
}: {
  soundEventAnnotation: SoundEventAnnotation;
} & SoundEventAnnotationProps) {
  const { data = soundEventAnnotation, recording } = useSoundEventAnnotation({
    uuid: soundEventAnnotation.uuid,
    soundEventAnnotation,
    withRecording: true,
  });

  if (recording.isLoading) {
    return <Loading />;
  }

  if (recording.data == null) {
    return <Error error={recording.error || undefined} />;
  }

  return (
    <Inner soundEventAnnotation={data} recording={recording.data} {...props} />
  );
}

function Inner({
  soundEventAnnotation,
  recording,
  height,
  withAnnotations = true,
  withPlayer = true,
  withControls = true,
  withViewportBar = true,
  withHotKeys = true,
  enabled = false,
}: {
  soundEventAnnotation: SoundEventAnnotation;
  recording: Recording;
} & SoundEventAnnotationProps) {
  const audioSettings = useAudioSettings();

  const spectrogramSettings = useSpectrogramSettings();

  const spectrogramState = useSpectrogramState();

  const viewport = useSoundEventViewport({
    soundEvent: soundEventAnnotation.sound_event,
    recording,
    audioSettings: audioSettings.settings,
  });

  const audio = useSpectrogramAudio({
    viewport,
    recording,
    audioSettings: audioSettings.settings,
  });

  useSpectrogramHotkeys({
    audio,
    viewport,
    spectrogramState,
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
    height ?? spectrogramSettings.settings.height ?? 400;

  return (
    <ClipAnnotationSpectrogramBase
      ViewportToolbar={
        withControls ? (
          <ViewportToolbar
            state={spectrogramState}
            viewport={viewport}
          />
        ) : undefined
      }
      Player={
        withPlayer ? (
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
      ViewportBar={
        withViewportBar ? <ViewportBar viewport={viewport} /> : undefined
      }
      Canvas={
        <SoundEventAnnotationCanvas
          height={canvasHeight}
          soundEventAnnotation={soundEventAnnotation}
          audioSettings={audioSettings.settings}
          spectrogramSettings={spectrogramSettings.settings}
          spectrogramState={spectrogramState}
          recording={recording}
          audio={audio}
          viewport={viewport}
          withAnnotations={withAnnotations}
          enabled={enabled}
        />
      }
    />
  );
}
