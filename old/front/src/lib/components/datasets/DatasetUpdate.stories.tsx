import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import DatasetUpdateComponent from "./DatasetUpdate";
import { makeDataset } from "./storyHelpers";

const meta: Meta<typeof DatasetUpdateComponent> = {
  title: "Dataset/Update",
  component: DatasetUpdateComponent,
};

export default meta;

type Story = StoryObj<typeof DatasetUpdateComponent>;

export const Primary: Story = {
  args: {
    dataset: makeDataset(),
    onChangeDataset: fn(),
  },
};
