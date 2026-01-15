import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import DatasetActions from "./DatasetActions";
import { makeDataset } from "./storyHelpers";

const meta: Meta<typeof DatasetActions> = {
  title: "Dataset/Actions",
  component: DatasetActions,
};

export default meta;

type Story = StoryObj<typeof DatasetActions>;

export const Primary: Story = {
  args: {
    dataset: makeDataset(),
    onDeleteDataset: fn(),
  },
};
