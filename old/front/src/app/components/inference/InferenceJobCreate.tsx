import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";

import api from "@/app/api";

/** Generate a simple unique ID */
function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

import { Group, Input, Select, Submit } from "@/lib/components/inputs";
import type { Option } from "@/lib/components/inputs/Select";
import Slider from "@/lib/components/inputs/Slider";
import Card from "@/lib/components/ui/Card";

import type { Dataset } from "@/lib/types";

import type { InferenceJobConfig, InferenceJobUI } from "./InferenceJobCard";

type InferenceModel = "birdnet" | "perch";

const MODEL_OPTIONS: Option<InferenceModel>[] = [
  {
    id: "birdnet",
    label: "BirdNET",
    value: "birdnet",
  },
  {
    id: "perch",
    label: "Perch",
    value: "perch",
  },
];

interface FormData {
  datasetUuid: string;
  model: InferenceModel;
  threshold: number;
  overlap: number;
  minConfidence: number;
  batchSize: number;
}

export default function InferenceJobCreate({
  onJobCreated,
}: {
  onJobCreated?: (job: InferenceJobUI) => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
    setValue,
    watch,
    reset,
  } = useForm<FormData>({
    defaultValues: {
      datasetUuid: "",
      model: "birdnet",
      threshold: 0.5,
      overlap: 0.0,
      minConfidence: 0.1,
      batchSize: 16,
    },
  });

  useEffect(() => {
    register("datasetUuid");
    register("model");
    register("threshold");
    register("overlap");
    register("minConfidence");
    register("batchSize");
  }, [register]);

  const datasetUuid = watch("datasetUuid");
  const model = watch("model");
  const threshold = watch("threshold");
  const overlap = watch("overlap");
  const minConfidence = watch("minConfidence");
  const batchSize = watch("batchSize");

  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch available datasets
  const { data: datasetsPage, isLoading: datasetsLoading } = useQuery({
    queryKey: ["datasets", "all"],
    queryFn: () => api.datasets.getMany({ limit: 100 }),
    staleTime: 60_000,
  });

  const datasets = datasetsPage?.items ?? [];

  const datasetPlaceholder: Option<string> = useMemo(
    () => ({
      id: "placeholder",
      label: datasetsLoading ? "Loading datasets..." : "Select a dataset",
      value: "",
      disabled: true,
    }),
    [datasetsLoading],
  );

  const datasetOptions: Option<string>[] = useMemo(
    () => [
      datasetPlaceholder,
      ...datasets.map((dataset: Dataset) => ({
        id: dataset.uuid,
        label: dataset.name,
        value: dataset.uuid,
      })),
    ],
    [datasets, datasetPlaceholder],
  );

  const selectedDatasetOption =
    datasetOptions.find((opt) => opt.value === datasetUuid) ??
    datasetPlaceholder;

  const selectedModelOption =
    MODEL_OPTIONS.find((opt) => opt.value === model) ?? MODEL_OPTIONS[0];

  const handleDatasetChange = useCallback(
    (value: string) => {
      setValue("datasetUuid", value, { shouldValidate: true });
    },
    [setValue],
  );

  const handleModelChange = useCallback(
    (value: InferenceModel) => {
      setValue("model", value, { shouldValidate: true });
    },
    [setValue],
  );

  const handleThresholdChange = useCallback(
    (value: number | number[]) => {
      const val = Array.isArray(value) ? value[0] : value;
      setValue("threshold", val, { shouldValidate: true });
    },
    [setValue],
  );

  const handleOverlapChange = useCallback(
    (value: number | number[]) => {
      const val = Array.isArray(value) ? value[0] : value;
      setValue("overlap", val, { shouldValidate: true });
    },
    [setValue],
  );

  const handleMinConfidenceChange = useCallback(
    (value: number | number[]) => {
      const val = Array.isArray(value) ? value[0] : value;
      setValue("minConfidence", val, { shouldValidate: true });
    },
    [setValue],
  );

  const selectedDataset = datasets.find(
    (d: Dataset) => d.uuid === datasetUuid,
  );

  const canSubmit = !!datasetUuid && !!model && !isSubmitting;

  const onSubmit = useCallback(
    async (data: FormData) => {
      if (!canSubmit || !selectedDataset) return;

      setIsSubmitting(true);
      try {
        // Create a new inference job (demo - in production this would call the API)
        const config: InferenceJobConfig = {
          threshold: data.threshold,
          overlap: data.overlap,
          minConfidence: data.minConfidence,
          batchSize: data.batchSize,
        };

        const newJob: InferenceJobUI = {
          id: generateId(),
          datasetUuid: data.datasetUuid,
          datasetName: selectedDataset.name,
          model: data.model === "birdnet" ? "BirdNET" : "Perch",
          config,
          status: "running",
          progress: 0,
          startedAt: new Date(),
          recordingCount: Math.floor(Math.random() * 100) + 10, // Demo value
          processedCount: 0,
        };

        toast.success(`Inference job started for ${selectedDataset.name}`);
        onJobCreated?.(newJob);
        reset();
      } catch (error) {
        toast.error("Failed to create inference job");
        console.error("Failed to create inference job:", error);
      } finally {
        setIsSubmitting(false);
      }
    },
    [canSubmit, selectedDataset, onJobCreated, reset],
  );

  return (
    <Card>
      <h2 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
        Create Inference Job
      </h2>
      <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)}>
        <Group
          name="datasetUuid"
          label="Dataset"
          help="Select the dataset to process."
          error={errors.datasetUuid?.message}
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
          name="model"
          label="Model"
          help="Choose the ML model for inference."
          error={errors.model?.message}
        >
          <Select
            label="Model"
            options={MODEL_OPTIONS}
            selected={selectedModelOption}
            onChange={handleModelChange}
            placement="bottom-start"
          />
        </Group>

        <Group
          name="threshold"
          label="Detection Threshold"
          help="Minimum detection score (0-1). Higher values mean fewer, more confident detections."
        >
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <Slider
                label="Threshold"
                minValue={0}
                maxValue={1}
                step={0.05}
                value={threshold}
                onChange={handleThresholdChange}
                formatter={(val) => val.toFixed(2)}
              />
            </div>
            <Input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={threshold}
              onChange={(e) =>
                handleThresholdChange(parseFloat(e.target.value) || 0)
              }
              className="w-20"
            />
          </div>
        </Group>

        <Group
          name="overlap"
          label="Window Overlap"
          help="Overlap between analysis windows (0-0.5). Higher values may improve detection at segment boundaries."
        >
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <Slider
                label="Overlap"
                minValue={0}
                maxValue={0.5}
                step={0.05}
                value={overlap}
                onChange={handleOverlapChange}
                formatter={(val) => val.toFixed(2)}
              />
            </div>
            <Input
              type="number"
              min={0}
              max={0.5}
              step={0.05}
              value={overlap}
              onChange={(e) =>
                handleOverlapChange(parseFloat(e.target.value) || 0)
              }
              className="w-20"
            />
          </div>
        </Group>

        <Group
          name="minConfidence"
          label="Minimum Confidence"
          help="Filter results below this confidence level."
        >
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <Slider
                label="Min Confidence"
                minValue={0}
                maxValue={1}
                step={0.05}
                value={minConfidence}
                onChange={handleMinConfidenceChange}
                formatter={(val) => val.toFixed(2)}
              />
            </div>
            <Input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={minConfidence}
              onChange={(e) =>
                handleMinConfidenceChange(parseFloat(e.target.value) || 0)
              }
              className="w-20"
            />
          </div>
        </Group>

        <Group
          name="batchSize"
          label="Batch Size"
          help="Number of recordings to process in parallel."
          error={errors.batchSize?.message}
        >
          <Input
            type="number"
            min={1}
            max={64}
            value={batchSize}
            onChange={(e) =>
              setValue("batchSize", parseInt(e.target.value) || 16)
            }
          />
        </Group>

        <div className="mt-2">
          <Submit disabled={!canSubmit}>
            {isSubmitting ? "Starting..." : "Start Inference"}
          </Submit>
        </div>
      </form>
    </Card>
  );
}
