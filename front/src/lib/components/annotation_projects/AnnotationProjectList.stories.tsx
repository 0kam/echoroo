import type { Meta, StoryObj } from "@storybook/react";
import { fn } from "@storybook/test";
import { loremIpsum } from "lorem-ipsum";

import AnnotationProjectCreate from "@/lib/components/annotation_projects/AnnotationProjectCreate";
import AnnotationProjectImport from "@/lib/components/annotation_projects/AnnotationProjectImport";
import { AnnotationProjectIcon } from "@/lib/components/icons";
import Search from "@/lib/components/inputs/Search";
import Pagination from "@/lib/components/lists/Pagination";

import AnnotationProjectList from "./AnnotationProjectList";
import { makeAnnotationProject } from "./storyHelpers";

const meta: Meta<typeof AnnotationProjectList> = {
  title: "AnnotationProject/List",
  component: AnnotationProjectList,
  args: {
    AnnotationProjectSearch: (
      <Search
        label="Search"
        placeholder="Search project..."
        icon={<AnnotationProjectIcon />}
      />
    ),
    AnnotationProjectCreate: (
      <AnnotationProjectCreate onCreateAnnotationProject={fn()} />
    ),
    AnnotationProjectImport: (
      <AnnotationProjectImport onImportAnnotationProject={fn()} />
    ),
    Pagination: <Pagination />,
    onClickAnnotationProject: fn(),
  },
  parameters: {
    controls: {
      exclude: [
        "AnnotationProjectSearch",
        "AnnotationProjectCreate",
        "AnnotationProjectImport",
        "Pagination",
      ],
    },
  },
};

export default meta;

type Story = StoryObj<typeof AnnotationProjectList>;

export const Empty: Story = {
  args: {
    annotationProjects: [],
    isLoading: false,
  },
};

export const WithProjects: Story = {
  args: {
    annotationProjects: [
      makeAnnotationProject({
        uuid: "1",
        name: "Project 1",
        description: "Description of project 1",
      }),
      makeAnnotationProject({
        uuid: "2",
        name: "Project 2",
        description: "Description of project 2",
      }),
      makeAnnotationProject({
        uuid: "3",
        name: "Project 3",
        description: "Description of project 3",
      }),
    ],
    isLoading: false,
  },
};

export const ManyProjects: Story = {
  args: {
    annotationProjects: [
      makeAnnotationProject({
        uuid: "1",
        name: "Project 1",
        description: loremIpsum({ count: 3, units: "paragraphs" }),
      }),
      makeAnnotationProject({
        uuid: "2",
        name: "Project 2",
        description: loremIpsum({ count: 3, units: "paragraphs" }),
      }),
      makeAnnotationProject({
        uuid: "3",
        name: "Project 3",
        description: loremIpsum({ count: 3, units: "paragraphs" }),
      }),
    ],
    isLoading: false,
  },
};
