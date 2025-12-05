import useRecording from "@/app/hooks/api/useRecording";

import Error from "@/app/error";
import Loading from "@/app/loading";

import RecordingHeaderBase from "@/lib/components/recordings/RecordingHeader";

import type { Recording } from "@/lib/types";

export default function RecordingHeader({
  recording,
}: {
  recording: Recording;
}) {
  const { data, isLoading, error } = useRecording({
    uuid: recording.uuid,
    recording,
  });

  if (isLoading) {
    return <Loading />;
  }

  if (data == null) {
    return <Error error={error || undefined} />;
  }

  return <RecordingHeaderBase recording={data} />;
}
