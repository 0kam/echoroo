import type { Meta, StoryObj } from "@storybook/react";

import RecordingMediaInfo from "@/lib/components/recordings/RecordingMediaInfo";

const meta: Meta<typeof RecordingMediaInfo> = {
  title: "Recordings/MediaInfo",
  component: RecordingMediaInfo,
};

export default meta;

type Story = StoryObj<typeof RecordingMediaInfo>;

export const Primary: Story = {
  args: {
    recording: {
      uuid: "uuid",
      hash: "hash",
      path: "path.wav",
      duration: 10,
      samplerate: 44100,
      channels: 1,
      time_expansion: 1,
      datetime_parse_status: "pending",
      created_on: new Date(),
    },
  },
};

export const WithBitDepth: Story = {
  args: {
    recording: {
      uuid: "uuid",
      hash: "hash",
      path: "path.wav",
      duration: 10,
      samplerate: 44100,
      channels: 2,
      time_expansion: 1,
      bit_depth: 24,
      datetime_parse_status: "pending",
      created_on: new Date(),
    },
  },
};

export const WithRights: Story = {
  args: {
    recording: {
      uuid: "uuid",
      hash: "hash",
      path: "path.wav",
      duration: 10,
      samplerate: 44100,
      channels: 1,
      time_expansion: 1,
      bit_depth: 16,
      rights: "CC BY-NC 4.0",
      datetime_parse_status: "pending",
      created_on: new Date(),
    },
  },
};

export const FullMetadata: Story = {
  args: {
    recording: {
      uuid: "uuid",
      hash: "hash",
      path: "path.wav",
      duration: 125.5,
      samplerate: 96000,
      channels: 2,
      time_expansion: 10,
      bit_depth: 32,
      rights: "Creative Commons Attribution 4.0 International License",
      datetime_parse_status: "pending",
      created_on: new Date(),
    },
  },
};
