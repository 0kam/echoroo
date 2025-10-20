import { z } from "zod";

export const SpeciesCandidateSchema = z.object({
  usage_key: z.string(),
  canonical_name: z.string(),
  scientific_name: z.string().optional().nullable(),
  rank: z.string().optional().nullable(),
  synonym: z.boolean().optional().nullable(),
  dataset_key: z.string().optional().nullable(),
});

export type SpeciesCandidate = z.infer<typeof SpeciesCandidateSchema>;
