import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import TagSearchBar from "@/lib/components/tags/TagSearchBar";

import AnnotationProjectTags from "./AnnotationProjectTags";

const meta: Meta<typeof AnnotationProjectTags> = {
  title: "AnnotationProject/Tags",
  component: AnnotationProjectTags,
  args: {
    onDeleteTag: fn(),
    TagSearchBar: (
      <TagSearchBar
        onSelectTag={fn()}
        tags={[
          { key: "species", value: "Myotis myotis", canonical_name: "Myotis myotis" },
          { key: "species", value: "Tadarida brasiliensis", canonical_name: "Tadarida brasiliensis" },
          { key: "species", value: "Eptesicus fuscus", canonical_name: "Eptesicus fuscus" },
          { key: "species", value: "Nyctalus noctula", canonical_name: "Nyctalus noctula" },
          { key: "species", value: "Pipistrellus pipistrellus", canonical_name: "Pipistrellus pipistrellus" },
          { key: "species", value: "Eumops perotis", canonical_name: "Eumops perotis" },
        ]}
      />
    ),
  },
};

export default meta;

type Story = StoryObj<typeof AnnotationProjectTags>;

export const Empty: Story = {
  args: {
    annotationProject: {
      uuid: "1",
      name: "Project 1",
      description: "Annotation project 1",
      created_on: new Date(),
      visibility: "private" as const,
      created_by_id: "test-user-id",
      owner_group_id: null,
      tags: [],
    },
  },
};

export const WithTags: Story = {
  args: {
    annotationProject: {
      uuid: "1",
      name: "Project 1",
      description: "Annotation project 1",
      created_on: new Date(),
      visibility: "private" as const,
      created_by_id: "test-user-id",
      owner_group_id: null,
      tags: [
        { key: "species", value: "Myotis lucifugus", canonical_name: "Myotis lucifugus" },
        { key: "species", value: "Myotis septentrionalis", canonical_name: "Myotis septentrionalis" },
        { key: "event", value: "Echolocation", canonical_name: "Echolocation" },
      ],
    },
  },
};
