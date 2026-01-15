"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2Icon } from "lucide-react";
import toast from "react-hot-toast";

import api from "@/app/api";
import useFoundationModels from "@/app/hooks/api/useFoundationModels";

import Button from "@/lib/components/ui/Button";
import { DialogOverlay } from "@/lib/components/ui/Dialog";

import type { FoundationModel, FoundationModelRunCreate } from "@/lib/types";

export interface RunFoundationModelDialogProps {
  /** Whether the dialog is open */
  isOpen: boolean;
  /** Callback when the dialog is closed */
  onClose: () => void;
  /** The dataset UUID to run the model on */
  datasetUuid: string;
  /** Optional recording count to display */
  recordingCount?: number;
  /** Whether the user has permission to run models */
  canRun?: boolean;
  /** Callback when a run is successfully created */
  onRunCreated?: (runUuid: string) => void;
}

const MODEL_DESCRIPTIONS: Record<string, string> = {
  birdnet_v2_4:
    "BirdNET v2.4 is a deep learning model for identifying bird species from audio recordings. It can recognize over 3,000 bird species worldwide.",
  perch_v2_0:
    "Perch v2.0 is Google's bird vocalization model optimized for generating high-quality audio embeddings for species classification and similarity search.",
};

// BirdNET supported locales for species names
const BIRDNET_LOCALES: { value: string; label: string }[] = [
  { value: "ja", label: "Japanese (日本語)" },
  { value: "en_us", label: "English (US)" },
  { value: "en_uk", label: "English (UK)" },
  { value: "de", label: "German (Deutsch)" },
  { value: "fr", label: "French (Français)" },
  { value: "es", label: "Spanish (Español)" },
  { value: "pt", label: "Portuguese (Português)" },
  { value: "zh", label: "Chinese (中文)" },
  { value: "ko", label: "Korean (한국어)" },
  { value: "it", label: "Italian (Italiano)" },
  { value: "nl", label: "Dutch (Nederlands)" },
  { value: "pl", label: "Polish (Polski)" },
  { value: "ru", label: "Russian (Русский)" },
  { value: "sv", label: "Swedish (Svenska)" },
  { value: "da", label: "Danish (Dansk)" },
  { value: "fi", label: "Finnish (Suomi)" },
  { value: "no", label: "Norwegian (Norsk)" },
  { value: "cs", label: "Czech (Čeština)" },
  { value: "sk", label: "Slovak (Slovenčina)" },
  { value: "hu", label: "Hungarian (Magyar)" },
  { value: "ro", label: "Romanian (Română)" },
  { value: "tr", label: "Turkish (Türkçe)" },
  { value: "th", label: "Thai (ไทย)" },
  { value: "uk", label: "Ukrainian (Українська)" },
  { value: "ar", label: "Arabic (العربية)" },
  { value: "af", label: "Afrikaans" },
  { value: "sl", label: "Slovenian (Slovenščina)" },
  { value: "latin", label: "Latin (Scientific names)" },
];

// Check if a model slug is BirdNET
const isBirdNetModel = (slug: string | null): boolean => {
  return slug?.toLowerCase().includes("birdnet") ?? false;
};

/**
 * Dialog for running a foundation model on a dataset.
 * Allows model selection, confidence threshold adjustment, and displays
 * model descriptions and recording count information.
 */
export default function RunFoundationModelDialog({
  isOpen,
  onClose,
  datasetUuid,
  recordingCount,
  canRun = true,
  onRunCreated,
}: RunFoundationModelDialogProps) {
  const queryClient = useQueryClient();
  const modelsQuery = useFoundationModels();
  const models = modelsQuery.data ?? [];

  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [threshold, setThreshold] = useState(0.1);
  const [locale, setLocale] = useState("ja");
  const [runEmbeddings, setRunEmbeddings] = useState(true);
  const [runPredictions, setRunPredictions] = useState(true);

  // Set default selection when models load
  useEffect(() => {
    if (!selectedSlug && models.length > 0) {
      const defaultModel = models[0];
      setSelectedSlug(defaultModel.slug);
      setThreshold(defaultModel.default_confidence_threshold);
    }
  }, [models, selectedSlug]);

  // Reset state when dialog closes
  useEffect(() => {
    if (!isOpen) {
      setSelectedSlug(null);
      setThreshold(0.1);
      setLocale("ja");
      setRunEmbeddings(true);
      setRunPredictions(true);
    }
  }, [isOpen]);

  const selectedModel = models.find((m) => m.slug === selectedSlug);

  const mutation = useMutation({
    mutationFn: async (payload: FoundationModelRunCreate) =>
      await api.foundationModels.createRun(payload),
    onSuccess: (run) => {
      toast.success("Foundation model run queued");
      void queryClient.invalidateQueries({
        queryKey: ["foundation-models", datasetUuid, "summary"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["foundation-models", datasetUuid, "runs"],
      });
      onRunCreated?.(run.uuid);
      onClose();
    },
    onError: (error: unknown) => {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to start foundation model run";
      toast.error(message);
    },
  });

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedSlug) return;
    await mutation.mutateAsync({
      dataset_uuid: datasetUuid,
      foundation_model_slug: selectedSlug,
      confidence_threshold: threshold,
      run_embeddings: runEmbeddings,
      run_predictions: runPredictions,
      // Only include locale for BirdNET models
      ...(isBirdNetModel(selectedSlug) ? { locale } : {}),
    });
  };

  const handleModelSelect = (model: FoundationModel) => {
    setSelectedSlug(model.slug);
    setThreshold(model.default_confidence_threshold);
  };

  if (!isOpen) return null;

  const description = selectedSlug
    ? MODEL_DESCRIPTIONS[selectedSlug] ?? selectedModel?.description ?? null
    : null;

  return (
    <DialogOverlay title="Run foundation model" isOpen onClose={onClose}>
      <form onSubmit={handleSubmit} className="w-[480px] space-y-6">
        {/* Model Selection */}
        <div className="space-y-2">
          <label className="block text-sm font-semibold text-stone-700 dark:text-stone-200">
            Select model
          </label>
          {modelsQuery.isLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2Icon className="h-5 w-5 animate-spin text-stone-400" />
            </div>
          ) : models.length === 0 ? (
            <p className="text-sm text-stone-500">
              No foundation models available.
            </p>
          ) : (
            <div className="space-y-2">
              {models.map((model) => (
                <label
                  key={model.slug}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                    selectedSlug === model.slug
                      ? "border-emerald-500 bg-emerald-50 dark:border-emerald-400 dark:bg-emerald-900/20"
                      : "border-stone-200 hover:border-stone-300 dark:border-stone-600 dark:hover:border-stone-500"
                  } ${!canRun ? "cursor-not-allowed opacity-60" : ""}`}
                >
                  <input
                    type="radio"
                    name="foundation-model"
                    value={model.slug}
                    checked={selectedSlug === model.slug}
                    onChange={() => handleModelSelect(model)}
                    disabled={!canRun}
                    className="mt-1 h-4 w-4 text-emerald-600 focus:ring-emerald-500"
                  />
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-stone-900 dark:text-stone-100">
                        {model.display_name}
                      </span>
                      <span className="rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-600 dark:bg-stone-700 dark:text-stone-300">
                        v{model.version}
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">
                      Provider: {model.provider}
                    </p>
                  </div>
                </label>
              ))}
            </div>
          )}
        </div>

        {/* Model Description */}
        {description && (
          <div className="rounded-lg bg-stone-50 p-3 dark:bg-stone-800">
            <p className="text-sm text-stone-600 dark:text-stone-300">
              {description}
            </p>
          </div>
        )}

        {/* Confidence Threshold Slider */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="block text-sm font-semibold text-stone-700 dark:text-stone-200">
              Confidence threshold
            </label>
            <span className="text-sm font-mono text-stone-600 dark:text-stone-400">
              {(threshold * 100).toFixed(0)}%
            </span>
          </div>
          <input
            type="range"
            min={0.01}
            max={0.99}
            step={0.01}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            disabled={!canRun}
            className="w-full accent-emerald-600"
          />
          <div className="flex justify-between text-xs text-stone-500">
            <span>1%</span>
            <span>50%</span>
            <span>99%</span>
          </div>
          <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">
            Only detections with confidence above this threshold will be
            recorded. Lower values capture more detections but may include more
            false positives.
          </p>
        </div>

        {/* Species Name Language (BirdNET only) */}
        {isBirdNetModel(selectedSlug) && (
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-stone-700 dark:text-stone-200">
              Species names language
            </label>
            <select
              value={locale}
              onChange={(e) => setLocale(e.target.value)}
              disabled={!canRun}
              className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:cursor-not-allowed disabled:opacity-60 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
            >
              {BIRDNET_LOCALES.map((loc) => (
                <option key={loc.value} value={loc.value}>
                  {loc.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-stone-500 dark:text-stone-400">
              Select the language for species common names in detection results.
            </p>
          </div>
        )}

        {/* Processing Options */}
        <div className="space-y-2">
          <label className="block text-sm font-semibold text-stone-700 dark:text-stone-200">
            Processing options
          </label>
          <div className="space-y-2 rounded-lg border border-stone-200 p-3 dark:border-stone-600">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={runEmbeddings}
                onChange={(e) => setRunEmbeddings(e.target.checked)}
                disabled={!canRun}
                className="h-4 w-4 rounded border-stone-300 text-emerald-600 focus:ring-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
              />
              <span className="text-sm text-stone-700 dark:text-stone-200">
                Generate embeddings
              </span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={runPredictions}
                onChange={(e) => setRunPredictions(e.target.checked)}
                disabled={!canRun}
                className="h-4 w-4 rounded border-stone-300 text-emerald-600 focus:ring-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
              />
              <span className="text-sm text-stone-700 dark:text-stone-200">
                Generate species predictions
              </span>
            </label>
          </div>
          <p className="text-xs text-stone-500 dark:text-stone-400">
            Select which outputs to generate. Embeddings enable similarity search, predictions provide species identifications.
          </p>
        </div>

        {/* Recording Count Info */}
        {recordingCount !== undefined && recordingCount > 0 && (
          <div className="rounded-lg border border-stone-200 bg-stone-50 p-3 dark:border-stone-700 dark:bg-stone-800">
            <div className="flex items-center gap-2">
              <span className="text-sm text-stone-600 dark:text-stone-300">
                This will process{" "}
                <span className="font-semibold text-stone-900 dark:text-stone-100">
                  {recordingCount.toLocaleString()}
                </span>{" "}
                recording{recordingCount !== 1 ? "s" : ""}
              </span>
            </div>
          </div>
        )}

        {/* Permission Warning */}
        {!canRun && (
          <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-700 dark:bg-amber-900/30 dark:text-amber-200">
            You need manager access to this dataset to run foundation models.
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-2">
          <Button mode="ghost" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={
              !canRun ||
              mutation.isPending ||
              !selectedSlug ||
              (!runEmbeddings && !runPredictions)
            }
            variant="primary"
            mode="filled"
          >
            {mutation.isPending ? (
              <>
                <Loader2Icon className="mr-2 h-4 w-4 animate-spin" />
                Queuing...
              </>
            ) : (
              "Run"
            )}
          </Button>
        </div>
      </form>
    </DialogOverlay>
  );
}
