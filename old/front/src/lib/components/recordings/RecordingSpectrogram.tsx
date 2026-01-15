import { memo } from "react";

import Card from "@/lib/components/ui/Card";

const RecordingSpectrogram = memo(function RecordingSpectrogram(props: {
  ViewportToolbar?: JSX.Element;
  Player?: JSX.Element;
  SettingsMenu?: JSX.Element;
  ViewportBar?: JSX.Element;
  TimeScaleControl?: JSX.Element;
  FreqScaleControl?: JSX.Element;
  Canvas: JSX.Element;
}) {
  return (
    <Card>
      <div className="flex flex-row gap-4">
        {props.ViewportToolbar}
        {props.Player}
        {props.SettingsMenu}
      </div>
      {props.Canvas}
      {props.TimeScaleControl}
      {props.FreqScaleControl}
      {props.ViewportBar}
    </Card>
  );
});
export default RecordingSpectrogram;
