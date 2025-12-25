import type { AxiosError } from "axios";
import toast from "react-hot-toast";

import api from "@/app/api";

import useObject from "@/lib/hooks/utils/useObject";

import type { MLProject, MLProjectUpdate, Tag } from "@/lib/types";

/**
 * Custom hook for managing a single ML project.
 *
 * This hook encapsulates the logic for querying, updating, and deleting
 * an ML project using React Query. It also provides mutations for
 * adding and removing target tags.
 */
export default function useMLProject({
  uuid,
  mlProject,
  enabled = true,
  onUpdate,
  onDelete,
  onAddTag,
  onRemoveTag,
  onError,
}: {
  uuid: string;
  mlProject?: MLProject;
  enabled?: boolean;
  onUpdate?: (mlProject: MLProject) => void;
  onDelete?: (mlProject: MLProject) => void;
  onAddTag?: (mlProject: MLProject) => void;
  onRemoveTag?: (mlProject: MLProject) => void;
  onError?: (error: AxiosError) => void;
}) {
  if (mlProject !== undefined && mlProject.uuid !== uuid) {
    throw new Error("MLProject uuid does not match");
  }

  const { query, useMutation, useDestruction, client } = useObject<MLProject>({
    id: uuid,
    initialData: mlProject,
    name: "ml_project",
    enabled,
    queryFn: api.mlProjects.get,
    onError,
  });

  const update = useMutation<MLProjectUpdate>({
    mutationFn: api.mlProjects.update,
    onSuccess: (data) => {
      toast.success("ML project updated");
      onUpdate?.(data);
    },
  });

  const delete_ = useDestruction({
    mutationFn: api.mlProjects.delete,
    onSuccess: (data) => {
      toast.success("ML project deleted");
      onDelete?.(data);
    },
  });

  const addTag = useMutation<Tag>({
    mutationFn: api.mlProjects.addTag,
    onSuccess: (data) => {
      toast.success("Tag added");
      onAddTag?.(data);
    },
  });

  const removeTag = useMutation<Tag>({
    mutationFn: api.mlProjects.removeTag,
    onSuccess: (data) => {
      toast.success("Tag removed");
      onRemoveTag?.(data);
    },
  });

  return {
    ...query,
    update,
    delete: delete_,
    addTag,
    removeTag,
    client,
  } as const;
}
