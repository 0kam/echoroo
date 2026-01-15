import type { Meta, StoryObj } from "@storybook/react";

import DatasetRecordingsSummary from "./DatasetRecordingsSummary";
import { makeDataset } from "./storyHelpers";

const meta: Meta<typeof DatasetRecordingsSummary> = {
  title: "Dataset/RecordingsSummary",
  component: DatasetRecordingsSummary,
};

export default meta;

type Story = StoryObj<typeof DatasetRecordingsSummary>;

export const Primary: Story = {
  args: {
    dataset: makeDataset({ recording_count: 10 }),
  },
};
