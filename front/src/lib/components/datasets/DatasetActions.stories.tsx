import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import DatasetActions from "./DatasetActions";

const meta: Meta<typeof DatasetActions> = {
  title: "Dataset/Actions",
  component: DatasetActions,
};

export default meta;

type Story = StoryObj<typeof DatasetActions>;

export const Primary: Story = {
  args: {
    dataset: {
      uuid: "123",
      name: "Test Dataset",
      description: "This is a test dataset.",
      audio_dir: "/path/to/audio",
      recording_count: 0,
      created_on: new Date(),
      visibility: "private" as const,
      created_by_id: "test-user-id",
      owner_group_id: null,
    },
    onDownloadDataset: fn(),
    onDeleteDataset: fn(),
  },
};
