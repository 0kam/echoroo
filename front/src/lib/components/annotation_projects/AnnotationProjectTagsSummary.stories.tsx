import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import AnnotationProjectTagsSummary from "./AnnotationProjectTagsSummary";
import { makeAnnotationProject } from "./storyHelpers";

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
    annotationProject: makeAnnotationProject({ tags: [] }),
  },
};

export const Loading: Story = {
  args: {
    isLoading: true,
    annotationProject: makeAnnotationProject({ tags: [] }),
  },
};

export const WithProjectTags: Story = {
  args: {
    annotationProject: makeAnnotationProject({
      tags: [
        { key: "species", value: "Myotis lucifugus", canonical_name: "Myotis lucifugus" },
        { key: "species", value: "Myotis septentrionalis", canonical_name: "Myotis septentrionalis" },
        { key: "event", value: "Echolocation", canonical_name: "Echolocation" },
      ],
    }),
  },
};

export const WithAnnotations: Story = {
  args: {
    annotationProject: makeAnnotationProject({
      tags: [
        { key: "species", value: "Myotis lucifugus", canonical_name: "Myotis lucifugus" },
        { key: "species", value: "Myotis septentrionalis", canonical_name: "Myotis septentrionalis" },
        { key: "event", value: "Echolocation", canonical_name: "Echolocation" },
      ],
    }),
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
