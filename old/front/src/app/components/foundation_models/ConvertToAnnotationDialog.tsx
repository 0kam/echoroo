"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { AlertTriangle, ArrowRight, FileText, Loader2 } from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import { DialogOverlay } from "@/lib/components/ui/Dialog";
import Input from "@/lib/components/inputs/Input";
import InputGroup from "@/lib/components/inputs/InputGroup";
import TextArea from "@/lib/components/inputs/TextArea";

// ============================================================================
// Types
// ============================================================================

export interface ConvertToAnnotationDialogProps {
  /** The foundation model run UUID */
  runUuid: string;
  /** Whether a species filter has been applied to the run */
  hasFilterApplied: boolean;
  /** The UUID of the filter application (if applied) */
  filterApplicationUuid?: string;
  /** The name of the foundation model (for default naming) */
  modelName?: string;
  /** Controls whether the dialog is open */
  open: boolean;
  /** Callback when the dialog open state changes */
  onOpenChange: (open: boolean) => void;
  /** Callback when the conversion is successful */
  onSuccess: (annotationProjectUuid: string) => void;
  /** Callback to open the species filter dialog */
  onApplyFilter?: () => void;
}

type DialogStep = "warning" | "form";

// ============================================================================
// Main Component
// ============================================================================

export default function ConvertToAnnotationDialog({
  runUuid,
  hasFilterApplied,
  filterApplicationUuid,
  modelName = "Foundation Model",
  open,
  onOpenChange,
  onSuccess,
  onApplyFilter,
}: ConvertToAnnotationDialogProps) {
  // If no filter applied, show warning first; otherwise go directly to form
  const [step, setStep] = useState<DialogStep>(
    hasFilterApplied ? "form" : "warning"
  );
  const [name, setName] = useState(`Annotations from ${modelName}`);
  const [description, setDescription] = useState("");
  const [includeOnlyFiltered, setIncludeOnlyFiltered] = useState(true);

  const queryClient = useQueryClient();

  // Reset state when dialog opens or hasFilterApplied changes
  useEffect(() => {
    if (open) {
      setStep(hasFilterApplied ? "form" : "warning");
      setName(`Annotations from ${modelName}`);
      setDescription("");
      setIncludeOnlyFiltered(true);
    }
  }, [open, hasFilterApplied, modelName]);

  // Handle dialog open/close
  const handleOpenChange = useCallback(
    (isOpen: boolean) => {
      onOpenChange(isOpen);
    },
    [onOpenChange]
  );

  // Mutation for conversion
  const convertMutation = useMutation({
    mutationFn: async () => {
      return await api.foundationModels.convertToAnnotationProject(runUuid, {
        name: name.trim(),
        description: description.trim() || undefined,
        include_only_filtered: hasFilterApplied ? includeOnlyFiltered : false,
        species_filter_application_uuid: hasFilterApplied
          ? filterApplicationUuid
          : undefined,
      });
    },
    onSuccess: (data) => {
      // Invalidate related queries
      void queryClient.invalidateQueries({ queryKey: ["annotation_projects"] });
      void queryClient.invalidateQueries({
        queryKey: ["foundation-models", "runs", runUuid],
      });
      handleOpenChange(false);
      onSuccess(data.annotation_project_uuid);
    },
  });

  const handleApplyFilter = useCallback(() => {
    handleOpenChange(false);
    onApplyFilter?.();
  }, [handleOpenChange, onApplyFilter]);

  const handleContinueWithoutFilter = useCallback(() => {
    setStep("form");
  }, []);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!name.trim()) return;
      convertMutation.mutate();
    },
    [name, convertMutation]
  );

  // Extract error message from the mutation error
  const errorMessage = useMemo(() => {
    if (!convertMutation.error) return null;

    const error = convertMutation.error;
    if (error instanceof AxiosError && error.response?.data?.message) {
      return error.response.data.message;
    }

    return "Failed to create annotation project. Please try again.";
  }, [convertMutation.error]);

  if (!open) return null;

  return (
    <DialogOverlay
      title="Convert to Annotation Project"
      isOpen={open}
      onClose={() => handleOpenChange(false)}
    >
      <div className="w-[480px]">
        {step === "warning" ? (
          // Warning Step
          <div className="space-y-6">
            <Card className="border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-900/20">
              <div className="flex gap-3">
                <AlertTriangle className="h-5 w-5 flex-shrink-0 text-amber-500" />
                <div className="space-y-2">
                  <h4 className="font-medium text-amber-800 dark:text-amber-200">
                    Species Filter Recommended
                  </h4>
                  <p className="text-sm text-amber-700 dark:text-amber-300">
                    Applying a species filter before conversion helps remove
                    unlikely species detections based on geographic occurrence
                    data. This reduces false positives and improves annotation
                    quality.
                  </p>
                </div>
              </div>
            </Card>

            <div className="flex flex-col gap-3">
              <Button
                mode="filled"
                variant="primary"
                onClick={handleApplyFilter}
                className="w-full justify-center"
              >
                Apply Species Filter First
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
              <Button
                mode="outline"
                variant="secondary"
                onClick={handleContinueWithoutFilter}
                className="w-full justify-center"
              >
                Continue Without Filter
              </Button>
            </div>
          </div>
        ) : (
          // Form Step
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="flex items-start gap-3 rounded-lg bg-stone-50 p-3 dark:bg-stone-800">
              <FileText className="h-5 w-5 flex-shrink-0 text-stone-500" />
              <p className="text-sm text-stone-600 dark:text-stone-400">
                This will create a new annotation project with tasks generated
                from the foundation model detections.
              </p>
            </div>

            <InputGroup
              name="name"
              label="Project Name"
              help="A name for the new annotation project"
            >
              <Input
                id="name"
                name="name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Enter project name"
                required
                autoFocus
              />
            </InputGroup>

            <InputGroup
              name="description"
              label="Description"
              help="Optional description for the annotation project"
            >
              <TextArea
                id="description"
                name="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Enter project description (optional)"
                rows={3}
              />
            </InputGroup>

            {hasFilterApplied && (
              <div className="flex items-start gap-3 rounded-lg border border-stone-200 p-4 dark:border-stone-700">
                <input
                  type="checkbox"
                  id="includeOnlyFiltered"
                  checked={includeOnlyFiltered}
                  onChange={(e) => setIncludeOnlyFiltered(e.target.checked)}
                  className="mt-0.5 h-4 w-4 cursor-pointer rounded border-stone-300 text-emerald-600 focus:ring-emerald-500"
                />
                <label
                  htmlFor="includeOnlyFiltered"
                  className="cursor-pointer text-sm"
                >
                  <span className="font-medium text-stone-900 dark:text-stone-100">
                    Only include filtered detections
                  </span>
                  <p className="mt-0.5 text-stone-500 dark:text-stone-400">
                    Only detections that passed the species filter will be
                    converted to annotation tasks.
                  </p>
                </label>
              </div>
            )}

            {convertMutation.isError && errorMessage && (
              <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300">
                {errorMessage}
              </div>
            )}

            <div className="flex justify-end gap-3 border-t border-stone-200 pt-4 dark:border-stone-700">
              <Button
                type="button"
                mode="outline"
                variant="secondary"
                onClick={() => handleOpenChange(false)}
                disabled={convertMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                mode="filled"
                variant="primary"
                disabled={!name.trim() || convertMutation.isPending}
              >
                {convertMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Creating...
                  </>
                ) : (
                  "Create Annotation Project"
                )}
              </Button>
            </div>
          </form>
        )}
      </div>
    </DialogOverlay>
  );
}
