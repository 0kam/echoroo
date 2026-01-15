import { type Control, Controller } from "react-hook-form";

import Slider from "@/lib/components/inputs/Slider";
import { Group } from "@/lib/components/inputs/index";

import type { SpectrogramSettings } from "@/lib/types";

import SettingsSection from "./SettingsSection";

const MIN_CANVAS_HEIGHT = 200;
const MAX_CANVAS_HEIGHT = 1200;

export default function DisplaySettings({
  control,
}: {
  control: Control<SpectrogramSettings>;
}) {
  return (
    <SettingsSection>
      <Controller
        name="height"
        control={control}
        render={({ field, fieldState }) => (
          <Group
            name="canvasHeight"
            label="Canvas height"
            help="Set the vertical size (in pixels) used when rendering spectrograms."
            error={fieldState.error?.message}
          >
            <Slider
              label="Height"
              value={field.value}
              onChange={field.onChange}
              minValue={MIN_CANVAS_HEIGHT}
              maxValue={MAX_CANVAS_HEIGHT}
              step={20}
              formatter={(value) => `${Math.round(value)} px`}
            />
          </Group>
        )}
      />
    </SettingsSection>
  );
}
