import {
  ColumnDef,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useMemo, useState } from "react";

import {
  DateIcon,
  LocationIcon,
  NotesIcon,
} from "@/lib/components/icons";
import Checkbox from "@/lib/components/inputs/Checkbox";
import TableCell from "@/lib/components/tables/TableCell";
import TableHeader from "@/lib/components/tables/TableHeader";
import TableInput from "@/lib/components/tables/TableInput";
import Button from "@/lib/components/ui/Button";

import type { Note, Recording, RecordingUpdate } from "@/lib/types";

const defaultPathFormatter = (path: string) => path;

export default function useRecordingTable({
  data,
  pathFormatter = defaultPathFormatter,
  onClickRecording,
  onUpdateRecording,
}: {
  data: Recording[];
  pathFormatter?: (path: string) => string;
  onUpdateRecording?: ({
    recording,
    data,
    index,
  }: {
    recording: Recording;
    data: RecordingUpdate;
    index: number;
  }) => void;
  onClickRecording?: (recording: Recording) => void;
}) {
  const [rowSelection, setRowSelection] = useState({});

  const selectRow: ColumnDef<Recording> = useMemo(
    () => ({
      id: "select",
      maxSize: 33,
      enableResizing: false,
      header: ({ table }) => (
        <Checkbox
          {...{
            checked: table.getIsAllRowsSelected(),
            indeterminate: table.getIsSomeRowsSelected(),
            onChange: table.getToggleAllRowsSelectedHandler(),
          }}
        />
      ),
      cell: ({ row }) => (
        <div className="flex justify-center px-1">
          <Checkbox
            {...{
              checked: row.getIsSelected(),
              disabled: !row.getCanSelect(),
              indeterminate: row.getIsSomeSelected(),
              onChange: row.getToggleSelectedHandler(),
            }}
          />
        </div>
      ),
    }),
    [],
  );

  const pathRow: ColumnDef<Recording> = useMemo(
    () => ({
      accessorFn: (row) => row.path,
      id: "path",
      header: () => <TableHeader>Path</TableHeader>,
      size: 200,
      enableResizing: true,
      footer: (props) => props.column.id,
      cell: ({ row }) => {
        const path = row.getValue("path") as string;
        return (
          <TableCell>
            <Button
              mode="text"
              align="text-left"
              onClick={() => onClickRecording?.(row.original)}
            >
              {pathFormatter(path)}
            </Button>
          </TableCell>
        );
      },
    }),
    [onClickRecording, pathFormatter],
  );

  const durationRow: ColumnDef<Recording> = useMemo(
    () => ({
      id: "duration",
      header: () => <TableHeader>Duration</TableHeader>,
      enableResizing: true,
      size: 100,
      accessorFn: (row) => row.duration.toFixed(2),
      cell: ({ row }) => {
        const duration = row.getValue("duration") as string;
        return <TableCell>{duration}</TableCell>;
      },
    }),
    [],
  );

  const samplerateRow: ColumnDef<Recording> = useMemo(
    () => ({
      id: "samplerate",
      accessorKey: "samplerate",
      header: () => <TableHeader>Sample Rate</TableHeader>,
      enableResizing: true,
      size: 120,
      footer: (props) => props.column.id,
      cell: ({ row }) => {
        const samplerate = row.getValue("samplerate") as string;
        return <TableCell>{samplerate}</TableCell>;
      },
    }),
    [],
  );

  const bitDepthRow: ColumnDef<Recording> = useMemo(
    () => ({
      id: "bit_depth",
      accessorKey: "bit_depth",
      header: () => <TableHeader>Bit Depth</TableHeader>,
      enableResizing: true,
      size: 100,
      footer: (props) => props.column.id,
      cell: ({ row }) => {
        const bitDepth = row.getValue("bit_depth") as number | null;
        return (
          <TableCell>
            {bitDepth != null ? `${bitDepth}-bit` : "—"}
          </TableCell>
        );
      },
    }),
    [],
  );

  const timeExpansionRow: ColumnDef<Recording> = useMemo(
    () => ({
      id: "time_expansion",
      accessorKey: "time_expansion",
      header: () => <TableHeader>Time Expansion</TableHeader>,
      enableResizing: true,
      size: 120,
      footer: (props) => props.column.id,
      cell: ({ row }) => {
        const value = row.getValue("time_expansion") as string;
        return (
          <TableInput
            onChange={(value) => {
              if (value === null) return;
              onUpdateRecording?.({
                recording: row.original,
                data: { time_expansion: parseFloat(value) },
                index: row.index,
              });
            }}
            type="number"
            value={value}
          />
        );
      },
    }),
    [onUpdateRecording],
  );

  const datetimeRow: ColumnDef<Recording> = useMemo(
    () => ({
      id: "datetime",
      enableResizing: true,
      size: 200,
      header: () => {
        return (
          <TableHeader>
            <DateIcon className="inline-block mr-2 w-5 h-5 align-middle text-stone-500" />
            Datetime
          </TableHeader>
        );
      },
      cell: ({ row }) => {
        const recording = row.original;

        // Prioritize parsed datetime over legacy date+time
        let displayValue = "";
        let statusIcon = null;

        if (recording.datetime) {
          displayValue = new Date(recording.datetime).toLocaleString("ja-JP", {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          });

          // Status indicator for parsed datetime
          if (recording.datetime_parse_status === "success") {
            statusIcon = (
              <span className="text-emerald-500 mr-1" title="パース成功">
                ✓
              </span>
            );
          } else if (recording.datetime_parse_status === "failed") {
            statusIcon = (
              <span className="text-red-500 mr-1" title={recording.datetime_parse_error || "パース失敗"}>
                ⚠
              </span>
            );
          } else if (recording.datetime_parse_status === "pending") {
            statusIcon = (
              <span className="text-stone-400 mr-1" title="パース待ち">
                ⏳
              </span>
            );
          }
        } else if (recording.date) {
          // Fallback to legacy date+time
          const dateStr = recording.date.toLocaleDateString("ja-JP", {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
          });
          const timeStr = recording.time || "";
          displayValue = timeStr ? `${dateStr} ${timeStr}` : dateStr;
        }

        return (
          <TableCell>
            <div className="flex items-center">
              {statusIcon}
              <span className="text-sm">{displayValue || "—"}</span>
            </div>
          </TableCell>
        );
      },
      accessorFn: (row) => {
        if (row.datetime) {
          return new Date(row.datetime).toISOString();
        }
        if (row.date) {
          return row.date.toISOString();
        }
        return "";
      },
    }),
    [],
  );

  const locationRow: ColumnDef<Recording> = useMemo(
    () => ({
      id: "location",
      enableResizing: true,
      size: 180,
      header: () => {
        return (
          <TableHeader>
            <LocationIcon className="inline-block mr-2 w-5 h-5 align-middle text-stone-500" />
            Location
          </TableHeader>
        );
      },
      accessorFn: (row) => {
        if (row.h3_index) {
          return row.h3_index;
        }
        if (row.latitude && row.longitude) {
          return `${row.latitude}, ${row.longitude}`;
        }
        return "";
      },
      cell: ({ row }) => {
        const recording = row.original;

        // Prioritize H3 index (from dataset site)
        if (recording.h3_index) {
          const siteName = recording.dataset?.primary_site?.site_name;
          return (
            <TableCell>
              <div className="flex flex-col">
                {siteName && (
                  <span className="text-xs text-stone-500 dark:text-stone-400">
                    {siteName}
                  </span>
                )}
                <span className="text-xs font-mono text-stone-700 dark:text-stone-300">
                  {recording.h3_index}
                </span>
              </div>
            </TableCell>
          );
        }

        // Fallback to legacy lat/lon (read-only)
        if (recording.latitude && recording.longitude) {
          return (
            <TableCell>
              <span className="text-xs font-mono text-stone-700 dark:text-stone-300">
                {recording.latitude.toFixed(4)}, {recording.longitude.toFixed(4)}
              </span>
            </TableCell>
          );
        }

        return <TableCell>—</TableCell>;
      },
    }),
    [onUpdateRecording],
  );

  const notesRow: ColumnDef<Recording> = useMemo(
    () => ({
      id: "notes",
      enableResizing: true,
      header: () => {
        return (
          <TableHeader>
            <NotesIcon className="inline-block mr-2 w-5 h-5 align-middle text-stone-500" />
            Notes
          </TableHeader>
        );
      },
      accessorFn: (row) => row.notes,
      cell: ({ row }) => {
        const notes = row.getValue("notes") as Note[];
        if ((notes || []).length == 0) return null;

        return (
          <TableCell>
            <Button
              mode="text"
              align="text-left"
              onClick={() => onClickRecording?.(row.original)}
            >
              <NotesIcon className="inline-block mr-1 w-4 h-4 text-blue-500 align-middle" />
              {notes.length} notes
            </Button>
          </TableCell>
        );
      },
    }),
    [onClickRecording],
  );

  // Column definitions
  const columns: ColumnDef<Recording>[] = useMemo(
    () => [
      selectRow,
      pathRow,
      durationRow,
      samplerateRow,
      bitDepthRow,
      timeExpansionRow,
      datetimeRow,
      locationRow,
      notesRow,
    ],
    [
      selectRow,
      pathRow,
      durationRow,
      samplerateRow,
      bitDepthRow,
      timeExpansionRow,
      datetimeRow,
      locationRow,
      notesRow,
    ],
  );

  return useReactTable<Recording>({
    data,
    columns,
    state: { rowSelection },
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    columnResizeMode: "onChange",
    getCoreRowModel: getCoreRowModel(),
  });
}
