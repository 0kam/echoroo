import { createContext } from "react";

import type { AnnotationProject } from "@/lib/types";

const AnnotationProjectContext = createContext<AnnotationProject>({
  name: "",
  description: "",
  tags: [],
  created_on: new Date(),
  uuid: "",
  visibility: "private",
  created_by_id: "",
  owner_group_id: null,
  annotation_instructions: null,
});

export default AnnotationProjectContext;
