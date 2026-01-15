import { z } from "zod";

import { SpeciesCandidateSchema } from "@/lib/schemas/species";

export type SpeciesCandidate = z.infer<typeof SpeciesCandidateSchema>;
