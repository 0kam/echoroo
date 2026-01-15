"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import api from "@/app/api";
import { useProject } from "@/app/hooks/api/useMetadata";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Spinner from "@/lib/components/ui/Spinner";
import { Group, Input, TextArea, Checkbox } from "@/lib/components/inputs";
import MultiCheckbox, {
  type MultiCheckboxOption,
} from "@/lib/components/inputs/MultiCheckbox";
import { textOrUndefined } from "@/lib/utils/forms";

const TARGET_TAXA_OPTIONS: MultiCheckboxOption[] = [
  { value: "Birds", label: "Birds" },
  { value: "Anurans", label: "Anurans" },
  { value: "Insects", label: "Insects" },
  { value: "Bats", label: "Bats" },
  { value: "Land mammals", label: "Land mammals" },
  { value: "Fishes", label: "Fishes" },
  { value: "Cetaceans", label: "Cetaceans" },
];

type ProjectFormState = {
  project_name: string;
  url: string;
  description: string;
  target_taxa: string[];
  admin_name: string;
  admin_email: string;
  is_active: boolean;
};

const INITIAL_PROJECT_FORM: ProjectFormState = {
  project_name: "",
  url: "",
  description: "",
  target_taxa: [],
  admin_name: "",
  admin_email: "",
  is_active: true,
};

export default function ProjectGeneralSettingsPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const projectId = params.project_id as string;

  const [form, setForm] = useState<ProjectFormState>(INITIAL_PROJECT_FORM);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const { query } = useProject(projectId);
  const { data: project, isLoading } = query;

  const updateMutation = useMutation({
    mutationFn: async (payload: Partial<ProjectFormState>) => {
      const updatePayload = {
        project_name: textOrUndefined(payload.project_name),
        url: textOrUndefined(payload.url),
        description: textOrUndefined(payload.description),
        target_taxa:
          payload.target_taxa && payload.target_taxa.length > 0
            ? payload.target_taxa.join(", ")
            : undefined,
        admin_name: textOrUndefined(payload.admin_name),
        admin_email: textOrUndefined(payload.admin_email),
        is_active: payload.is_active,
      };
      return api.metadata.projects.update(projectId, updatePayload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["metadata", "projects"] });
      setSuccess("プロジェクトを更新しました。");
      setError(null);
      setTimeout(() => setSuccess(null), 3000);
    },
    onError: (err) => {
      setError(
        err instanceof Error ? err.message : "プロジェクトの更新に失敗しました。",
      );
      setSuccess(null);
    },
  });

  useEffect(() => {
    if (!project) return;
    const targetTaxaArray = project.target_taxa
      ? project.target_taxa.split(",").map((t) => t.trim()).filter((t) => t)
      : [];
    setForm({
      project_name: project.project_name,
      url: project.url ?? "",
      description: project.description ?? "",
      target_taxa: targetTaxaArray,
      admin_name: project.admin_name ?? "",
      admin_email: project.admin_email ?? "",
      is_active: project.is_active,
    });
  }, [project]);

  const { mutate: updateProject } = updateMutation;

  const handleSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setError(null);
      setSuccess(null);
      updateProject(form);
    },
    [form, updateProject],
  );

  if (isLoading) {
    return (
      <div className="flex justify-center items-center py-12">
        <Spinner />
      </div>
    );
  }

  if (!project) {
    return (
      <Card>
        <p className="text-red-600">プロジェクトが見つかりません。</p>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <h2 className="text-xl font-semibold text-stone-900 dark:text-stone-100 mb-1">
              Project Information
            </h2>
            <p className="text-sm text-stone-500 dark:text-stone-400">
              Basic details about this project.
            </p>
          </div>

          <Group label="Project Name" name="project_name">
            <Input
              value={form.project_name}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  project_name: event.target.value,
                }))
              }
              required
            />
          </Group>

          <Group
            label="Project URL"
            name="url"
            help="Optional project website or documentation link."
          >
            <Input
              value={form.url}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  url: event.target.value,
                }))
              }
              placeholder="https://example.org/project"
            />
          </Group>

          <Group label="Description" name="description">
            <TextArea
              rows={3}
              value={form.description}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  description: event.target.value,
                }))
              }
            />
          </Group>

          <Group label="Target Taxa" name="target_taxa">
            <MultiCheckbox
              options={TARGET_TAXA_OPTIONS}
              selectedValues={form.target_taxa}
              onChange={(values) =>
                setForm((prev) => ({
                  ...prev,
                  target_taxa: values,
                }))
              }
            />
          </Group>

          <Group label="Is Active?" name="is_active">
            <div className="flex items-center gap-2">
              <Checkbox
                checked={form.is_active}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    is_active: event.currentTarget.checked,
                  }))
                }
              />
              <span className="text-sm text-stone-600 dark:text-stone-300">
                非アクティブにするとプロジェクトは一覧に表示されなくなります。
              </span>
            </div>
          </Group>

          <div className="pt-4 border-t border-stone-200 dark:border-stone-700">
            <h3 className="text-lg font-semibold text-stone-900 dark:text-stone-100 mb-3">
              Administrator Contact
            </h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <Group label="Administrator Name" name="admin_name">
                <Input
                  value={form.admin_name}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      admin_name: event.target.value,
                    }))
                  }
                />
              </Group>

              <Group label="Administrator Email" name="admin_email">
                <Input
                  type="email"
                  value={form.admin_email}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      admin_email: event.target.value,
                    }))
                  }
                />
              </Group>
            </div>
          </div>

          {error && (
            <div className="rounded-md bg-red-50 dark:bg-red-900/20 p-4 border border-red-200 dark:border-red-800">
              <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
            </div>
          )}

          {success && (
            <div className="rounded-md bg-emerald-50 dark:bg-emerald-900/20 p-4 border border-emerald-200 dark:border-emerald-800">
              <p className="text-sm text-emerald-600 dark:text-emerald-400">{success}</p>
            </div>
          )}

          <div className="flex justify-end gap-3 pt-4">
            <Button
              mode="text"
              type="button"
              onClick={() => router.push(`/projects/${projectId}`)}
              disabled={updateMutation.isPending}
            >
              キャンセル
            </Button>
            <Button
              variant="primary"
              type="submit"
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? "更新中..." : "変更を保存"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
