"use client";

import { createContext } from "react";

import type { MLProject } from "@/lib/types";

/**
 * Context for providing ML Project data to child components.
 *
 * This context allows child components within the ML Project layout
 * to access the current ML Project data without prop drilling.
 */
const MLProjectContext = createContext<MLProject | null>(null);

export default MLProjectContext;
