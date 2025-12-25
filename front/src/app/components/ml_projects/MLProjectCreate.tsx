"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";

import api from "@/app/api";

import {
  Group,
  Input,
  Select,
  Slider,
  Submit,
  TextArea,
} from "@/lib/components/inputs";
import type { Option } from "@/lib/components/inputs/Select";
import { MLProjectCreateSchema } from "@/lib/schemas";
import type { MLProjectCreate, Page, Dataset, ModelRun } from "@/lib/types";

/**
 * Component for creating a new ML Project.
 */
export default function MLProjectCreate({
  onCreateMLProject,
  defaultDatasetUuid,
}: {
  onCreateMLProject?: (data: MLProjectCreate) => void;
  defaultDatasetUuid?: string;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
    setValue,
    watch,
  } = useForm<MLProjectCreate>({
    resolver: zodResolver(MLProjectCreateSchema),
    mode: "onChange",
    defaultValues: {
      name: "",
      description: "",
      dataset_uuid: defaultDatasetUuid ?? "",
      embedding_model_run_id: undefined,
      default_similarity_threshold: 0.7,
    },
  });

  useEffect(() => {
    register("dataset_uuid");
    register("embedding_model_run_id");
    register("default_similarity_threshold");
  }, [register]);

  const datasetUuid = watch("dataset_uuid");
  const embeddingModelRunId = watch("embedding_model_run_id");
  const threshold = watch("default_similarity_threshold") ?? 0.7;

  // Fetch available datasets
  const {
    data: datasetsPage,
    isLoading: datasetsLoading,
  } = useQuery<Page<Dataset>>({
    queryKey: ["datasets", "all"],
    queryFn: () => api.datasets.getMany({}),
    staleTime: 60_000,
  });

  const datasets = datasetsPage?.items ?? [];

  // Fetch embedding model runs for the selected dataset
  const {
    data: modelRunsPage,
    isLoading: modelRunsLoading,
  } = useQuery<Page<ModelRun>>({
    queryKey: ["model-runs", "embedding", datasetUuid],
    queryFn: () => api.modelRuns.getMany({}),
    enabled: !!datasetUuid,
    staleTime: 60_000,
  });

  const modelRuns = modelRunsPage?.items ?? [];

  // Filter to only embedding models (by name pattern)
  const embeddingModelRuns = useMemo(() => {
    return modelRuns.filter((run) =>
      run.name?.toLowerCase().includes("embed") ||
      run.name?.toLowerCase().includes("birdnet")
    );
  }, [modelRuns]);

  const datasetOptions: Option<string>[] = useMemo(() => {
    const placeholder: Option<string> = {
      id: "dataset-placeholder",
      label: datasetsLoading ? "Loading datasets..." : "Select a dataset",
      value: "",
      disabled: true,
    };
    const options = datasets.map((dataset) => ({
      id: dataset.uuid,
      label: dataset.name,
      value: dataset.uuid,
    }));
    return [placeholder, ...options];
  }, [datasets, datasetsLoading]);

  const selectedDatasetOption =
    datasetOptions.find((option) => option.value === datasetUuid) ??
    datasetOptions[0];

  const modelRunOptions: Option<number | undefined>[] = useMemo(() => {
    const placeholder: Option<number | undefined> = {
      id: "model-placeholder",
      label: modelRunsLoading
        ? "Loading models..."
        : embeddingModelRuns.length === 0
          ? "No embedding models available"
          : "Select an embedding model (optional)",
      value: undefined,
    };
    const options = embeddingModelRuns.map((run, index) => ({
      id: run.uuid,
      label: `${run.name} (v${run.version}) - ${run.created_on.toLocaleDateString()}`,
      value: index + 1, // Use index as a temporary ID
    }));
    return [placeholder, ...options];
  }, [embeddingModelRuns, modelRunsLoading]);

  const selectedModelRunOption =
    modelRunOptions.find((option) => option.value === embeddingModelRunId) ??
    modelRunOptions[0];

  const handleDatasetChange = useCallback(
    (value: string) => {
      setValue("dataset_uuid", value, { shouldValidate: true, shouldDirty: true });
      // Reset model run when dataset changes
      setValue("embedding_model_run_id", undefined, { shouldValidate: true });
    },
    [setValue],
  );

  const handleModelRunChange = useCallback(
    (value: number | undefined) => {
      setValue("embedding_model_run_id", value, {
        shouldValidate: true,
        shouldDirty: true,
      });
    },
    [setValue],
  );

  const handleThresholdChange = useCallback(
    (value: number | number[]) => {
      const newValue = Array.isArray(value) ? value[0] : value;
      setValue("default_similarity_threshold", newValue, {
        shouldValidate: true,
        shouldDirty: true,
      });
    },
    [setValue],
  );

  const canSubmit = !!datasetUuid;

  const onSubmit = useCallback(
    (data: MLProjectCreate) => {
      if (!canSubmit) return;
      onCreateMLProject?.(data);
    },
    [canSubmit, onCreateMLProject],
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
          placeholder="e.g., Birdsong Detection Project"
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
          placeholder="e.g., Detecting Hooded Warbler songs in the spring 2024 recordings..."
          {...register("description")}
        />
      </Group>

      <Group
        name="dataset_uuid"
        label="Dataset"
        help="Select the dataset containing audio recordings to analyze."
        error={errors.dataset_uuid?.message}
      >
        <Select
          label="Dataset"
          options={datasetOptions}
          selected={selectedDatasetOption}
          onChange={handleDatasetChange}
          placement="bottom-start"
        />
      </Group>

      <Group
        name="embedding_model_run_id"
        label="Embedding Model"
        help="Optional. Select a pre-computed embedding model run for faster similarity search."
        error={errors.embedding_model_run_id?.message}
      >
        <Select
          label="Model Run"
          options={modelRunOptions}
          selected={selectedModelRunOption}
          onChange={handleModelRunChange}
          placement="bottom-start"
        />
      </Group>

      <Group
        name="default_similarity_threshold"
        label={`Similarity Threshold: ${(threshold * 100).toFixed(0)}%`}
        help="Default minimum similarity score for search results. Can be adjusted per session."
      >
        <Slider
          label="Threshold"
          minValue={0}
          maxValue={1}
          step={0.01}
          value={threshold}
          onChange={handleThresholdChange}
          formatter={(v) => `${(v * 100).toFixed(0)}%`}
        />
      </Group>

      <div className="mb-3">
        <Submit disabled={!canSubmit}>Create ML Project</Submit>
      </div>
    </form>
  );
}
