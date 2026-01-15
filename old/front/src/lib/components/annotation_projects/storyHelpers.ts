import type { AnnotationProject } from "@/lib/types";

export function makeAnnotationProject(
  overrides: Partial<AnnotationProject> = {},
): AnnotationProject {
  const base: AnnotationProject = {
    uuid: "00000000-0000-0000-0000-0000000000aa",
    name: "Demo Annotation Project",
    description: "Example annotation project used in stories.",
    annotation_instructions: null,
    tags: [],
    created_on: new Date("2024-01-01T00:00:00Z"),
    visibility: "restricted",
    created_by_id: "00000000-0000-0000-0000-00000000000a",
    dataset_id: 1,
    project_id: "prj-demo",
  };

  return {
    ...base,
    ...overrides,
    created_on: overrides.created_on ?? base.created_on,
  };
}
