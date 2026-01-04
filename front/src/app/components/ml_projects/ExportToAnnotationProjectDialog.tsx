"use client";

import { useState, useMemo, useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";

import { DialogOverlay } from "@/lib/components/ui/Dialog";
import Button from "@/lib/components/ui/Button";
import { CheckIcon } from "@/lib/components/icons";

import api from "@/app/api";

import type { SearchSession, SearchProgress, ExportToAPRequest } from "@/lib/types";

interface ExportToAnnotationProjectDialogProps {
  isOpen: boolean;
  onClose: () => void;
  mlProjectUuid: string;
  searchSession: SearchSession;
  progress: SearchProgress | null;
}

// Labels that can be included in the export
const EXPORTABLE_LABELS = [
  { value: "positive", label: "Positive (Yes)", description: "Results marked as containing target species" },
  { value: "positive_reference", label: "Positive Reference", description: "Reference examples for positive training" },
  { value: "negative_reference", label: "Negative Reference", description: "Reference examples for negative training" },
];

export default function ExportToAnnotationProjectDialog({
  isOpen,
  onClose,
  mlProjectUuid,
  searchSession,
  progress,
}: ExportToAnnotationProjectDialogProps) {
  const queryClient = useQueryClient();

  const [name, setName] = useState(`AP from ${searchSession.name}`);
  const [description, setDescription] = useState("");
  const [selectedLabels, setSelectedLabels] = useState<Set<string>>(new Set(["positive", "positive_reference"]));

  // Calculate preview counts
  const previewCounts = useMemo(() => {
    if (!progress) return {};
    return {
      positive: progress.positive,
      positive_reference: progress.positive_reference ?? 0,
      negative_reference: progress.negative_reference ?? 0,
    };
  }, [progress]);

  const totalSelected = useMemo(() => {
    let total = 0;
    selectedLabels.forEach((label) => {
      total += previewCounts[label as keyof typeof previewCounts] ?? 0;
    });
    return total;
  }, [selectedLabels, previewCounts]);

  const toggleLabel = useCallback((label: string) => {
    setSelectedLabels((prev) => {
      const next = new Set(prev);
      if (next.has(label)) {
        next.delete(label);
      } else {
        next.add(label);
      }
      return next;
    });
  }, []);

  const exportMutation = useMutation({
    mutationFn: async (data: ExportToAPRequest) => {
      return api.searchSessions.exportToAnnotationProject(
        mlProjectUuid,
        searchSession.uuid,
        data,
      );
    },
    onSuccess: (result) => {
      toast.success(`Annotation Project "${result.name}" created successfully!`);
      queryClient.invalidateQueries({ queryKey: ["ml_project_annotation_projects", mlProjectUuid] });
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
    if (selectedLabels.size === 0) {
      toast.error("Please select at least one label to include");
      return;
    }

    mutateExport({
      name: name.trim(),
      description: description.trim() || undefined,
      include_labels: Array.from(selectedLabels),
      search_session_uuid: searchSession.uuid,
    });
  }, [name, description, selectedLabels, searchSession.uuid, mutateExport]);

  return (
    <DialogOverlay
      title="Export to Annotation Project"
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
            {progress?.total ?? 0} total results, {progress?.labeled ?? 0} labeled
          </div>
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

        {/* Label Selection */}
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-2">
            Include Results with Labels
          </label>
          <div className="flex flex-col gap-2">
            {EXPORTABLE_LABELS.map(({ value, label, description }) => {
              const count = previewCounts[value as keyof typeof previewCounts] ?? 0;
              const isSelected = selectedLabels.has(value);

              return (
                <button
                  key={value}
                  type="button"
                  onClick={() => toggleLabel(value)}
                  className={`flex items-center justify-between p-3 rounded-lg border-2 transition-colors ${
                    isSelected
                      ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20"
                      : "border-stone-200 dark:border-stone-600 hover:border-stone-300 dark:hover:border-stone-500"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div
                      className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ${
                        isSelected
                          ? "bg-emerald-500 border-emerald-500 text-white"
                          : "border-stone-400 dark:border-stone-500"
                      }`}
                    >
                      {isSelected && <CheckIcon className="w-3 h-3" />}
                    </div>
                    <div className="text-left">
                      <div className="font-medium text-stone-700 dark:text-stone-200">
                        {label}
                      </div>
                      <div className="text-xs text-stone-500 dark:text-stone-400">
                        {description}
                      </div>
                    </div>
                  </div>
                  <div className="text-sm font-bold text-stone-600 dark:text-stone-300">
                    {count}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Preview */}
        <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-emerald-700 dark:text-emerald-300">
              Total clips to export:
            </span>
            <span className="text-lg font-bold text-emerald-600 dark:text-emerald-400">
              {totalSelected}
            </span>
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
            disabled={isExporting || selectedLabels.size === 0 || !name.trim()}
          >
            {isExporting ? "Exporting..." : "Export"}
          </Button>
        </div>
      </div>
    </DialogOverlay>
  );
}
