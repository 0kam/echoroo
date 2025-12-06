"use client";

import classNames from "classnames";
import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";
import type { KeyboardEvent } from "react";
import { Plus, MapPin, Edit2, Trash2 } from "lucide-react";
import toast from "react-hot-toast";
import Link from "next/link";

import { useMetadataSites } from "@/app/hooks/api/useMetadata";
import useDatasets from "@/app/hooks/api/useDatasets";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import SlideOver from "@/lib/components/ui/SlideOver";
import Spinner from "@/lib/components/ui/Spinner";
import VisibilityBadge from "@/lib/components/ui/VisibilityBadge";
import SiteForm from "@/lib/components/metadata/SiteForm";
import { DatasetIcon, RecordingsIcon, CalendarIcon } from "@/lib/components/icons";

import type { Dataset, Project, Site, SiteCreate, SiteUpdate } from "@/lib/types";
import { getSiteImageUrl } from "@/lib/utils/siteImages";

const H3SiteMap = dynamic(
  () => import("@/lib/components/maps/H3SiteMap").then((mod) => mod.default),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[360px] items-center justify-center rounded-lg border border-stone-200 bg-white dark:border-stone-700 dark:bg-stone-900">
        <Spinner />
      </div>
    ),
  }
);

interface ProjectSitesTabProps {
  project: Project;
  canEdit: boolean;
  isMember: boolean;
  isManager: boolean;
}

export default function ProjectSitesTab({
  project,
  isManager,
}: ProjectSitesTabProps) {
  const { query, create, update, remove } = useMetadataSites({ project_id: project.project_id });
  const { data: sites, isLoading } = query;
  const projectSites = useMemo(() => sites ?? [], [sites]);
  const [selectedSiteId, setSelectedSiteId] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  const selectedSite = useMemo(
    () => projectSites.find((site) => site.site_id === selectedSiteId) ?? null,
    [projectSites, selectedSiteId],
  );

  const handleSelectSite = useCallback(
    (siteId: string) => {
      const exists = projectSites.some((site) => site.site_id === siteId);
      if (!exists) {
        return;
      }
      setSelectedSiteId(siteId);
      setIsEditing(false);
    },
    [projectSites],
  );

  const closeDetail = useCallback(() => {
    setSelectedSiteId(null);
    setIsEditing(false);
  }, []);

  const handleCreateClick = useCallback(() => {
    setIsCreating(true);
  }, []);

  const handleCancelCreate = useCallback(() => {
    setIsCreating(false);
  }, []);

  const handleCreate = useCallback(
    async (data: SiteCreate | SiteUpdate) => {
      try {
        await create.mutateAsync(data as SiteCreate);
        toast.success("Site created successfully");
        setIsCreating(false);
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Failed to create site");
      }
    },
    [create],
  );

  const handleEdit = useCallback(() => {
    setIsEditing(true);
  }, []);

  const handleCancelEdit = useCallback(() => {
    setIsEditing(false);
  }, []);

  const handleUpdate = useCallback(
    async (data: SiteCreate | SiteUpdate) => {
      if (!selectedSite) return;
      try {
        await update.mutateAsync({ id: selectedSite.site_id, payload: data as SiteUpdate });
        toast.success("Site updated successfully");
        setIsEditing(false);
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Failed to update site");
      }
    },
    [selectedSite, update],
  );

  const handleDelete = useCallback(async () => {
    if (!selectedSite) return;
    if (!confirm(`Are you sure you want to delete site "${selectedSite.site_name}"?`)) return;

    try {
      await remove.mutateAsync(selectedSite.site_id);
      toast.success("Site deleted successfully");
      setSelectedSiteId(null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to delete site");
    }
  }, [selectedSite, remove]);

  const siteSummaries = useMemo(
    () =>
      projectSites.map((site) => ({
        site_id: site.site_id,
        site_name: site.site_name,
        h3_index: site.h3_index,
      })),
    [projectSites],
  );

  const canCreate = isManager;

  if (isLoading) {
    return <Loading />;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">Sites</h3>
          <p className="text-sm text-stone-600 dark:text-stone-400">
            Recording locations for this project
          </p>
          <p className="text-xs text-stone-500 dark:text-stone-500 mt-1">
            Note: All sites are publicly visible with H3 resolution for privacy
          </p>
        </div>
        {canCreate && (
          <Button
            variant="primary"
            padding="px-3 py-2"
            onClick={handleCreateClick}
          >
            <Plus className="w-4 h-4 mr-2" />
            New Site
          </Button>
        )}
      </div>

      {/* Map View */}
      <div className="space-y-3">
        <div>
          <h4 className="text-sm font-semibold text-stone-700 dark:text-stone-200">
            Site Map
          </h4>
          <p className="text-xs text-stone-500 dark:text-stone-400">
            Click a hexagon to focus a site and open its details.
          </p>
        </div>
        <H3SiteMap
          sites={siteSummaries}
          selectedSiteId={selectedSiteId ?? undefined}
          onSelect={handleSelectSite}
          height={360}
        />
      </div>

      {/* Site List */}
      {projectSites.length === 0 ? (
        <Empty>
          <MapPin className="w-16 h-16 text-stone-400 dark:text-stone-600 mb-4" />
          <p className="text-lg text-stone-600 dark:text-stone-400">
            No sites created yet
          </p>
          {canCreate && (
            <p className="text-sm text-stone-500 dark:text-stone-500 mt-2">
              Create your first site to mark recording locations
            </p>
          )}
        </Empty>
      ) : (
        <div>
          <h4 className="text-sm font-semibold mb-3 text-stone-700 dark:text-stone-300">
            All Sites ({projectSites.length})
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {projectSites.map((site: Site) => (
              <SiteCard
                key={site.site_id}
                site={site}
                isSelected={site.site_id === selectedSiteId}
                onSelect={handleSelectSite}
              />
            ))}
          </div>
        </div>
      )}

      {/* Create Site SlideOver */}
      <SlideOver
        isOpen={isCreating}
        onClose={handleCancelCreate}
        title="Create New Site"
      >
        <SiteForm
          projectId={project.project_id}
          onSubmit={handleCreate}
          onCancel={handleCancelCreate}
          isSubmitting={create.isPending}
        />
      </SlideOver>

      {/* Site Detail/Edit SlideOver */}
      <SiteDetailPanel
        site={selectedSite}
        project={project}
        isManager={isManager}
        isEditing={isEditing}
        onEdit={handleEdit}
        onCancelEdit={handleCancelEdit}
        onUpdate={handleUpdate}
        onDelete={handleDelete}
        onClose={closeDetail}
        isUpdating={update.isPending}
        isDeleting={remove.isPending}
      />
    </div>
  );
}

function SiteCard({
  site,
  isSelected,
  onSelect,
}: {
  site: Site;
  isSelected: boolean;
  onSelect: (siteId: string) => void;
}) {
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(site.site_id);
    }
  };

  return (
    <Card
      role="button"
      tabIndex={0}
      onClick={() => onSelect(site.site_id)}
      onKeyDown={handleKeyDown}
      aria-pressed={isSelected}
      className={classNames(
        "p-4 transition-shadow hover:shadow-md focus:outline-none focus:ring-2 focus:ring-emerald-500",
        isSelected
          ? "border-emerald-500 ring-1 ring-emerald-200 dark:border-emerald-400"
          : "",
      )}
    >
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="flex items-start gap-2 mb-2">
          <MapPin className="w-5 h-5 text-orange-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <h4 className="font-semibold text-sm line-clamp-1">
              {site.site_name}
            </h4>
            <p className="text-xs font-mono text-stone-500 dark:text-stone-400 line-clamp-1">
              {site.site_id}
            </p>
          </div>
        </div>

        {/* Location Info */}
        <div className="space-y-1 mb-2">
          {site.h3_index && (
            <div className="text-xs">
              <span className="text-stone-500 dark:text-stone-400">H3: </span>
              <span className="font-mono text-stone-700 dark:text-stone-300">
                {site.h3_index.slice(0, 12)}...
              </span>
            </div>
          )}
          {site.center_lat != null && site.center_lon != null && (
            <div className="text-xs text-stone-600 dark:text-stone-400">
              {site.center_lat.toFixed(4)}, {site.center_lon.toFixed(4)}
            </div>
          )}
        </div>

        {/* Metadata */}
        <div className="mt-auto grid grid-cols-2 gap-2 border-t border-stone-200 pt-2 text-xs dark:border-stone-700">
          <div>
            <span className="text-stone-500 dark:text-stone-400 block">
              Images
            </span>
            <span>{site.images.length}</span>
          </div>
          <div>
            <span className="text-stone-500 dark:text-stone-400 block">
              Created
            </span>
            <span>{site.created_on.toLocaleDateString()}</span>
          </div>
        </div>
      </div>
    </Card>
  );
}

/** Format date range for display */
function formatDateRange(startDate: Date | null | undefined, endDate: Date | null | undefined): string | null {
  if (!startDate && !endDate) return null;

  const formatDate = (date: Date) => date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric"
  });

  if (startDate && endDate) {
    // Check if same day
    if (startDate.toDateString() === endDate.toDateString()) {
      return formatDate(startDate);
    }
    return `${formatDate(startDate)} - ${formatDate(endDate)}`;
  }

  if (startDate) return `From ${formatDate(startDate)}`;
  if (endDate) return `Until ${formatDate(endDate)}`;
  return null;
}

/** Dataset card component displayed within the site detail panel */
function DatasetCard({
  dataset,
}: {
  dataset: Dataset;
}) {
  const dateRange = formatDateRange(dataset.recording_start_date, dataset.recording_end_date);

  return (
    <Link
      href={`/datasets/${dataset.uuid}/`}
      className="block rounded-lg border border-stone-200 bg-white p-3 hover:shadow-md hover:border-emerald-300 focus:outline-none focus:ring-2 focus:ring-emerald-500 dark:border-stone-700 dark:bg-stone-900 dark:hover:border-emerald-600 transition-all duration-200"
    >
      {/* Header Row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <DatasetIcon className="w-4 h-4 text-stone-500 flex-shrink-0" />
          <h5 className="text-sm font-semibold text-stone-900 dark:text-stone-100 truncate">
            {dataset.name}
          </h5>
        </div>
        <VisibilityBadge visibility={dataset.visibility} />
      </div>

      {/* Description */}
      {dataset.description && (
        <p className="text-sm text-stone-600 dark:text-stone-400 line-clamp-2 mt-1">
          {dataset.description}
        </p>
      )}

      {/* Metadata Row */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-xs text-stone-500 dark:text-stone-400">
        <div className="flex items-center gap-1">
          <RecordingsIcon className="w-4 h-4" />
          <span>{dataset.recording_count} recordings</span>
        </div>
        {dateRange && (
          <div className="flex items-center gap-1">
            <CalendarIcon className="w-4 h-4" />
            <span>{dateRange}</span>
          </div>
        )}
      </div>
    </Link>
  );
}

function SiteDetailPanel({
  site,
  project,
  isManager,
  isEditing,
  onEdit,
  onCancelEdit,
  onUpdate,
  onDelete,
  onClose,
  isUpdating,
  isDeleting,
}: {
  site: Site | null;
  project: Project;
  isManager: boolean;
  isEditing: boolean;
  onEdit: () => void;
  onCancelEdit: () => void;
  onUpdate: (data: SiteCreate | SiteUpdate) => void;
  onDelete: () => void;
  onClose: () => void;
  isUpdating: boolean;
  isDeleting: boolean;
}) {
  // Memoize filter to prevent infinite re-renders
  const datasetFilter = useMemo(
    () => (site ? { primary_site_id__eq: site.site_id } : {}),
    [site?.site_id]
  );

  // Fetch datasets associated with this site
  const {
    items: siteDatasets,
    isLoading: isDatasetsLoading,
    isError: isDatasetsError,
  } = useDatasets({
    filter: datasetFilter,
    pageSize: 100,
    enabled: Boolean(site),
  });

  const datasets = useMemo(() => siteDatasets ?? [], [siteDatasets]);

  if (!site) {
    return null;
  }

  return (
    <SlideOver
      isOpen={Boolean(site)}
      onClose={onClose}
      title={
        <div className="space-y-1">
          <p className="text-xs uppercase tracking-wide text-stone-500 dark:text-stone-400">
            Site Detail
          </p>
          <p className="text-lg font-semibold text-stone-900 dark:text-stone-100">
            {site.site_name}
          </p>
          <p className="font-mono text-xs text-stone-500 dark:text-stone-400">
            {site.site_id}
          </p>
        </div>
      }
    >
      {isEditing ? (
        <SiteForm
          site={site}
          projectId={project.project_id}
          onSubmit={onUpdate}
          onCancel={onCancelEdit}
          isSubmitting={isUpdating}
        />
      ) : (
        <div className="space-y-5 pb-10">
          <div>
            <p className="text-xs uppercase text-stone-500 dark:text-stone-400">
              Project
            </p>
            <p className="text-sm text-stone-900 dark:text-stone-100">
              {project.project_name}
              <span className="ml-2 font-mono text-xs text-stone-500 dark:text-stone-400">
                ({project.project_id})
              </span>
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-xs uppercase text-stone-500 dark:text-stone-400">
                H3 Index
              </p>
              <p className="font-mono break-all text-stone-900 dark:text-stone-100">
                {site.h3_index}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase text-stone-500 dark:text-stone-400">
                Created
              </p>
              <p>{site.created_on.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs uppercase text-stone-500 dark:text-stone-400">
                Latitude
              </p>
              <p>{site.center_lat != null ? site.center_lat.toFixed(6) : "---"}</p>
            </div>
            <div>
              <p className="text-xs uppercase text-stone-500 dark:text-stone-400">
                Longitude
              </p>
              <p>{site.center_lon != null ? site.center_lon.toFixed(6) : "---"}</p>
            </div>
          </div>
          <div>
            <p className="text-xs uppercase text-stone-500 dark:text-stone-400">
              Reference Images
            </p>
            {site.images.length === 0 ? (
              <p className="text-sm text-stone-500 dark:text-stone-400">
                No reference images uploaded for this site.
              </p>
            ) : (
              <div className="space-y-3">
                {site.images.map((image) => {
                  const imageUrl = getSiteImageUrl(image);
                  return (
                    <div
                      key={image.site_image_id}
                      className="flex items-center justify-between rounded-md border border-stone-200 bg-white p-2 text-xs dark:border-stone-700 dark:bg-stone-900"
                    >
                      <div className="flex min-w-0 flex-col">
                        <span className="font-semibold text-stone-700 dark:text-stone-200">
                          {image.site_image_id}
                        </span>
                        <span className="truncate font-mono text-stone-500 dark:text-stone-400">
                          {image.site_image_path}
                        </span>
                      </div>
                      {imageUrl ? (
                        <a
                          href={imageUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="ml-3 text-emerald-600 hover:underline dark:text-emerald-300"
                        >
                          Open
                        </a>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Associated Datasets Section */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs uppercase text-stone-500 dark:text-stone-400">
                Associated Datasets
              </p>
              {datasets.length > 0 && (
                <span className="inline-flex items-center rounded-full bg-stone-200 px-2 py-0.5 text-xs font-medium text-stone-700 dark:bg-stone-700 dark:text-stone-300">
                  {datasets.length}
                </span>
              )}
            </div>

            {isDatasetsLoading ? (
              <div className="flex justify-center py-8">
                <Spinner />
              </div>
            ) : isDatasetsError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-center dark:border-red-800 dark:bg-red-900/20">
                <p className="text-sm text-red-600 dark:text-red-400">
                  Failed to load datasets
                </p>
              </div>
            ) : datasets.length === 0 ? (
              <Empty>
                <DatasetIcon className="w-12 h-12 text-stone-400 dark:text-stone-600 mb-2" />
                <p className="text-sm text-stone-600 dark:text-stone-400">
                  No datasets at this site
                </p>
                <p className="text-xs text-stone-500 dark:text-stone-500 mt-1">
                  Datasets can be linked to this site when creating or editing them
                </p>
              </Empty>
            ) : (
              <div className="space-y-2">
                {datasets.map((dataset) => (
                  <DatasetCard
                    key={dataset.uuid}
                    dataset={dataset}
                  />
                ))}
              </div>
            )}
          </div>

          {isManager && (
            <div className="border-t border-stone-200 pt-4 dark:border-stone-700 space-y-2">
              <p className="text-xs uppercase text-stone-500 dark:text-stone-400 mb-2">
                Manage
              </p>
              <Button
                variant="primary"
                className="w-full justify-center"
                onClick={onEdit}
              >
                <Edit2 className="w-4 h-4 mr-2" />
                Edit Site
              </Button>
              <Button
                variant="danger"
                className="w-full justify-center"
                onClick={onDelete}
                disabled={isDeleting}
              >
                <Trash2 className="w-4 h-4 mr-2" />
                {isDeleting ? "Deleting..." : "Delete Site"}
              </Button>
            </div>
          )}
        </div>
      )}
    </SlideOver>
  );
}
