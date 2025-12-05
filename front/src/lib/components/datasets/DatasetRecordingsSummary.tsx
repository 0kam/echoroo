import { RecordingsIcon } from "@/lib/components/icons";
import SecondaryNavBar from "@/lib/components/navigation/SecondaryNavBar";

import type { Dataset } from "@/lib/types";

export default function DatasetRecordingSummary({
  dataset,
}: { dataset: Dataset }) {
  return (
    <SecondaryNavBar
      title="Recordings"
      icon={
        <>
          <RecordingsIcon className="inline-block mr-1 w-5 h-5 align-middle text-stone-500" />
          <span className="mr-1 font-semibold text-stone-500">
            {dataset?.recording_count}
          </span>
        </>
      }
    />
  );
}
