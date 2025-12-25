"use client";

import { createContext, useContext } from "react";
import type { MLProject } from "@/lib/types";

interface MLProjectContextValue {
  mlProject: MLProject;
  refetch: () => void;
}

const MLProjectContext = createContext<MLProjectContextValue | null>(null);

export function useMLProject() {
  const context = useContext(MLProjectContext);
  if (!context) {
    throw new Error("useMLProject must be used within MLProjectProvider");
  }
  return context;
}

export default MLProjectContext;
