import type { Meta, StoryObj } from "@storybook/react";

import Note from "@/lib/components/notes/Note";

import AnnotationProjectActions from "./AnnotationProjectActions";
import AnnotationProjectDetail from "./AnnotationProjectDetail";
import AnnotationProjectNotesSummary from "./AnnotationProjectNotesSummary";
import AnnotationProjectProgress from "./AnnotationProjectProgress";
import AnnotationProjectTagsSummary from "./AnnotationProjectTagsSummary";
import AnnotationProjectUpdate from "./AnnotationProjectUpdate";

const meta: Meta<typeof AnnotationProjectDetail> = {
  title: "AnnotationProject/Detail",
  component: AnnotationProjectDetail,
  parameters: {
    controls: {
      exclude: [
        "AnnotationProjectUpdate",
        "AnnotationProjectActions",
        "AnnotationProjectTagsSummary",
        "AnnotationProjectNotesSummary",
        "AnnotationProjectProgress",
      ],
    },
  },
};

export default meta;

type Story = StoryObj<typeof AnnotationProjectDetail>;

const annotationProject = {
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
};

export const Primary: Story = {
  args: {
    AnnotationProjectProgress: <AnnotationProjectProgress />,
    AnnotationProjectUpdate: (
      <AnnotationProjectUpdate annotationProject={annotationProject} />
    ),
    AnnotationProjectActions: (
      <AnnotationProjectActions annotationProject={annotationProject} />
    ),
    AnnotationProjectTagsSummary: (
      <AnnotationProjectTagsSummary annotationProject={annotationProject} />
    ),
    AnnotationProjectNotesSummary: (
      <AnnotationProjectNotesSummary
        ClipAnnotationNote={(props) => (
          <Note note={props.clipAnnotationNote.note} />
        )}
        SoundEventAnnotationNote={(props) => (
          <Note note={props.soundEventAnnotationNote.note} />
        )}
      />
    ),
  },
};
