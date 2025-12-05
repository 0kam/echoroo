import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import AnnotationProjectUpdate from "./AnnotationProjectUpdate";
import { makeAnnotationProject } from "./storyHelpers";

const meta: Meta<typeof AnnotationProjectUpdate> = {
  title: "AnnotationProject/Update",
  component: AnnotationProjectUpdate,
};

export default meta;

type Story = StoryObj<typeof AnnotationProjectUpdate>;

export const Primary: Story = {
  args: {
    annotationProject: makeAnnotationProject(),
    onChangeAnnotationProject: fn(),
  },
};
