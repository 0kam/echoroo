import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import type { Tag } from "@/lib/types";

import TagSearchBar from "./TagSearchBar";

const meta: Meta<typeof TagSearchBar> = {
  title: "Tags/Search",
  component: TagSearchBar,
};

export default meta;

type Story = StoryObj<typeof TagSearchBar>;

export const Primary: Story = {
  args: {
    tags: [
      { key: "species", value: "Tadarida brasiliensis", canonical_name: "Tadarida brasiliensis" },
      { key: "species", value: "Myotis myotis", canonical_name: "Myotis myotis" },
      { key: "event", value: "Echolocation", canonical_name: "Echolocation" },
    ] as Tag[],
    onSelectTag: fn(),
    onCreateTag: fn(),
    onChangeQuery: fn(),
    canCreate: true,
  },
};
