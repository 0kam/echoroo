import { createContext } from "react";

import type { EvaluationSet } from "@/lib/types";

const EvaluationSetContext = createContext<EvaluationSet>({
  uuid: "",
  name: "",
  description: "",
  created_on: new Date(),
  tags: [],
  task: "Sound Event Detection",
});

export default EvaluationSetContext;
