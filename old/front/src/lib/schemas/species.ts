import { z } from "zod";

export const VernacularNameSchema = z.object({
  vernacular_name: z.string(),
  language: z.string().optional().nullable(),
  source: z.string().optional().nullable(),
});

export const SpeciesCandidateSchema = z.object({
  usage_key: z.string(),
  canonical_name: z.string(),
  scientific_name: z.string().optional().nullable(),
  rank: z.string().optional().nullable(),
  synonym: z.boolean().optional().nullable(),
  dataset_key: z.string().optional().nullable(),
  vernacular_name: z.string().optional().nullable(),
  vernacular_names: z.array(VernacularNameSchema).optional().nullable(),
});

export type VernacularName = z.infer<typeof VernacularNameSchema>;
export type SpeciesCandidate = z.infer<typeof SpeciesCandidateSchema>;
