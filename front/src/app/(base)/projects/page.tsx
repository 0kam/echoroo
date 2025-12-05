"use client";

import { useCallback, useMemo, useState } from "react";
import { Search, Plus, FolderOpen } from "lucide-react";

import { useMetadataProjects } from "@/app/hooks/api/useMetadata";
import useActiveUser from "@/app/hooks/api/useActiveUser";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import { Input } from "@/lib/components/inputs";
import Link from "@/lib/components/ui/Link";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";

import { canCreateProject } from "@/lib/utils/permissions";

import type { Project } from "@/lib/types";

export default function ProjectsPage() {
  const { data: activeUser } = useActiveUser();
  const [searchQuery, setSearchQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<boolean | undefined>(true);

  const { query } = useMetadataProjects({
    search: searchQuery,
    is_active: activeFilter,
  });

  const { data: projects, isLoading, error } = query;

  const canCreate = useMemo(
    () => canCreateProject(activeUser),
    [activeUser]
  );

  const filteredProjects = useMemo(() => {
    if (!projects) return [];
    return projects;
  }, [projects]);

  const handleSearch = useCallback((value: string) => {
    setSearchQuery(value);
  }, []);

  if (error) {
    return (
      <div className="container mx-auto p-8">
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-6">
          <h2 className="text-xl font-bold text-red-700 dark:text-red-400 mb-2">
            Error Loading Projects
          </h2>
          <p className="text-red-600 dark:text-red-300">
            {error instanceof Error ? error.message : "Unknown error occurred"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-4xl font-bold mb-2">Projects</h1>
          <p className="text-stone-600 dark:text-stone-400">
            Browse and manage research projects
          </p>
        </div>
        {/* Project creation is currently only available through the backend API */}
      </div>

      {/* Filters */}
      <Card className="p-6 mb-6">
        <div className="flex flex-col md:flex-row gap-4">
          <div className="flex-1">
            <Input
              type="text"
              placeholder="Search projects by name, ID, or description..."
              value={searchQuery}
              onChange={(e) => handleSearch(e.target.value)}
            />
          </div>
          <div className="flex gap-2">
            <Button
              variant={activeFilter === undefined ? "primary" : "secondary"}
              onClick={() => setActiveFilter(undefined)}
            >
              All
            </Button>
            <Button
              variant={activeFilter === true ? "primary" : "secondary"}
              onClick={() => setActiveFilter(true)}
            >
              Active
            </Button>
            <Button
              variant={activeFilter === false ? "primary" : "secondary"}
              onClick={() => setActiveFilter(false)}
            >
              Inactive
            </Button>
          </div>
        </div>
      </Card>

      {/* Project List */}
      {isLoading ? (
        <Loading />
      ) : filteredProjects.length === 0 ? (
        <Empty>
          <FolderOpen className="w-16 h-16 text-stone-400 dark:text-stone-600 mb-4" />
          <p className="text-lg text-stone-600 dark:text-stone-400">
            {searchQuery
              ? "No projects found matching your search"
              : "No projects available"}
          </p>
        </Empty>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredProjects.map((project: Project) => (
            <ProjectCard key={project.project_id} project={project} />
          ))}
        </div>
      )}
    </div>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const memberCount = project.memberships?.length ?? 0;
  const managerCount =
    project.memberships?.filter((m) => m.role === "manager").length ?? 0;

  return (
    <Link href={`/projects/${project.project_id}`}>
      <Card className="p-6 h-full hover:shadow-lg transition-shadow cursor-pointer">
        <div className="flex flex-col h-full">
          {/* Header */}
          <div className="flex items-start justify-between mb-3">
            <h3 className="text-xl font-bold flex-1">
              {project.project_name}
            </h3>
            {!project.is_active && (
              <span className="px-2 py-1 text-xs bg-stone-200 dark:bg-stone-700 rounded-md">
                Inactive
              </span>
            )}
          </div>

          {/* ID */}
          <p className="text-sm text-stone-500 dark:text-stone-400 mb-3 font-mono">
            ID: {project.project_id}
          </p>

          {/* Description */}
          {project.description && (
            <p className="text-sm text-stone-600 dark:text-stone-300 mb-4 line-clamp-3 flex-1">
              {project.description}
            </p>
          )}

          {/* Target Taxa */}
          {project.target_taxa && (
            <div className="mb-4">
              <span className="px-2 py-1 text-xs bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 rounded-md">
                {project.target_taxa}
              </span>
            </div>
          )}

          {/* Footer */}
          <div className="flex items-center justify-between text-sm text-stone-500 dark:text-stone-400 pt-4 border-t border-stone-200 dark:border-stone-700">
            <div className="flex gap-4">
              <span title="Total members">
                {memberCount} member{memberCount !== 1 ? "s" : ""}
              </span>
              <span title="Managers">
                {managerCount} manager{managerCount !== 1 ? "s" : ""}
              </span>
            </div>
            <span className="text-xs">
              {new Date(project.created_on).toLocaleDateString()}
            </span>
          </div>
        </div>
      </Card>
    </Link>
  );
}
