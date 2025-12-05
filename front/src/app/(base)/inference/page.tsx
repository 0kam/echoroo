"use client";

/**
 * Page module for displaying and managing inference jobs.
 *
 * This page includes a hero section with the title "Inference" and components
 * for listing, creating, and managing inference jobs.
 *
 * @module pages/inference
 */
import { useCallback, useState } from "react";

import { type InferenceJobUI } from "@/app/components/inference/InferenceJobCard";
import InferenceJobCreate from "@/app/components/inference/InferenceJobCreate";
import InferenceJobList from "@/app/components/inference/InferenceJobList";

import Hero from "@/lib/components/ui/Hero";

export default function Page() {
  const [jobs, setJobs] = useState<InferenceJobUI[]>([]);

  const handleJobCreated = useCallback((job: InferenceJobUI) => {
    setJobs((prev) => [job, ...prev]);
  }, []);

  const handleJobCancelled = useCallback((jobId: string) => {
    setJobs((prev) =>
      prev.map((job) =>
        job.id === jobId ? { ...job, status: "cancelled" as const } : job,
      ),
    );
  }, []);

  const handleJobUpdated = useCallback((updatedJob: InferenceJobUI) => {
    setJobs((prev) =>
      prev.map((job) => (job.id === updatedJob.id ? updatedJob : job)),
    );
  }, []);

  return (
    <>
      <Hero text="Inference" />
      <div className="container mx-auto px-4 py-6">
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-1">
            <InferenceJobCreate onJobCreated={handleJobCreated} />
          </div>
          <div className="lg:col-span-2">
            <InferenceJobList
              jobs={jobs}
              onJobCancelled={handleJobCancelled}
              onJobUpdated={handleJobUpdated}
            />
          </div>
        </div>
      </div>
    </>
  );
}
