import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";
import { loremIpsum } from "lorem-ipsum";

import AnnotationProject from "./AnnotationProject";
import { makeAnnotationProject } from "./storyHelpers";

const meta: Meta<typeof AnnotationProject> = {
  title: "AnnotationProject/Item",
  component: AnnotationProject,
};

export default meta;

type Story = StoryObj<typeof AnnotationProject>;

export const Primary: Story = {
  args: {
    annotationProject: makeAnnotationProject({
      uuid: "123",
      name: "Test Project",
      description: loremIpsum({ count: 2 }),
    }),
    onClickAnnotationProject: fn(),
  },
};
