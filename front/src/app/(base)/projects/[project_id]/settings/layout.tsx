"use client";

import classnames from "classnames";
import { usePathname, useParams, useRouter } from "next/navigation";
import { useContext, useEffect, useMemo } from "react";
import type { ReactNode } from "react";

import { useProject } from "@/app/hooks/api/useMetadata";
import useActiveUser from "@/app/hooks/api/useActiveUser";

import Header from "@/lib/components/ui/Header";
import { H1 } from "@/lib/components/ui/Headings";
import Link from "@/lib/components/ui/Link";
import Loading from "@/lib/components/ui/Loading";

import { canEditProject } from "@/lib/utils/permissions";

type NavItem = {
  href: string;
  label: string;
};

export default function ProjectSettingsLayout({
  children,
}: {
  children: ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const params = useParams();
  const projectId = params?.project_id as string;

  const { data: activeUser } = useActiveUser();
  const { query } = useProject(projectId);
  const { data: project, isLoading } = query;

  const canManage = useMemo(
    () => canEditProject(activeUser, project),
    [activeUser, project]
  );

  useEffect(() => {
    if (!isLoading && project && !canManage) {
      router.replace(`/projects/${projectId}`);
    }
  }, [isLoading, project, canManage, router, projectId]);

  const navItems = useMemo<NavItem[]>(() => [
    { href: `/projects/${projectId}/settings/general`, label: "General" },
  ], [projectId]);

  if (isLoading || !project) {
    return <Loading />;
  }

  if (!canManage) {
    return (
      <div className="flex flex-col items-center justify-center py-12 px-4">
        <p className="text-center text-stone-500 dark:text-stone-400">
          You need project manager privileges to access this page.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 pb-12">
      <Header>
        <div className="flex flex-col gap-4">
          <div>
            <nav className="mb-2 text-sm text-stone-600 dark:text-stone-400">
              <Link href="/projects/" className="hover:underline">
                Projects
              </Link>
              {" / "}
              <Link href={`/projects/${projectId}`} className="hover:underline">
                {project.project_name}
              </Link>
              {" / "}
              <span className="text-stone-900 dark:text-stone-100">
                Settings
              </span>
            </nav>
            <H1>{project.project_name} Settings</H1>
            <p className="mt-1 text-sm text-stone-600 dark:text-stone-300">
              Manage project details, members, sites, and datasets.
            </p>
          </div>
          <nav className="flex flex-wrap gap-2">
            {navItems.map((item) => {
              const isActive = pathname?.startsWith(item.href);

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  mode="text"
                  variant={isActive ? "primary" : "secondary"}
                  padding="px-3 py-2"
                  className={classnames(
                    "text-sm font-semibold transition-colors",
                    isActive
                      ? "border border-emerald-500 bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200"
                      : "border border-transparent text-stone-600 dark:text-stone-300 hover:border-stone-300 dark:hover:border-stone-700",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </Header>
      <div className="px-2 sm:px-3 lg:px-6 space-y-4">
        {children}
      </div>
    </div>
  );
}
