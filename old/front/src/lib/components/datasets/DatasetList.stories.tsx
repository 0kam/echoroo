import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";
import { loremIpsum } from "lorem-ipsum";

import { DatasetIcon } from "@/lib/components/icons";
import Search from "@/lib/components/inputs/Search";
import Pagination from "@/lib/components/lists/Pagination";

import DatasetList from "./DatasetList";
import { makeDataset } from "./storyHelpers";

const meta: Meta<typeof DatasetList> = {
  title: "Dataset/List",
  component: DatasetList,
  args: {
    onClickDataset: fn(),
    Pagination: <Pagination />,
    DatasetSearch: (
      <Search
        label="Search"
        placeholder="Search dataset..."
        icon={<DatasetIcon />}
      />
    ),
  },
};

export default meta;

type Story = StoryObj<typeof DatasetList>;

export const Empty: Story = {
  args: {
    datasets: [],
  },
};

export const WithDatasets: Story = {
  args: {
    datasets: [
      makeDataset({
        uuid: "dataset-1",
        name: "Test Dataset",
        recording_count: 1201,
      }),
      makeDataset({
        uuid: "dataset-2",
        name: "Another Dataset",
        recording_count: 0,
        visibility: "restricted",
      }),
      makeDataset({
        uuid: "dataset-3",
        name: "Dataset with a very Long Name describing the Year of Collection and Location as well as mentioning the Institutions involved.",
        recording_count: 640,
      }),
      makeDataset({
        uuid: "dataset-4",
        name: "Dataset",
        description: loremIpsum({
          count: 4,
          units: "paragraphs",
          suffix: "\n\n",
        }),
        recording_count: 540,
      }),
    ],
  },
};
