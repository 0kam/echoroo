/**
 * Shared types for the tag management components.
 */
import type { TagCreate, TagUpdate } from '$lib/types/tag';

/**
 * Payload emitted by {@link TagForm} on submit. The parent shell owns the
 * TanStack mutations and dispatches on `mode`.
 */
export type TagFormSubmit =
  | { mode: 'create'; data: TagCreate }
  | { mode: 'edit'; tagId: string; data: TagUpdate };
