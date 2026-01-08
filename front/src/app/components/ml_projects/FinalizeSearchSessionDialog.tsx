"use client";

import { useState, useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";

import { DialogOverlay } from "@/lib/components/ui/Dialog";
import Button from "@/lib/components/ui/Button";

import api from "@/app/api";

import type { SearchSession, SearchProgress, FinalizeRequest, ClassifierType } from "@/lib/types";

interface FinalizeSearchSessionDialogProps {
  isOpen: boolean;
  onClose: () => void;
  mlProjectUuid: string;
  searchSession: SearchSession;
  progress: SearchProgress | null;
}

const MODEL_TYPE_LABELS: Record<ClassifierType, string> = {
  logistic_regression: "Logistic Regression",
  svm_linear: "Linear SVM",
  mlp_small: "Small Neural Network",
  mlp_medium: "Medium Neural Network",
  random_forest: "Random Forest",
};

export default function FinalizeSearchSessionDialog({
  isOpen,
  onClose,
  mlProjectUuid,
  searchSession,
  progress,
}: FinalizeSearchSessionDialogProps) {
  const queryClient = useQueryClient();

  const [modelName, setModelName] = useState(`Model from ${searchSession.name}`);
  const [modelType, setModelType] = useState<ClassifierType>("logistic_regression");
  const [description, setDescription] = useState("");
  const [createAnnotationProject, setCreateAnnotationProject] = useState(true);
  const [annotationProjectName, setAnnotationProjectName] = useState("");

  const finalizeMutation = useMutation({
    mutationFn: async (data: FinalizeRequest) => {
      return api.searchSessions.finalize(
        mlProjectUuid,
        searchSession.uuid,
        data,
      );
    },
    onSuccess: (result) => {
      const message = createAnnotationProject && result.annotation_project_uuid
        ? `Model "${result.custom_model_name}" and Annotation Project "${result.annotation_project_name}" created successfully!`
        : `Model "${result.custom_model_name}" created successfully!`;

      toast.success(message);

      // Show additional details
      toast.success(
        `Trained with ${result.positive_count} positive and ${result.negative_count} negative samples`,
        { duration: 5000 }
      );

      // Invalidate relevant queries
      queryClient.invalidateQueries({ queryKey: ["ml_project_custom_models", mlProjectUuid] });
      if (createAnnotationProject) {
        queryClient.invalidateQueries({ queryKey: ["ml_project_annotation_projects", mlProjectUuid] });
      }

      onClose();
    },
    onError: (error) => {
      toast.error(`Failed to finalize: ${error instanceof Error ? error.message : "Unknown error"}`);
    },
  });

  const { mutate: mutateFinalize, isPending: isFinalizing } = finalizeMutation;

  const handleSubmit = useCallback(() => {
    if (!modelName.trim()) {
      toast.error("Please enter a model name");
      return;
    }

    const finalizeData: FinalizeRequest = {
      model_name: modelName.trim(),
      model_type: modelType,
      create_annotation_project: createAnnotationProject,
      annotation_project_name: createAnnotationProject
        ? (annotationProjectName.trim() || modelName.trim())
        : undefined,
      description: description.trim() || undefined,
    };

    mutateFinalize(finalizeData);
  }, [modelName, modelType, createAnnotationProject, annotationProjectName, description, mutateFinalize]);

  return (
    <DialogOverlay
      title="Finalize & Save Model"
      isOpen={isOpen}
      onClose={onClose}
    >
      <div className="w-[500px] flex flex-col gap-6">
        {/* Source Info */}
        <div className="bg-stone-100 dark:bg-stone-800 rounded-lg p-3">
          <div className="text-sm text-stone-500 dark:text-stone-400">Source Search Session</div>
          <div className="font-medium text-stone-700 dark:text-stone-200">
            {searchSession.name}
          </div>
          <div className="text-sm text-stone-500 dark:text-stone-400 mt-1">
            {progress?.labeled ?? 0} labeled samples ({progress?.negative ?? 0} negative,{" "}
            {(progress?.labeled ?? 0) - (progress?.negative ?? 0)} positive)
          </div>
        </div>

        {/* Model Name Input */}
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Model Name *
          </label>
          <input
            type="text"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            placeholder="Enter model name..."
            className="w-full px-3 py-2 rounded-lg border border-stone-300 dark:border-stone-600 bg-white dark:bg-stone-800 text-stone-700 dark:text-stone-200 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none"
          />
        </div>

        {/* Model Type Selection */}
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Model Type
          </label>
          <select
            value={modelType}
            onChange={(e) => setModelType(e.target.value as ClassifierType)}
            className="w-full px-3 py-2 rounded-lg border border-stone-300 dark:border-stone-600 bg-white dark:bg-stone-800 text-stone-700 dark:text-stone-200 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none"
          >
            {Object.entries(MODEL_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <p className="text-xs text-stone-400 mt-1">
            {modelType === "logistic_regression" && "Fast linear classifier (recommended)"}
            {modelType === "svm_linear" && "Linear classifier with margin-based optimization"}
            {modelType === "mlp_small" && "256-unit hidden layer"}
            {modelType === "mlp_medium" && "256+128-unit hidden layers"}
            {modelType === "random_forest" && "Ensemble method, robust to noisy labels"}
          </p>
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

        {/* Create Annotation Project Checkbox */}
        <div className="border-t border-stone-200 dark:border-stone-700 pt-4">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={createAnnotationProject}
              onChange={(e) => setCreateAnnotationProject(e.target.checked)}
              className="mt-1 rounded border-stone-300 text-emerald-600 focus:ring-emerald-500"
            />
            <div className="flex-1">
              <div className="text-sm font-medium text-stone-700 dark:text-stone-300">
                Create Annotation Project
              </div>
              <div className="text-xs text-stone-500 dark:text-stone-400 mt-0.5">
                Export labeled samples to a new annotation project for further curation
              </div>
            </div>
          </label>

          {/* Annotation Project Name Input */}
          {createAnnotationProject && (
            <div className="mt-3 ml-6">
              <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
                Annotation Project Name (optional)
              </label>
              <input
                type="text"
                value={annotationProjectName}
                onChange={(e) => setAnnotationProjectName(e.target.value)}
                placeholder={`Defaults to: ${modelName || "model name"}`}
                className="w-full px-3 py-2 rounded-lg border border-stone-300 dark:border-stone-600 bg-white dark:bg-stone-800 text-stone-700 dark:text-stone-200 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none"
              />
              <p className="text-xs text-stone-400 mt-1">
                Leave empty to use the model name
              </p>
            </div>
          )}
        </div>

        {/* Preview */}
        <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg p-4">
          <div className="text-sm text-emerald-700 dark:text-emerald-300 space-y-1">
            <div className="flex items-center justify-between">
              <span>Custom Model:</span>
              <span className="font-bold">{modelName || "(enter name)"}</span>
            </div>
            <div className="flex items-center justify-between">
              <span>Model Type:</span>
              <span className="font-bold">{MODEL_TYPE_LABELS[modelType]}</span>
            </div>
            {createAnnotationProject && (
              <div className="flex items-center justify-between">
                <span>Annotation Project:</span>
                <span className="font-bold">
                  {annotationProjectName || modelName || "(enter name)"}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <Button
            variant="secondary"
            onClick={onClose}
            disabled={isFinalizing}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            disabled={isFinalizing || !modelName.trim()}
          >
            {isFinalizing ? "Finalizing..." : "Finalize & Save"}
          </Button>
        </div>
      </div>
    </DialogOverlay>
  );
}
