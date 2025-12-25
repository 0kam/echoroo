import { z } from "zod";

import { UserSchema } from "./users";

export const TagSchema = z.object({
  id: z.number().int().optional(),
  key: z.string(),
  value: z.string(),
  canonical_name: z.string().optional(),
});

export const TagCountSchema = z.object({
  tag: TagSchema,
  count: z.number(),
});

export const PredictionTagSchema = z.object({
  tag: TagSchema,
  score: z.number(),
  created_on: z.coerce.date(),
});

export const TagAssociationSchema = z.object({
  tag: TagSchema,
  created_by: UserSchema.nullish(),
  created_on: z.coerce.date(),
});
