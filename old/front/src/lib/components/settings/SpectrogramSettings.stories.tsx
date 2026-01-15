import type { Meta, StoryObj } from "@storybook/react";

import SpectrogramSettings from "@/lib/components/settings/SpectrogramSettings";

const meta: Meta<typeof SpectrogramSettings> = {
  title: "Settings/SpectrogramsSettings",
  component: SpectrogramSettings,
};

export default meta;

type Story = StoryObj<typeof SpectrogramSettings>;

export const Primary: Story = {
  args: {
    settings: {
      window_size: 1024,
      overlap: 256,
      window: "hann",
      scale: "dB",
      height: 400,
      clamp: false,
      min_dB: -80,
      max_dB: 0,
      normalize: true,
      pcen: false,
      cmap: "viridis",
      time_scale: 1,
      freq_scale: 1,
    },
    samplerate: 44100,
  },
};
