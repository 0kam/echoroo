import type { z } from "zod";

import * as schemas from "@/lib/schemas";

export type AudioDirectory = z.infer<typeof schemas.AudioDirectorySchema>;
export type AudioDirectoryUpdate = z.input<
  typeof schemas.AudioDirectoryUpdateSchema
>;
