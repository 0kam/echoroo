import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import { type Dataset } from "@/lib/types";

import DatasetDetail from "./DatasetDetail";
import DatasetNotesSummary from "./DatasetNotesSummary";
import DatasetOverview from "./DatasetOverview";
import DatasetUpdate from "./DatasetUpdate";
import { makeDataset } from "./storyHelpers";

const meta: Meta<typeof DatasetDetail> = {
  title: "Dataset/Detail",
  component: DatasetDetail,
  parameters: {
    controls: {
      exclude: [
        "DatasetUpdate",
        "DatasetOverview",
        "DatasetNotesSummary",
      ],
    },
  },
};

export default meta;

type Story = StoryObj<typeof DatasetDetail>;

const dataset: Dataset = makeDataset();

export const Primary: Story = {
  args: {
    DatasetUpdate: <DatasetUpdate dataset={dataset} />,
    DatasetOverview: (
      <DatasetOverview dataset={dataset} onClickDatasetRecordings={fn()} />
    ),
    DatasetNotesSummary: <DatasetNotesSummary notes={[]} onClickNote={fn()} />,
  },
};
