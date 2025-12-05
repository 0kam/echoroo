import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";
import { loremIpsum } from "lorem-ipsum";

import Dataset from "./Dataset";
import { makeDataset } from "./storyHelpers";

const meta: Meta<typeof Dataset> = {
  title: "Dataset/Item",
  component: Dataset,
};

export default meta;

type Story = StoryObj<typeof Dataset>;

export const Primary: Story = {
  args: {
    dataset: makeDataset(),
    onClickDataset: fn(),
  },
};

export const WithRecordings: Story = {
  args: {
    dataset: makeDataset({ recording_count: 1201 }),
    onClickDataset: fn(),
  },
};

export const WithLongName: Story = {
  args: {
    dataset: makeDataset({
      name: "Audio Dataset with a very Long Name describing the Year of Collection and Location as well as mentioning the Institutions involved.",
      recording_count: 1201,
    }),
    onClickDataset: fn(),
  },
};

export const WithLongDescription: Story = {
  args: {
    dataset: makeDataset({
      name: "Dataset",
      description: loremIpsum({
        count: 4,
        units: "paragraphs",
        suffix: "\n\n",
      }),
      recording_count: 1201,
      visibility: "restricted",
    }),
    onClickDataset: fn(),
  },
};
