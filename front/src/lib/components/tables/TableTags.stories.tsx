import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import TagSearchBar, {
  type TagSearchBarProps,
} from "@/lib/components/tags/TagSearchBar";

import type { Tag } from "@/lib/types";

import TableTags from "./TableTags";

const meta: Meta<typeof TableTags> = {
  title: "Table/Tags",
  component: TableTags,
  parameters: {
    controls: {
      exclude: [
        "TagSearchBar",
        "tagColorFn",
        "onBlur",
        "onKeyDown",
        "placement",
        "autoPlacement",
      ],
    },
  },
};

export default meta;

type Story = StoryObj<typeof TableTags>;

const tags: Tag[] = [
  { key: "species", value: "Myotis myotis", canonical_name: "Myotis myotis" },
  { key: "species", value: "Myotis blythii", canonical_name: "Myotis blythii" },
  { key: "species", value: "Myotis capaccinii", canonical_name: "Myotis capaccinii" },
  { key: "species", value: "Myotis emarginatus", canonical_name: "Myotis emarginatus" },
];

const props = {
  onClickTag: fn(),
  onDeleteTag: fn(),
  onCreateTag: fn(),
  TagSearchBar: (props: TagSearchBarProps) => (
    <TagSearchBar tags={tags} {...props} />
  ),
};

export const Empty: Story = {
  args: {
    tags: [],
    ...props,
  },
};

export const WithTags: Story = {
  args: {
    tags: [
      {
        key: "species",
        value: "Myotis myotis",
        canonical_name: "Myotis myotis",
      },
      {
        key: "event",
        value: "Echolocation",
        canonical_name: "Echolocation",
      },
    ],
    ...props,
  },
};

// 20 random tags
const randomTags = Array(20)
  .fill(0)
  .map((_, i) => ({
    key: `tag${i}`,
    value: `value${i}`,
    canonical_name: `value${i}`,
  }));

export const WithManyTags: Story = {
  args: {
    tags: randomTags,
    ...props,
  },
};
