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
  // Use Set of tag IDs (numbers) instead of label strings
  const [selectedTagIds, setSelectedTagIds] = useState<Set<number>>(() => {
    // Default to all target tags selected
    return new Set(searchSession.target_tags.map((tt) => tt.tag_id));
  });

  // Get tag counts from progress.tag_counts
  const tagCounts = useMemo(() => {
    if (!progress?.tag_counts) return {};
    return progress.tag_counts;
  }, [progress]);

  // Calculate total selected count
  const totalSelected = useMemo(() => {
    let total = 0;
    selectedTagIds.forEach((tagId) => {
      // tag_counts keys are strings in the schema
      total += tagCounts[String(tagId)] ?? 0;
    });
    return total;
  }, [selectedTagIds, tagCounts]);

  const toggleTag = useCallback((tagId: number) => {
    setSelectedTagIds((prev) => {
      const next = new Set(prev);
      if (next.has(tagId)) {
        next.delete(tagId);
      } else {
        next.add(tagId);
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
      toast.success(`Annotation Project "${result.annotation_project_name}" created successfully!`);
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
    if (selectedTagIds.size === 0) {
      toast.error("Please select at least one tag to include");
      return;
    }

    // Determine if all tags are selected (use null for all)
    const allTagIds = searchSession.target_tags.map((tt) => tt.tag_id);
    const allSelected = allTagIds.length === selectedTagIds.size &&
      allTagIds.every((id) => selectedTagIds.has(id));

    mutateExport({
      name: name.trim(),
      description: description.trim() || undefined,
      include_labeled: true,
      include_tag_ids: allSelected ? null : Array.from(selectedTagIds),
    });
  }, [name, description, selectedTagIds, searchSession.target_tags, mutateExport]);

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

        {/* Tag Selection */}
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-2">
            Include Results with Tags
          </label>
          {searchSession.target_tags.length === 0 ? (
            <div className="text-sm text-stone-500 dark:text-stone-400 italic p-3 bg-stone-50 dark:bg-stone-800/50 rounded-lg">
              No target tags defined for this session
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {searchSession.target_tags.map(({ tag_id, tag, shortcut_key }) => {
                const count = tagCounts[String(tag_id)] ?? 0;
                const isSelected = selectedTagIds.has(tag_id);
                // Use canonical_name or value for display
                const displayName = tag.canonical_name || tag.value;

                return (
                  <button
                    key={tag_id}
                    type="button"
                    onClick={() => toggleTag(tag_id)}
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
                        <div className="font-medium text-stone-700 dark:text-stone-200 flex items-center gap-2">
                          {displayName}
                          <span className="text-xs px-1.5 py-0.5 bg-stone-200 dark:bg-stone-700 rounded text-stone-500 dark:text-stone-400">
                            {shortcut_key}
                          </span>
                        </div>
                        {tag.vernacular_name && (
                          <div className="text-xs text-stone-500 dark:text-stone-400">
                            {tag.vernacular_name}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="text-sm font-bold text-stone-600 dark:text-stone-300">
                      {count}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
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
            disabled={isExporting || selectedTagIds.size === 0 || !name.trim()}
          >
            {isExporting ? "Exporting..." : "Export"}
          </Button>
        </div>
      </div>
    </DialogOverlay>
  );
}
