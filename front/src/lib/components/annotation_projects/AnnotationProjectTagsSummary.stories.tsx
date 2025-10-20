import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import AnnotationProjectTagsSummary from "./AnnotationProjectTagsSummary";

const meta: Meta<typeof AnnotationProjectTagsSummary> = {
  title: "AnnotationProject/TagsSummary",
  component: AnnotationProjectTagsSummary,
  args: {
    onAddTags: fn(),
  },
};

export default meta;

type Story = StoryObj<typeof AnnotationProjectTagsSummary>;

export const NoTags: Story = {
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

export const Loading: Story = {
  args: {
    isLoading: true,
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

export const WithProjectTags: Story = {
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

export const WithAnnotations: Story = {
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
    clipTags: [
      {
        tag: { key: "species", value: "Myotis lucifugus", canonical_name: "Myotis lucifugus" },
        count: 1,
      },
      {
        tag: { key: "event", value: "Echolocation", canonical_name: "Echolocation" },
        count: 2,
      },
      {
        tag: { key: "species", value: "Myotis septentrionalis", canonical_name: "Myotis septentrionalis" },
        count: 3,
      },
    ],
    soundEventTags: [
      {
        tag: { key: "species", value: "Myotis septentrionalis", canonical_name: "Myotis septentrionalis" },
        count: 10,
      },
      {
        tag: { key: "event", value: "Echolocation", canonical_name: "Echolocation" },
        count: 2,
      },
    ],
  },
};
