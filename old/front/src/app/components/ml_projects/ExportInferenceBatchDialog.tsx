"use client";

import { useState, useMemo, useCallback } from "react";
import { useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";

import { DialogOverlay } from "@/lib/components/ui/Dialog";
import Button from "@/lib/components/ui/Button";
import { CheckIcon } from "@/lib/components/icons";

import api from "@/app/api";

import type { InferenceBatch, ConvertToAnnotationProjectRequest } from "@/lib/types";

interface ExportInferenceBatchDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (annotationProjectUuid: string) => void;
  mlProjectUuid: string;
  inferenceBatch: InferenceBatch;
}

export default function ExportInferenceBatchDialog({
  isOpen,
  onClose,
  onSuccess,
  mlProjectUuid,
  inferenceBatch,
}: ExportInferenceBatchDialogProps) {
  const [name, setName] = useState(`AP from ${inferenceBatch.name || "Inference Batch"}`);
  const [description, setDescription] = useState("");
  const [confidenceThreshold, setConfidenceThreshold] = useState<string>(
    (inferenceBatch.confidence_threshold * 100).toFixed(0)
  );
  const [includeOnlyPositive, setIncludeOnlyPositive] = useState(true);

  // Calculate estimated count based on current settings
  const estimatedCount = useMemo(() => {
    // If including only positive, use positive_predictions_count
    // Otherwise use total_predictions
    if (includeOnlyPositive) {
      return inferenceBatch.positive_predictions_count;
    }
    return inferenceBatch.total_predictions;
  }, [inferenceBatch, includeOnlyPositive]);

  // Parse confidence threshold
  const parsedThreshold = useMemo(() => {
    const value = parseFloat(confidenceThreshold);
    if (isNaN(value) || value < 0 || value > 100) {
      return null;
    }
    return value / 100;
  }, [confidenceThreshold]);

  const exportMutation = useMutation({
    mutationFn: async (data: ConvertToAnnotationProjectRequest) => {
      return api.inferenceBatches.convertToAnnotationProject(
        mlProjectUuid,
        inferenceBatch.uuid,
        data,
      );
    },
    onSuccess: (result) => {
      toast.success(`Annotation Project "${result.name}" created successfully!`);
      onSuccess(result.uuid);
      onClose();
    },
    onError: (error) => {
      toast.error(`Failed to export: ${error instanceof Error ? error.message : "Unknown error"}`);
    },
  });

  const { mutate: mutateExport, isPending: isExporting } = exportMutation;

  const handleSubmit = useCallback(() => {
    if (!name.trim()) {
      toast.error("Please enter a name for the Annotation Project");
      return;
    }
    if (parsedThreshold === null) {
      toast.error("Please enter a valid confidence threshold (0-100)");
      return;
    }

    mutateExport({
      name: name.trim(),
      description: description.trim() || undefined,
      confidence_threshold: parsedThreshold,
      include_only_positive: includeOnlyPositive,
    });
  }, [name, description, parsedThreshold, includeOnlyPositive, mutateExport]);

  return (
    <DialogOverlay
      title="Export to Annotation Project"
      isOpen={isOpen}
      onClose={onClose}
    >
      <div className="w-[500px] flex flex-col gap-6">
        {/* Source Info */}
        <div className="bg-stone-100 dark:bg-stone-800 rounded-lg p-3">
          <div className="text-sm text-stone-500 dark:text-stone-400">Source Inference Batch</div>
          <div className="font-medium text-stone-700 dark:text-stone-200">
            {inferenceBatch.name || "Inference Batch"}
          </div>
          <div className="text-sm text-stone-500 dark:text-stone-400 mt-1">
            {inferenceBatch.total_predictions} total predictions,{" "}
            {inferenceBatch.positive_predictions_count} positive
          </div>
          {inferenceBatch.custom_model && (
            <div className="text-sm text-stone-500 dark:text-stone-400">
              Model: {inferenceBatch.custom_model.name} | Target: {inferenceBatch.custom_model.tag?.key}: {inferenceBatch.custom_model.tag?.value}
            </div>
          )}
        </div>

        {/* Name Input */}
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Annotation Project Name *
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Enter name..."
            className="w-full px-3 py-2 rounded-lg border border-stone-300 dark:border-stone-600 bg-white dark:bg-stone-800 text-stone-700 dark:text-stone-200 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none"
          />
        </div>

        {/* Description Input */}
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Description (optional)
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Enter description..."
            rows={3}
            className="w-full px-3 py-2 rounded-lg border border-stone-300 dark:border-stone-600 bg-white dark:bg-stone-800 text-stone-700 dark:text-stone-200 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none resize-none"
          />
        </div>

        {/* Confidence Threshold */}
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Confidence Threshold (%)
          </label>
          <input
            type="number"
            min={0}
            max={100}
            value={confidenceThreshold}
            onChange={(e) => setConfidenceThreshold(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-stone-300 dark:border-stone-600 bg-white dark:bg-stone-800 text-stone-700 dark:text-stone-200 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none"
          />
          <div className="text-xs text-stone-500 dark:text-stone-400 mt-1">
            Only predictions with confidence above this threshold will be included
          </div>
        </div>

        {/* Include Only Positive Toggle */}
        <div>
          <button
            type="button"
            onClick={() => setIncludeOnlyPositive(!includeOnlyPositive)}
            className={`flex items-center gap-3 p-3 w-full rounded-lg border-2 transition-colors ${
              includeOnlyPositive
                ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20"
                : "border-stone-200 dark:border-stone-600 hover:border-stone-300 dark:hover:border-stone-500"
            }`}
          >
            <div
              className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ${
                includeOnlyPositive
                  ? "bg-emerald-500 border-emerald-500 text-white"
                  : "border-stone-400 dark:border-stone-500"
              }`}
            >
              {includeOnlyPositive && <CheckIcon className="w-3 h-3" />}
            </div>
            <div className="text-left">
              <div className="font-medium text-stone-700 dark:text-stone-200">
                Include only positive predictions
              </div>
              <div className="text-xs text-stone-500 dark:text-stone-400">
                Only include predictions where the model predicted positive for the target sound
              </div>
            </div>
          </button>
        </div>

        {/* Preview */}
        <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-emerald-700 dark:text-emerald-300">
              Estimated clips to export:
            </span>
            <span className="text-lg font-bold text-emerald-600 dark:text-emerald-400">
              ~{estimatedCount}
            </span>
          </div>
          <div className="text-xs text-emerald-600 dark:text-emerald-400 mt-1">
            Final count may differ based on confidence threshold
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <Button
            variant="secondary"
            onClick={onClose}
            disabled={isExporting}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            disabled={isExporting || !name.trim() || parsedThreshold === null}
          >
            {isExporting ? "Exporting..." : "Export"}
          </Button>
        </div>
      </div>
    </DialogOverlay>
  );
}
