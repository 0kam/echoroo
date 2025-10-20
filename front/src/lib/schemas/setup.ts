"use client";

import { z } from "zod";

export const AudioDirectorySchema = z.object({
  audio_dir: z.string().min(1),
});

export const AudioDirectoryUpdateSchema = AudioDirectorySchema;
