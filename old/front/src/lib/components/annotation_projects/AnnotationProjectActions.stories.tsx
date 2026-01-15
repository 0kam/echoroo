import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";

import AnnotationProjectActions from "./AnnotationProjectActions";
import { makeAnnotationProject } from "./storyHelpers";

const meta: Meta<typeof AnnotationProjectActions> = {
  title: "AnnotationProject/Actions",
  component: AnnotationProjectActions,
};

export default meta;

type Story = StoryObj<typeof AnnotationProjectActions>;

export const Primary: Story = {
  args: {
    annotationProject: makeAnnotationProject(),
    onDeleteAnnotationProject: fn(),
   onDownloadAnnotationProject: fn(),
 },
};
