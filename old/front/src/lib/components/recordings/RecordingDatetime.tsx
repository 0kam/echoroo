import { DateIcon, TimeIcon, WarningIcon, CheckIcon } from "@/lib/components/icons";
import Tooltip from "@/lib/components/ui/Tooltip";

import type { Recording } from "@/lib/types";

type DatetimeParseStatus = "pending" | "success" | "failed";

function StatusBadge({ status }: { status: DatetimeParseStatus }) {
  if (status === "success") {
    return (
      <Tooltip tooltip="Datetime parsed successfully from filename">
        <CheckIcon className="inline-block w-4 h-4 text-emerald-500" />
      </Tooltip>
    );
  }
  if (status === "failed") {
    return (
      <Tooltip tooltip="Failed to parse datetime from filename">
        <WarningIcon className="inline-block w-4 h-4 text-amber-500" />
      </Tooltip>
    );
  }
  return null;
}

function formatDatetime(datetime: Date | null | undefined): {
  date: string;
  time: string;
} | null {
  if (datetime == null) return null;

  const d = new Date(datetime);
  return {
    date: d.toLocaleDateString(),
    time: d.toLocaleTimeString(),
  };
}

export default function RecordingDatetime({
  recording,
}: {
  recording: Recording;
}) {
  const formatted = formatDatetime(recording.datetime);
  const status = recording.datetime_parse_status;

  if (formatted == null) {
    return (
      <div className="inline-flex items-center gap-2 text-stone-400 dark:text-stone-600">
        <DateIcon className="w-5 h-5" />
        <span className="text-sm">No datetime</span>
        {status === "failed" && recording.datetime_parse_error && (
          <Tooltip tooltip={recording.datetime_parse_error}>
            <WarningIcon className="w-4 h-4 text-amber-500" />
          </Tooltip>
        )}
      </div>
    );
  }

  return (
    <div className="inline-flex items-center gap-4">
      <div className="inline-flex items-center gap-1">
        <DateIcon className="w-5 h-5 text-stone-500" />
        <span>{formatted.date}</span>
        <StatusBadge status={status} />
      </div>
      <div className="inline-flex items-center gap-1">
        <TimeIcon className="w-5 h-5 text-stone-500" />
        <span>{formatted.time}</span>
      </div>
    </div>
  );
}
