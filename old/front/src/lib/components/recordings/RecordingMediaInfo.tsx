import {
  BitDepthIcon,
  ChannelsIcon,
  RightsIcon,
  SampleRateIcon,
  TimeExpansionIcon,
  TimeIcon,
} from "@/lib/components/icons";
import Card from "@/lib/components/ui/Card";

import type { Recording } from "@/lib/types";

function Label({ label }: { label: string }) {
  return <div className="mr-2 text-sm font-thin text-stone-500">{label}</div>;
}

function Units({ units }: { units: string }) {
  return <span className="ml-1 text-stone-500">{units}</span>;
}

export default function RecordingMediaInfo({
  recording,
}: {
  recording: Recording;
}) {
  return (
    <Card>
      <div className="inline-flex items-center">
        <TimeIcon className="inline-block mr-1 w-5 h-5 text-stone-500" />
        <Label label="Duration" />
        {recording.duration.toFixed(3)}
        <Units units="s" />
      </div>
      <div className="inline-flex items-center">
        <ChannelsIcon className="inline-block mr-1 w-5 h-5 text-stone-500" />
        <Label label="Channels" />
        {recording.channels}
      </div>
      <div className="inline-flex items-center">
        <SampleRateIcon className="inline-block mr-1 w-5 h-5 text-stone-500" />
        <Label label="Sample rate" />
        {recording.samplerate.toLocaleString()}
        <Units units="Hz" />
      </div>
      {recording.bit_depth != null && (
        <div className="inline-flex items-center">
          <BitDepthIcon className="inline-block mr-1 w-5 h-5 text-stone-500" />
          <Label label="Bit depth" />
          {recording.bit_depth}
          <Units units="bit" />
        </div>
      )}
      <div className="inline-flex items-center">
        <TimeExpansionIcon className="inline-block mr-1 w-5 h-5 text-stone-500" />
        <Label label="Time expansion" />
        {recording.time_expansion}
      </div>
      {recording.rights && (
        <div className="inline-flex items-center">
          <RightsIcon className="inline-block mr-1 w-5 h-5 text-stone-500" />
          <Label label="Rights" />
          <span className="text-sm truncate max-w-[200px]" title={recording.rights}>
            {recording.rights}
          </span>
        </div>
      )}
    </Card>
  );
}
