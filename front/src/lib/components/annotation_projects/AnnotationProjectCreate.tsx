import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";

import api from "@/app/api";

import {
  Group,
  Input,
  Select,
  Submit,
  TextArea,
} from "@/lib/components/inputs";
import type { Option } from "@/lib/components/inputs/Select";
import VisibilityBadge from "@/lib/components/ui/VisibilityBadge";

import {
  AnnotationProjectCreateSchema,
  VisibilityLevel,
} from "@/lib/schemas";
import type { AnnotationProjectCreate, Dataset } from "@/lib/types";

const VISIBILITY_LABELS: Record<VisibilityLevel, string> = {
  public: "Public – Visible to all authenticated users",
  restricted: "Restricted – Only project members",
};

export default function AnnotationProjectCreateForm({
  onCreateAnnotationProject,
  defaultDatasetId,
}: {
  onCreateAnnotationProject?: (project: AnnotationProjectCreate) => void;
  /** Pre-selected dataset ID (e.g., when creating from dataset page) */
  defaultDatasetId?: number;
}) {
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<AnnotationProjectCreate>({
    resolver: zodResolver(AnnotationProjectCreateSchema),
    mode: "onChange",
    defaultValues: {
      visibility: "restricted",
      dataset_id: defaultDatasetId,
    },
  });

  useEffect(() => {
    register("visibility");
    register("dataset_id");
  }, [register]);

  const {
    data: datasetPage,
    isLoading: datasetsLoading,
    error: datasetsError,
  } = useQuery({
    queryKey: ["datasets", "annotation-project-form"],
    queryFn: () => api.datasets.getMany({ limit: 100, offset: 0 }),
    staleTime: 60_000,
  });

  const datasets: Dataset[] = useMemo(
    () => datasetPage?.items ?? [],
    [datasetPage],
  );

  // Set visibility based on default dataset once datasets load
  useEffect(() => {
    if (defaultDatasetId && datasets.length > 0) {
      const defaultDataset = datasets.find((d) => d.id === defaultDatasetId);
      if (defaultDataset) {
        setValue("visibility", defaultDataset.visibility, {
          shouldValidate: true,
        });
      }
    }
  }, [defaultDatasetId, datasets, setValue]);

  const datasetOptions: Option<number>[] = useMemo(() => {
    return datasets
      .filter((dataset) => dataset.id != null)
      .map((dataset) => ({
        id: dataset.uuid,
        value: dataset.id as number,
        label: (
          <div className="flex flex-col">
            <span className="font-medium text-stone-900 dark:text-stone-100">
              {dataset.name}
            </span>
            <span className="text-xs text-stone-500 dark:text-stone-400">
              {dataset.project?.project_name ?? dataset.project_id}
            </span>
          </div>
        ),
      }));
  }, [datasets]);

  const datasetId = watch("dataset_id");
  const visibility = (watch("visibility") ?? "restricted") as VisibilityLevel;

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === datasetId),
    [datasets, datasetId],
  );

  const datasetPlaceholder: Option<number> = {
    id: "dataset-placeholder",
    label: datasetsLoading
      ? "Loading datasets…"
      : datasetOptions.length === 0
        ? "No datasets available"
        : "Select a dataset",
    value: -1,
    disabled: true,
  } as Option<number>;

  const selectedDatasetOption =
    datasetOptions.find((option) => option.value === datasetId) ??
    datasetPlaceholder;

  const handleDatasetChange = useCallback(
    (value: number) => {
      if (value === -1) return;
      setValue("dataset_id", value, {
        shouldValidate: true,
        shouldDirty: true,
      });
      const dataset = datasets.find((item) => item.id === value);
      if (dataset) {
        setValue("visibility", dataset.visibility, {
          shouldValidate: true,
          shouldDirty: true,
        });
      }
    },
    [datasets, setValue],
  );

  const datasetsErrorMessage =
    datasetsError instanceof Error ? datasetsError.message : undefined;

  const onSubmit = useCallback(
    (data: AnnotationProjectCreate) => onCreateAnnotationProject?.(data),
    [onCreateAnnotationProject],
  );

  return (
    <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)}>
      <Group
        label="Dataset"
        name="dataset_id"
        help={
          datasetOptions.length === 0 && !datasetsLoading
            ? "No datasets available. Create a dataset first."
            : "Choose the dataset this annotation project will use."
        }
        error={errors.dataset_id?.message ?? datasetsErrorMessage}
      >
        <Select
          label="Dataset"
          options={[datasetPlaceholder, ...datasetOptions]}
          selected={selectedDatasetOption}
          onChange={handleDatasetChange}
          placement="bottom-start"
        />
        {selectedDataset ? (
          <div className="mt-2 flex items-center gap-2 text-sm text-stone-500 dark:text-stone-400">
            <VisibilityBadge visibility={selectedDataset.visibility} />
            <span>{VISIBILITY_LABELS[selectedDataset.visibility]}</span>
          </div>
        ) : null}
      </Group>

      <Group
        label="Name"
        name="name"
        help="Provide a descriptive name for the annotation project."
        error={errors.name?.message}
      >
        <Input {...register("name")} />
      </Group>

      <Group
        label="Description"
        name="description"
        help="Summarize the goal and scope of this annotation project."
        error={errors.description?.message}
      >
        <TextArea rows={4} {...register("description")} />
      </Group>

      <Group
        label="Instructions"
        name="annotation_instructions"
        help="Write instructions for annotators. Markdown supported."
        error={errors.annotation_instructions?.message}
      >
        <TextArea rows={10} {...register("annotation_instructions")} />
      </Group>

      <Group
        label="Visibility"
        name="visibility"
        help="Visibility follows the selected dataset."
        error={errors.visibility?.message}
      >
        <div className="flex items-center gap-2">
          <VisibilityBadge visibility={visibility} />
          <span className="text-sm text-stone-500 dark:text-stone-400">
            {VISIBILITY_LABELS[visibility]}
          </span>
        </div>
      </Group>

      <Submit disabled={!datasetId}>Create Annotation Project</Submit>
    </form>
  );
}
