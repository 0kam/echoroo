"use client";

/**
 * ML Project Overview/Dashboard page.
 *
 * Displays project statistics, status progress indicator, quick actions,
 * and recent activity for an ML project.
 */
import { useContext, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Music,
  Search,
  Cpu,
  Play,
  Database,
  Calendar,
  ArrowRight,
  CheckCircle2,
  Circle,
  Tag,
} from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Link from "@/lib/components/ui/Link";
import ProgressBar from "@/lib/components/ui/ProgressBar";

import type { MLProject, MLProjectStatus } from "@/lib/types";

import MLProjectContext from "./context";

// Define workflow steps - matches backend MLProjectStatus enum
const WORKFLOW_STEPS: { status: MLProjectStatus; label: string; description: string }[] = [
  { status: "draft", label: "Draft", description: "Configure project and add reference sounds" },
  { status: "active", label: "Active", description: "Search, label, and prepare training data" },
  { status: "training", label: "Training", description: "Train custom detection model" },
  { status: "inference", label: "Inference", description: "Run model on new data" },
  { status: "completed", label: "Completed", description: "Project workflow complete" },
];

function getStepIndex(status: MLProjectStatus): number {
  if (status === "archived") return -1;
  return WORKFLOW_STEPS.findIndex((step) => step.status === status);
}

function StatCard({
  icon,
  label,
  value,
  href,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  href?: string;
}) {
  const content = (
    <Card className="hover:border-emerald-500/50 transition-colors">
      <div className="flex items-center gap-4">
        <div className="p-3 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400">
          {icon}
        </div>
        <div>
          <p className="text-2xl font-bold text-stone-900 dark:text-stone-100">
            {value}
          </p>
          <p className="text-sm text-stone-500 dark:text-stone-400">{label}</p>
        </div>
      </div>
    </Card>
  );

  if (href) {
    return <Link href={href}>{content}</Link>;
  }
  return content;
}

function WorkflowProgress({ currentStatus }: { currentStatus: MLProjectStatus }) {
  const currentIndex = getStepIndex(currentStatus);

  if (currentStatus === "archived") {
    return (
      <Card className="p-6">
        <h3 className="text-lg font-semibold mb-4">Project Status</h3>
        <p className="text-stone-500 dark:text-stone-400">
          This project has been archived.
        </p>
      </Card>
    );
  }

  return (
    <Card className="p-6">
      <h3 className="text-lg font-semibold mb-6">Workflow Progress</h3>
      <div className="relative">
        {/* Progress line */}
        <div className="absolute top-4 left-4 right-4 h-0.5 bg-stone-200 dark:bg-stone-700" />
        <div
          className="absolute top-4 left-4 h-0.5 bg-emerald-500 transition-all duration-500"
          style={{
            width: `${Math.max(0, (currentIndex / (WORKFLOW_STEPS.length - 1)) * 100)}%`,
          }}
        />

        {/* Steps */}
        <div className="relative flex justify-between">
          {WORKFLOW_STEPS.map((step, index) => {
            const isCompleted = index < currentIndex;
            const isCurrent = index === currentIndex;
            const isPending = index > currentIndex;

            return (
              <div key={step.status} className="flex flex-col items-center">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center z-10 ${
                    isCompleted
                      ? "bg-emerald-500 text-white"
                      : isCurrent
                      ? "bg-emerald-500 text-white ring-4 ring-emerald-500/20"
                      : "bg-stone-200 dark:bg-stone-700 text-stone-400"
                  }`}
                >
                  {isCompleted ? (
                    <CheckCircle2 className="w-5 h-5" />
                  ) : (
                    <Circle className="w-5 h-5" />
                  )}
                </div>
                <span
                  className={`mt-2 text-xs font-medium ${
                    isCurrent
                      ? "text-emerald-600 dark:text-emerald-400"
                      : isPending
                      ? "text-stone-400"
                      : "text-stone-600 dark:text-stone-400"
                  }`}
                >
                  {step.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Current step description */}
      <div className="mt-6 p-4 bg-emerald-50 dark:bg-emerald-900/20 rounded-lg">
        <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400">
          Current: {WORKFLOW_STEPS[currentIndex]?.label}
        </p>
        <p className="text-sm text-emerald-600 dark:text-emerald-500 mt-1">
          {WORKFLOW_STEPS[currentIndex]?.description}
        </p>
      </div>
    </Card>
  );
}

function QuickActions({ project }: { project: MLProject }) {
  const router = useRouter();
  const currentIndex = getStepIndex(project.status);

  const actions = useMemo(() => {
    const result: { label: string; href: string; primary?: boolean }[] = [];

    // Add reference sounds first
    if (project.reference_sound_count === 0 || currentIndex <= 0) {
      result.push({
        label: "Add Reference Sounds",
        href: `/ml-projects/${project.uuid}/reference-sounds/`,
        primary: currentIndex === 0,
      });
    }

    // Create search session
    if (project.reference_sound_count && project.reference_sound_count > 0) {
      result.push({
        label: "Create Search Session",
        href: `/ml-projects/${project.uuid}/search/`,
        primary: currentIndex === 1 || currentIndex === 2,
      });
    }

    // Train model
    if (project.search_session_count && project.search_session_count > 0) {
      result.push({
        label: "Train Model",
        href: `/ml-projects/${project.uuid}/models/`,
        primary: currentIndex === 3,
      });
    }

    // Run inference
    if (project.custom_model_count && project.custom_model_count > 0) {
      result.push({
        label: "Run Inference",
        href: `/ml-projects/${project.uuid}/inference/`,
        primary: currentIndex === 4 || currentIndex === 5,
      });
    }

    return result;
  }, [project, currentIndex]);

  return (
    <Card className="p-6">
      <h3 className="text-lg font-semibold mb-4">Quick Actions</h3>
      <div className="space-y-2">
        {actions.map((action) => (
          <Link key={action.href} href={action.href} className="block">
            <Button
              variant={action.primary ? "primary" : "secondary"}
              className="w-full justify-between"
            >
              {action.label}
              <ArrowRight className="w-4 h-4" />
            </Button>
          </Link>
        ))}
        {actions.length === 0 && (
          <p className="text-sm text-stone-500 dark:text-stone-400">
            No actions available
          </p>
        )}
      </div>
    </Card>
  );
}

function ProjectDetails({ project }: { project: MLProject }) {
  return (
    <Card className="p-6">
      <h3 className="text-lg font-semibold mb-4">Project Details</h3>
      <div className="space-y-4">
        <div>
          <p className="text-sm text-stone-500 dark:text-stone-400">Description</p>
          <p className="text-stone-700 dark:text-stone-300 mt-1">
            {project.description || "No description provided"}
          </p>
        </div>

        {project.dataset && (
          <div className="flex items-center gap-2">
            <Database className="w-4 h-4 text-stone-400" />
            <span className="text-sm text-stone-500 dark:text-stone-400">Dataset:</span>
            <Link
              href={`/datasets/${project.dataset.uuid}/`}
              className="text-emerald-600 dark:text-emerald-400 hover:underline"
            >
              {project.dataset.name}
            </Link>
          </div>
        )}

        <div className="flex items-center gap-2">
          <Calendar className="w-4 h-4 text-stone-400" />
          <span className="text-sm text-stone-500 dark:text-stone-400">Created:</span>
          <span className="text-stone-700 dark:text-stone-300">
            {new Date(project.created_on).toLocaleDateString()}
          </span>
        </div>

        {project.target_tags && project.target_tags.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Tag className="w-4 h-4 text-stone-400" />
              <span className="text-sm text-stone-500 dark:text-stone-400">Target Tags:</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {project.target_tags.map((tag) => (
                <span
                  key={`${tag.key}:${tag.value}`}
                  className="px-2 py-1 text-xs bg-stone-100 dark:bg-stone-700 rounded-full"
                >
                  {tag.key}: {tag.value}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

export default function MLProjectOverviewPage() {
  const project = useContext(MLProjectContext);

  if (!project) {
    return null;
  }

  return (
    <div className="space-y-6">
      {/* Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard
          icon={<Music className="w-6 h-6" />}
          label="Reference Sounds"
          value={project.reference_sound_count ?? 0}
          href={`/ml-projects/${project.uuid}/reference-sounds/`}
        />
        <StatCard
          icon={<Search className="w-6 h-6" />}
          label="Search Sessions"
          value={project.search_session_count ?? 0}
          href={`/ml-projects/${project.uuid}/search/`}
        />
        <StatCard
          icon={<Cpu className="w-6 h-6" />}
          label="Custom Models"
          value={project.custom_model_count ?? 0}
          href={`/ml-projects/${project.uuid}/models/`}
        />
        {project.dataset && (
          <StatCard
            icon={<Database className="w-6 h-6" />}
            label="Dataset Recordings"
            value={project.dataset.recording_count}
            href={`/datasets/${project.dataset.uuid}/`}
          />
        )}
      </div>

      {/* Workflow Progress */}
      <WorkflowProgress currentStatus={project.status} />

      {/* Quick Actions and Details */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <QuickActions project={project} />
        <ProjectDetails project={project} />
      </div>
    </div>
  );
}
