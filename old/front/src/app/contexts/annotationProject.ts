import { createContext } from "react";

import type { AnnotationProject } from "@/lib/types";

const AnnotationProjectContext = createContext<AnnotationProject>({
  name: "",
  description: "",
  tags: [],
  created_on: new Date(),
  uuid: "",
  visibility: "restricted",
  created_by_id: "",
  annotation_instructions: null,
  dataset_id: 0,
  project_id: "",
});

export default AnnotationProjectContext;
