"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  Info,
  Database,
  MapPin,
  Users,
  Settings,
  Globe,
  Lock,
  Calendar,
} from "lucide-react";

import { useProject } from "@/app/hooks/api/useMetadata";
import useActiveUser from "@/app/hooks/api/useActiveUser";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Link from "@/lib/components/ui/Link";
import Tab from "@/lib/components/ui/Tab";
import Loading from "@/lib/components/ui/Loading";

import {
  canEditProject,
  isProjectManager,
  isProjectMember,
} from "@/lib/utils/permissions";

import ProjectOverviewTab from "./ProjectOverviewTab";
import ProjectDatasetsTab from "./ProjectDatasetsTab";
import ProjectSitesTab from "./ProjectSitesTab";
import ProjectMembersTab from "./ProjectMembersTab";

type TabId = "overview" | "datasets" | "sites" | "members";

export default function ProjectDetailPage() {
  const params = useParams();
  const projectId = params?.project_id as string;
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  const { data: activeUser } = useActiveUser();
  const { query } = useProject(projectId);
  const { data: project, isLoading, error } = query;

  const canEdit = useMemo(
    () => canEditProject(activeUser, project),
    [activeUser, project]
  );

  const isMember = useMemo(
    () => isProjectMember(activeUser, project),
    [activeUser, project]
  );

  const isManager = useMemo(
    () => isProjectManager(activeUser, project),
    [activeUser, project]
  );

  if (error) {
    return (
      <div className="container mx-auto p-8">
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-6">
          <h2 className="text-xl font-bold text-red-700 dark:text-red-400 mb-2">
            Error Loading Project
          </h2>
          <p className="text-red-600 dark:text-red-300">
            {error instanceof Error ? error.message : "Unknown error occurred"}
          </p>
          <Link href="/projects/" className="mt-4 inline-block">
            <Button mode="text">Back to Projects</Button>
          </Link>
        </div>
      </div>
    );
  }

  if (isLoading || !project) {
    return <Loading />;
  }

  return (
    <div className="container mx-auto p-8">
      {/* Breadcrumbs */}
      <nav className="mb-6 text-sm text-stone-600 dark:text-stone-400">
        <Link href="/" className="hover:underline">
          Home
        </Link>
        {" / "}
        <Link href="/projects/" className="hover:underline">
          Projects
        </Link>
        {" / "}
        <span className="text-stone-900 dark:text-stone-100">
          {project.project_name}
        </span>
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-2">
            <h1 className="text-4xl font-bold">{project.project_name}</h1>
            {!project.is_active && (
              <span className="px-3 py-1 text-sm bg-stone-200 dark:bg-stone-700 rounded-md">
                Inactive
              </span>
            )}
          </div>
          <p className="text-sm text-stone-500 dark:text-stone-400 font-mono mb-2">
            ID: {project.project_id}
          </p>
          {project.target_taxa && (
            <div className="flex items-center gap-2">
              <span className="px-2 py-1 text-sm bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 rounded-md">
                {project.target_taxa}
              </span>
            </div>
          )}
        </div>
        {canEdit && (
          <Link href={`/projects/${projectId}/settings/general`}>
            <Button variant="primary">
              <Settings className="inline-block w-4 h-4 mr-2" />
              Settings
            </Button>
          </Link>
        )}
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <Card className="p-4">
          <div className="flex items-center gap-3">
            <Users className="w-8 h-8 text-emerald-500" />
            <div>
              <p className="text-2xl font-bold">
                {project.memberships?.length ?? 0}
              </p>
              <p className="text-sm text-stone-600 dark:text-stone-400">
                Members
              </p>
            </div>
          </div>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-3">
            <Database className="w-8 h-8 text-blue-500" />
            <div>
              <p className="text-2xl font-bold">-</p>
              <p className="text-sm text-stone-600 dark:text-stone-400">
                Datasets
              </p>
            </div>
          </div>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-3">
            <MapPin className="w-8 h-8 text-orange-500" />
            <div>
              <p className="text-2xl font-bold">-</p>
              <p className="text-sm text-stone-600 dark:text-stone-400">
                Sites
              </p>
            </div>
          </div>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-3">
            <Calendar className="w-8 h-8 text-purple-500" />
            <div>
              <p className="text-sm font-semibold">Created</p>
              <p className="text-sm text-stone-600 dark:text-stone-400">
                {new Date(project.created_on).toLocaleDateString()}
              </p>
            </div>
          </div>
        </Card>
      </div>

      {/* Tabs */}
      <Card className="p-6">
        <div className="flex gap-2 mb-6 border-b border-stone-200 dark:border-stone-700 pb-2">
          <Tab
            active={activeTab === "overview"}
            onClick={() => setActiveTab("overview")}
          >
            <Info className="w-4 h-4" />
            Overview
          </Tab>
          <Tab
            active={activeTab === "datasets"}
            onClick={() => setActiveTab("datasets")}
          >
            <Database className="w-4 h-4" />
            Datasets
          </Tab>
          <Tab
            active={activeTab === "sites"}
            onClick={() => setActiveTab("sites")}
          >
            <MapPin className="w-4 h-4" />
            Sites
          </Tab>
          <Tab
            active={activeTab === "members"}
            onClick={() => setActiveTab("members")}
          >
            <Users className="w-4 h-4" />
            Members
          </Tab>
        </div>

        {/* Tab Content */}
        <div className="min-h-[400px]">
          {activeTab === "overview" && (
            <ProjectOverviewTab
              project={project}
              canEdit={canEdit}
              isMember={isMember}
              isManager={isManager}
            />
          )}
          {activeTab === "datasets" && (
            <ProjectDatasetsTab
              project={project}
              canEdit={canEdit}
              isMember={isMember}
              isManager={isManager}
            />
          )}
          {activeTab === "sites" && (
            <ProjectSitesTab
              project={project}
              canEdit={canEdit}
              isMember={isMember}
              isManager={isManager}
            />
          )}
          {activeTab === "members" && (
            <ProjectMembersTab
              project={project}
              canEdit={canEdit}
              isMember={isMember}
              isManager={isManager}
            />
          )}
        </div>
      </Card>
    </div>
  );
}
