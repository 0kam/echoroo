import { useMutation } from "@tanstack/react-query";

import api from "@/app/api";

import type { Tag, TagCreate } from "@/lib/types";

export default function useTags() {
  const create = useMutation<Tag, unknown, TagCreate>({
    mutationFn: api.tags.create,
  });

  return {
    create,
  } as const;
}
