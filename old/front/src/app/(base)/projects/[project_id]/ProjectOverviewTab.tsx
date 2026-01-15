import { Globe, Lock, Mail, User, ExternalLink } from "lucide-react";

import type { Project } from "@/lib/types";

interface ProjectOverviewTabProps {
  project: Project;
  canEdit: boolean;
  isMember: boolean;
  isManager: boolean;
}

export default function ProjectOverviewTab({
  project,
}: ProjectOverviewTabProps) {
  return (
    <div className="space-y-6">
      {/* Description */}
      {project.description && (
        <div>
          <h3 className="text-lg font-semibold mb-2">Description</h3>
          <p className="text-stone-700 dark:text-stone-300 whitespace-pre-wrap">
            {project.description}
          </p>
        </div>
      )}

      {/* Project Details */}
      <div>
        <h3 className="text-lg font-semibold mb-3">Project Details</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Project ID */}
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-lg bg-stone-100 dark:bg-stone-800 flex items-center justify-center flex-shrink-0">
              <span className="text-lg font-bold text-stone-600 dark:text-stone-400">
                ID
              </span>
            </div>
            <div>
              <p className="text-sm text-stone-600 dark:text-stone-400">
                Project ID
              </p>
              <p className="font-mono text-sm">{project.project_id}</p>
            </div>
          </div>

          {/* Created Date */}
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-lg bg-stone-100 dark:bg-stone-800 flex items-center justify-center flex-shrink-0">
              <span className="text-lg">📅</span>
            </div>
            <div>
              <p className="text-sm text-stone-600 dark:text-stone-400">
                Created On
              </p>
              <p className="text-sm">
                {new Date(project.created_on).toLocaleString()}
              </p>
            </div>
          </div>

          {/* Status */}
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-lg bg-stone-100 dark:bg-stone-800 flex items-center justify-center flex-shrink-0">
              {project.is_active ? (
                <Globe className="w-5 h-5 text-emerald-500" />
              ) : (
                <Lock className="w-5 h-5 text-stone-400" />
              )}
            </div>
            <div>
              <p className="text-sm text-stone-600 dark:text-stone-400">
                Status
              </p>
              <p className="text-sm">
                {project.is_active ? "Active" : "Inactive"}
              </p>
            </div>
          </div>

          {/* Target Taxa */}
          {project.target_taxa && (
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-lg bg-stone-100 dark:bg-stone-800 flex items-center justify-center flex-shrink-0">
                <span className="text-lg">🦇</span>
              </div>
              <div>
                <p className="text-sm text-stone-600 dark:text-stone-400">
                  Target Taxa
                </p>
                <p className="text-sm">{project.target_taxa}</p>
              </div>
            </div>
          )}

          {/* Project URL */}
          {project.url && (
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-lg bg-stone-100 dark:bg-stone-800 flex items-center justify-center flex-shrink-0">
                <ExternalLink className="w-5 h-5 text-blue-500" />
              </div>
              <div>
                <p className="text-sm text-stone-600 dark:text-stone-400">
                  Project URL
                </p>
                <a
                  href={project.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
                >
                  {project.url}
                </a>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Admin Contact */}
      {(project.admin_name || project.admin_email) && (
        <div>
          <h3 className="text-lg font-semibold mb-3">Administrator Contact</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {project.admin_name && (
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-lg bg-stone-100 dark:bg-stone-800 flex items-center justify-center flex-shrink-0">
                  <User className="w-5 h-5 text-stone-600 dark:text-stone-400" />
                </div>
                <div>
                  <p className="text-sm text-stone-600 dark:text-stone-400">
                    Name
                  </p>
                  <p className="text-sm">{project.admin_name}</p>
                </div>
              </div>
            )}

            {project.admin_email && (
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-lg bg-stone-100 dark:bg-stone-800 flex items-center justify-center flex-shrink-0">
                  <Mail className="w-5 h-5 text-stone-600 dark:text-stone-400" />
                </div>
                <div>
                  <p className="text-sm text-stone-600 dark:text-stone-400">
                    Email
                  </p>
                  <a
                    href={`mailto:${project.admin_email}`}
                    className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
                  >
                    {project.admin_email}
                  </a>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
