"use client";

import Link from "next/link";

import useActiveUser from "@/app/hooks/api/useActiveUser";

import Card from "@/lib/components/ui/Card";
import DatasetDatetimeParser from "@/lib/components/datasets/DatasetDatetimeParser";
import type { Dataset } from "@/lib/types";
import { canEditDataset, isProjectMember } from "@/lib/utils/permissions";

function MetadataRow({
  label,
  value,
  action,
}: {
  label: string;
  value: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1 border-b border-stone-200 dark:border-stone-700 py-3 last:border-b-0">
      <span className="text-xs uppercase tracking-wide text-stone-500 dark:text-stone-400">
        {label}
      </span>
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-stone-900 dark:text-stone-100">{value}</div>
        {action}
      </div>
    </div>
  );
}

export default function DatasetMetadataSummary({
  dataset,
}: {
  dataset: Dataset;
}) {
  const { data: activeUser } = useActiveUser();
  const canManage = canEditDataset(activeUser, dataset, dataset.project ?? undefined);
  const isMember = isProjectMember(activeUser, dataset.project ?? undefined);

  const projectAction = dataset.project_id ? (
    <Link
      href={`/projects/${dataset.project_id}`}
      className="text-sm text-emerald-600 dark:text-emerald-300 hover:underline"
    >
      プロジェクト詳細
    </Link>
  ) : undefined;

  const siteLink = dataset.project_id
    ? `/projects/${dataset.project_id}`
    : "#";

  const siteValue =
    dataset.primary_site_id != null ? (
      <div className="flex flex-col">
        <span className="text-stone-900 dark:text-stone-100">
          {dataset.primary_site?.site_name ?? dataset.primary_site_id}
          {dataset.primary_site?.site_id ? (
            <span className="ml-2 text-xs text-stone-500 dark:text-stone-400">
              ({dataset.primary_site.site_id})
            </span>
          ) : null}
        </span>
        {dataset.primary_site?.h3_index ? (
          <span className="text-xs text-stone-500 dark:text-stone-400">
            H3: {dataset.primary_site.h3_index}
          </span>
        ) : null}
      </div>
    ) : (
      "—"
    );

  const recorderValue =
    dataset.primary_recorder_id != null ? (
      <div className="flex flex-col">
        <span className="text-stone-900 dark:text-stone-100">
          {dataset.primary_recorder?.recorder_name ??
            dataset.primary_recorder_id}
          {dataset.primary_recorder?.recorder_id ? (
            <span className="ml-2 text-xs text-stone-500 dark:text-stone-400">
              ({dataset.primary_recorder.recorder_id})
            </span>
          ) : null}
        </span>
        {dataset.primary_recorder?.manufacturer ||
          dataset.primary_recorder?.version ? (
          <span className="text-xs text-stone-500 dark:text-stone-400">
            {[dataset.primary_recorder?.manufacturer, dataset.primary_recorder?.version]
              .filter(Boolean)
              .join(" · ")}
          </span>
        ) : null}
      </div>
    ) : (
      "—"
    );

  return (
    <Card className="p-4 space-y-2">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
          メタデータ
        </h3>
        {canManage && <DatasetDatetimeParser dataset={dataset} />}
      </div>
      <MetadataRow
        label="Project"
        value={
          dataset.project ? (
            <span>
              {dataset.project.project_name}
              <span className="ml-2 text-xs text-stone-500 dark:text-stone-400">
                ({dataset.project.project_id})
              </span>
            </span>
          ) : (
            dataset.project_id ?? "—"
          )
        }
        action={projectAction}
      />
      <MetadataRow
        label="Primary Site"
        value={siteValue}
      />
      <MetadataRow
        label="Primary Recorder"
        value={recorderValue}
      />
      <MetadataRow
        label="License"
        value={
          dataset.license ? (
            <Link
              href={dataset.license.license_link}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-emerald-600 dark:text-emerald-300 hover:underline"
            >
              {dataset.license.license_name}
            </Link>
          ) : dataset.license_id ? (
            dataset.license_id
          ) : (
            "—"
          )
        }
      />
      <MetadataRow label="DOI" value={dataset.doi ?? "—"} />
      {dataset.note ? (
        <MetadataRow
          label="Note"
          value={<span className="whitespace-pre-wrap text-sm">{dataset.note}</span>}
        />
      ) : null}

      {dataset.visibility === "restricted" ? (
        <div className="rounded-md bg-amber-50 dark:bg-amber-900/30 px-3 py-2 text-xs text-amber-700 dark:text-amber-200">
          <p>このデータセットはプロジェクトメンバーのみ閲覧可能です。</p>
          {isMember ? (
            <p>あなたはこのプロジェクトのメンバーです。</p>
          ) : (
            <p>アクセスが必要な場合はプロジェクトマネージャーにお問い合わせください。</p>
          )}
        </div>
      ) : null}
    </Card>
  );
}
