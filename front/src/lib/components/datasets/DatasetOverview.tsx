import { type ReactNode } from "react";

import { IssueIcon, RecordingsIcon, WarningIcon } from "@/lib/components/icons";
import Card from "@/lib/components/ui/Card";
import { H3 } from "@/lib/components/ui/Headings";
import MetricBadge from "@/lib/components/ui/MetricBadge";
import VisibilityBadge from "@/lib/components/ui/VisibilityBadge";

import type { Dataset } from "@/lib/types";

export default function DatasetOverview({
  dataset,
  numIssues = 0,
  numMissing = 0,
  isLoading = false,
  actionSlot,
  children,
  onClickDatasetRecordings,
  onClickDatasetIssues,
  onClickDatasetMissing,
}: {
  dataset: Dataset;
  numIssues?: number;
  numMissing?: number;
  isLoading?: boolean;
  actionSlot?: ReactNode;
  children?: ReactNode;
  onClickDatasetRecordings?: () => void;
  onClickDatasetIssues?: () => void;
  onClickDatasetMissing?: () => void;
}) {
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          <H3 className="whitespace-nowrap">Dataset Overview</H3>
          <VisibilityBadge visibility={dataset.visibility} className="flex-shrink-0" />
        </div>
        {actionSlot ? (
          <div className="flex items-center gap-2 flex-shrink-0">{actionSlot}</div>
        ) : null}
      </div>
      <div className="flex flex-row gap-2 justify-around">
        <MetricBadge
          onClick={onClickDatasetRecordings}
          icon={
            <RecordingsIcon className="inline-block w-8 h-8 text-blue-500" />
          }
          title="Recordings"
          value={dataset.recording_count}
        />
        <MetricBadge
          onClick={onClickDatasetIssues}
          icon={<IssueIcon className="inline-block w-8 h-8 text-amber-500" />}
          title="Metadata Issues"
          value={numIssues}
          isLoading={isLoading}
        />
        <MetricBadge
          onClick={onClickDatasetMissing}
          icon={<WarningIcon className="inline-block w-8 h-8 text-red-500" />}
          title="Missing Files"
          value={numMissing}
          isLoading={isLoading}
        />
      </div>
      {children ? <div className="mt-4">{children}</div> : null}
    </Card>
  );
}
