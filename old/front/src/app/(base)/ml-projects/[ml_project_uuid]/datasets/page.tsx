"use client";

/**
 * Datasets page for ML Project.
 *
 * Displays a list of dataset scopes associated with the ML project.
 * Users can add new dataset scopes and remove existing ones.
 */
import { useCallback, useState } from "react";
import { useParams } from "next/navigation";
import {
  Database,
  Plus,
  Trash2,
  Cpu,
  Calendar,
  FileAudio,
} from "lucide-react";

import {
  useMLProjectDatasetScopes,
  useAddMLProjectDatasetScope,
  useRemoveMLProjectDatasetScope,
} from "@/app/hooks/api";
import { AddDatasetScopeDialog } from "@/app/components/ml_projects";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import { DialogOverlay } from "@/lib/components/ui/Dialog";

import type { MLProjectDatasetScope, MLProjectDatasetScopeCreate } from "@/lib/types";

function DeleteConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  datasetName,
  isDeleting,
}: {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  datasetName: string;
  isDeleting: boolean;
}) {
  return (
    <DialogOverlay title="Remove Dataset Scope" isOpen={isOpen} onClose={onClose}>
      <div className="w-[400px] space-y-4">
        <p className="text-stone-700 dark:text-stone-300">
          Are you sure you want to remove <strong>{datasetName}</strong> from this ML project?
        </p>
        <p className="text-sm text-stone-500 dark:text-stone-400">
          This will not delete the dataset itself, only remove it from this ML project.
        </p>
        <div className="flex justify-end gap-2 pt-4">
          <Button variant="secondary" onClick={onClose} disabled={isDeleting}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={onConfirm}
            disabled={isDeleting}
          >
            {isDeleting ? "Removing..." : "Remove"}
          </Button>
        </div>
      </div>
    </DialogOverlay>
  );
}

function DatasetScopeCard({
  scope,
  onDelete,
  isDeleting,
}: {
  scope: MLProjectDatasetScope;
  onDelete: () => void;
  isDeleting?: boolean;
}) {
  const { dataset, foundation_model_run: run } = scope;

  return (
    <Card className="relative">
      {/* Dataset Info */}
      <div className="space-y-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Database className="w-5 h-5 text-emerald-500" />
            <h3 className="font-medium text-stone-900 dark:text-stone-100">
              {dataset.name}
            </h3>
          </div>
          {dataset.description && (
            <p className="text-sm text-stone-500 dark:text-stone-400 line-clamp-2">
              {dataset.description}
            </p>
          )}
        </div>

        {/* Stats */}
        <div className="flex flex-wrap gap-3 text-sm text-stone-500 dark:text-stone-400">
          <span className="inline-flex items-center gap-1">
            <FileAudio className="w-4 h-4" />
            {dataset.recording_count.toLocaleString()} recordings
          </span>
        </div>

        {/* Foundation Model Run Info */}
        <div className="pt-3 border-t border-stone-200 dark:border-stone-700">
          <div className="flex items-center gap-2 text-sm">
            <Cpu className="w-4 h-4 text-blue-500" />
            <span className="font-medium text-stone-700 dark:text-stone-300">
              {run.foundation_model?.display_name ?? "Unknown Model"}
            </span>
          </div>
          <div className="flex flex-wrap gap-3 mt-2 text-xs text-stone-500 dark:text-stone-400">
            <span className="inline-flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {new Date(run.created_on).toLocaleDateString()}
            </span>
            {run.total_clips != null && (
              <span>{run.total_clips.toLocaleString()} clips</span>
            )}
            {run.total_detections != null && (
              <span>{run.total_detections.toLocaleString()} detections</span>
            )}
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-end gap-2 mt-4 pt-3 border-t border-stone-200 dark:border-stone-700">
        <Button variant="danger" mode="text" onClick={onDelete} disabled={isDeleting}>
          <Trash2 className="w-4 h-4 mr-1" />
          {isDeleting ? "Removing..." : "Remove"}
        </Button>
      </div>
    </Card>
  );
}

export default function DatasetsPage() {
  const params = useParams();
  const mlProjectUuid = params.ml_project_uuid as string;

  const [showAddDialog, setShowAddDialog] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ uuid: string; name: string } | null>(null);

  // Fetch dataset scopes
  const { data: scopes, isLoading } = useMLProjectDatasetScopes(mlProjectUuid);

  // Mutations
  const addMutation = useAddMLProjectDatasetScope(mlProjectUuid);
  const removeMutation = useRemoveMLProjectDatasetScope(mlProjectUuid);

  const handleAdd = useCallback(
    (data: MLProjectDatasetScopeCreate) => {
      addMutation.mutate(data, {
        onSuccess: () => {
          setShowAddDialog(false);
        },
      });
    },
    [addMutation],
  );

  const handleDelete = useCallback(
    (scopeUuid: string, datasetName: string) => {
      console.log("handleDelete called with:", scopeUuid, datasetName);
      setDeleteTarget({ uuid: scopeUuid, name: datasetName });
    },
    [],
  );

  const handleConfirmDelete = useCallback(() => {
    if (deleteTarget) {
      console.log("Confirming deletion of:", deleteTarget.uuid);
      removeMutation.mutate(deleteTarget.uuid, {
        onSuccess: () => {
          setDeleteTarget(null);
        },
      });
    }
  }, [deleteTarget, removeMutation]);

  if (isLoading) {
    return <Loading />;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-stone-900 dark:text-stone-100">
            Dataset Scopes
          </h2>
          <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
            Configure datasets and their foundation model runs for similarity
            search
          </p>
        </div>
        <Button variant="primary" onClick={() => setShowAddDialog(true)}>
          <Plus className="w-4 h-4 mr-2" />
          Add Dataset
        </Button>
      </div>

      {/* Dataset Scope Grid */}
      {!scopes || scopes.length === 0 ? (
        <Empty>
          <Database className="w-12 h-12 mb-4 text-stone-400" />
          <p className="text-lg font-medium">No dataset scopes</p>
          <p className="text-sm text-stone-500 mt-1">
            Add a dataset scope to enable similarity search across embeddings
          </p>
          <Button
            variant="primary"
            onClick={() => setShowAddDialog(true)}
            className="mt-4"
          >
            <Plus className="w-4 h-4 mr-2" />
            Add Dataset
          </Button>
        </Empty>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {scopes.map((scope) => (
            <DatasetScopeCard
              key={scope.uuid}
              scope={scope}
              onDelete={() => handleDelete(scope.uuid, scope.dataset.name)}
              isDeleting={removeMutation.isPending}
            />
          ))}
        </div>
      )}

      {/* Add Dialog */}
      <AddDatasetScopeDialog
        isOpen={showAddDialog}
        onClose={() => setShowAddDialog(false)}
        onSubmit={handleAdd}
        isSubmitting={addMutation.isPending}
      />

      {/* Delete Confirmation Dialog */}
      {deleteTarget && (
        <DeleteConfirmDialog
          isOpen={!!deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onConfirm={handleConfirmDelete}
          datasetName={deleteTarget.name}
          isDeleting={removeMutation.isPending}
        />
      )}
    </div>
  );
}
