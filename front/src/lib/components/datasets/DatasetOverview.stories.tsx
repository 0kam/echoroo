import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import DatasetOverview from "./DatasetOverview";
import { makeDataset } from "./storyHelpers";

const meta: Meta<typeof DatasetOverview> = {
  title: "Dataset/Overview",
  component: DatasetOverview,
};

export default meta;

type Story = StoryObj<typeof DatasetOverview>;

export const Primary: Story = {
  args: {
    dataset: makeDataset(),
    onClickDatasetRecordings: fn(),
  },
};
