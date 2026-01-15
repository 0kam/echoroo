import PlayerBase from "@/lib/components/audio/Player";

import type { SpeedOption } from "@/lib/hooks/settings/useAudioSettings";
import type { AudioController } from "@/lib/types";

// All available speed options
const ALL_SPEED_OPTIONS: SpeedOption[] = [
  { label: "1x", value: 1 },
  { label: "1.2x", value: 1.2 },
  { label: "1.5x", value: 1.5 },
  { label: "1.75x", value: 1.75 },
  { label: "2x", value: 2 },
  { label: "3x", value: 3 },
  { label: "0.75x", value: 0.75 },
  { label: "0.5x", value: 0.5 },
  { label: "0.25x", value: 0.25 },
  { label: "0.1x", value: 0.1 },
];

export default function Player({
  audio,
  samplerate,
  onChangeSpeed,
}: {
  audio: AudioController;
  samplerate: number;
  onChangeSpeed?: (speed: number) => void;
}) {
  // Always show all speed options since we handle resampling dynamically
  // in useSpectrogramAudio to keep effective samplerate within browser limits
  return (
    <PlayerBase
      currentTime={audio.currentTime}
      startTime={audio.startTime}
      endTime={audio.endTime}
      isPlaying={audio.isPlaying}
      loop={audio.loop}
      speed={audio.speed}
      speedOptions={ALL_SPEED_OPTIONS}
      onPlay={audio.play}
      onPause={audio.pause}
      onSeek={audio.seek}
      onToggleLoop={audio.toggleLoop}
      onChangeSpeed={onChangeSpeed}
    />
  );
}
