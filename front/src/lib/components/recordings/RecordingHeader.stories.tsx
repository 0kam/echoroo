import type { Meta, StoryObj } from "@storybook/react";

import RecordingHeader from "@/lib/components/recordings/RecordingHeader";

const meta: Meta<typeof RecordingHeader> = {
  title: "Recordings/Header",
  component: RecordingHeader,
};

export default meta;

type Story = StoryObj<typeof RecordingHeader>;

const recording = {
  path: "path/to/recording.wav",
  uuid: "uuid",
  hash: "hash",
  duration: 10,
  samplerate: 44100,
  channels: 1,
  time_expansion: 1,
  datetime_parse_status: "pending" as const,
  created_on: new Date(),
};

export const Primary: Story = {
  args: {
    recording,
  },
};

export const WithDatetime: Story = {
  args: {
    recording: {
      ...recording,
      datetime: new Date(),
      datetime_parse_status: "success" as const,
    },
  },
};

export const WithDatetimeFailed: Story = {
  args: {
    recording: {
      ...recording,
      datetime_parse_status: "failed" as const,
      datetime_parse_error: "Could not parse datetime from filename",
    },
  },
};

export const WithH3Index: Story = {
  args: {
    recording: {
      ...recording,
      h3_index: "8c2a100d2c5cdff", // Example H3 index
    },
  },
};

export const WithLegacyLocation: Story = {
  args: {
    recording: {
      ...recording,
      latitude: 35.6812,
      longitude: 139.7671,
    },
  },
};

export const FlacFile: Story = {
  args: {
    recording: {
      ...recording,
      path: "path/to/recording.flac",
    },
  },
};
