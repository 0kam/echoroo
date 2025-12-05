import InferenceJobCard, { type InferenceJobUI } from "./InferenceJobCard";

import { ModelIcon } from "@/lib/components/icons";
import Empty from "@/lib/components/ui/Empty";

export default function InferenceJobList({
  jobs,
  onJobCancelled,
  onJobUpdated,
}: {
  jobs: InferenceJobUI[];
  onJobCancelled?: (jobId: string) => void;
  onJobUpdated?: (job: InferenceJobUI) => void;
}) {
  if (jobs.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
          Inference Jobs
        </h2>
        <Empty>
          <ModelIcon className="w-12 h-12 mb-2" />
          <p className="text-base font-medium">No inference jobs yet</p>
          <p className="text-sm">
            Create a new inference job to start processing your recordings with
            machine learning models.
          </p>
        </Empty>
      </div>
    );
  }

  // Sort jobs: running first, then pending, then by start time (newest first)
  const sortedJobs = [...jobs].sort((a, b) => {
    const statusOrder: Record<string, number> = {
      running: 0,
      pending: 1,
      failed: 2,
      completed: 3,
      cancelled: 4,
    };
    const statusDiff = statusOrder[a.status] - statusOrder[b.status];
    if (statusDiff !== 0) return statusDiff;
    return b.startedAt.getTime() - a.startedAt.getTime();
  });

  const runningJobs = sortedJobs.filter((job) => job.status === "running");
  const pendingJobs = sortedJobs.filter((job) => job.status === "pending");
  const completedJobs = sortedJobs.filter(
    (job) =>
      job.status === "completed" ||
      job.status === "failed" ||
      job.status === "cancelled",
  );

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
        Inference Jobs
      </h2>

      {runningJobs.length > 0 && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-medium text-stone-600 dark:text-stone-400 uppercase tracking-wider">
            Running ({runningJobs.length})
          </h3>
          <div className="grid gap-4 md:grid-cols-2">
            {runningJobs.map((job) => (
              <InferenceJobCard
                key={job.id}
                job={job}
                onCancel={onJobCancelled}
                onUpdate={onJobUpdated}
              />
            ))}
          </div>
        </div>
      )}

      {pendingJobs.length > 0 && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-medium text-stone-600 dark:text-stone-400 uppercase tracking-wider">
            Pending ({pendingJobs.length})
          </h3>
          <div className="grid gap-4 md:grid-cols-2">
            {pendingJobs.map((job) => (
              <InferenceJobCard
                key={job.id}
                job={job}
                onCancel={onJobCancelled}
                onUpdate={onJobUpdated}
              />
            ))}
          </div>
        </div>
      )}

      {completedJobs.length > 0 && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-medium text-stone-600 dark:text-stone-400 uppercase tracking-wider">
            Completed ({completedJobs.length})
          </h3>
          <div className="grid gap-4 md:grid-cols-2">
            {completedJobs.map((job) => (
              <InferenceJobCard
                key={job.id}
                job={job}
                onCancel={onJobCancelled}
                onUpdate={onJobUpdated}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
