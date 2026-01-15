"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useCallback } from "react";
import { useForm } from "react-hook-form";

import {
  Group,
  Input,
  Submit,
  TextArea,
} from "@/lib/components/inputs";
import { MLProjectCreateSchema } from "@/lib/schemas";
import type { MLProjectCreate } from "@/lib/types";

/**
 * Component for creating a new ML Project.
 *
 * The simplified form only requires name and optional description.
 * Datasets and foundation models are configured after project creation
 * in the Datasets tab.
 */
export default function MLProjectCreate({
  onCreateMLProject,
}: {
  onCreateMLProject?: (data: MLProjectCreate) => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors, isValid },
  } = useForm<MLProjectCreate>({
    resolver: zodResolver(MLProjectCreateSchema),
    mode: "onChange",
    defaultValues: {
      name: "",
      description: "",
    },
  });

  const onSubmit = useCallback(
    (data: MLProjectCreate) => {
      onCreateMLProject?.(data);
    },
    [onCreateMLProject],
  );

  return (
    <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)}>
      <Group
        name="name"
        label="Name"
        help="Provide a descriptive name for this ML project."
        error={errors.name?.message}
      >
        <Input
          placeholder="e.g., Hooded Warbler Detection"
          {...register("name")}
        />
      </Group>

      <Group
        name="description"
        label="Description"
        help="Describe the objectives and target species for this project."
        error={errors.description?.message}
      >
        <TextArea
          rows={3}
          placeholder="e.g., Detecting Hooded Warbler songs in spring 2024 recordings..."
          {...register("description")}
        />
      </Group>

      <p className="text-sm text-stone-500 dark:text-stone-400">
        After creating the project, add datasets and configure embedding sources
        in the Datasets tab.
      </p>

      <div className="mb-3">
        <Submit disabled={!isValid}>Create ML Project</Submit>
      </div>
    </form>
  );
}
