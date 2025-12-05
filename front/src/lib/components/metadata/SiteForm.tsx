"use client";

import { useCallback, useState } from "react";
import dynamic from "next/dynamic";
import { MapPin } from "lucide-react";

import { Group, Input } from "@/lib/components/inputs";
import Button from "@/lib/components/ui/Button";
import Spinner from "@/lib/components/ui/Spinner";

import type { Site, SiteCreate, SiteUpdate } from "@/lib/types";

const H3HexPicker = dynamic(() => import("@/lib/components/maps/H3HexPicker"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[400px] items-center justify-center rounded-lg border border-stone-200 bg-white dark:border-stone-700 dark:bg-stone-900">
      <Spinner />
    </div>
  ),
});

interface SiteFormProps {
  site?: Site;
  projectId: string;
  onSubmit: (data: SiteCreate | SiteUpdate) => void | Promise<void>;
  onCancel: () => void;
  isSubmitting?: boolean;
}

export default function SiteForm({
  site,
  projectId,
  onSubmit,
  onCancel,
  isSubmitting = false,
}: SiteFormProps) {
  const isEditing = Boolean(site);

  const [siteId, setSiteId] = useState(site?.site_id ?? "");
  const [siteName, setSiteName] = useState(site?.site_name ?? "");
  const [h3Index, setH3Index] = useState(site?.h3_index ?? "");

  const [resolution, setResolution] = useState(7);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      if (site) {
        const updateData: SiteUpdate = {};
        if (siteName !== site.site_name) updateData.site_name = siteName;
        if (h3Index !== site.h3_index) updateData.h3_index = h3Index;

        await onSubmit(updateData);
      } else {
        const createData: SiteCreate = {
          site_id: siteId,
          site_name: siteName,
          project_id: projectId,
          h3_index: h3Index,
          images: [],
        };
        await onSubmit(createData);
      }
    },
    [isEditing, site, siteId, siteName, projectId, h3Index, onSubmit],
  );

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {!isEditing && (
        <Group label="Site ID" name="site_id" help="Unique identifier for this site">
          <Input
            value={siteId}
            onChange={(e) => setSiteId(e.target.value)}
            placeholder="e.g., SITE001"
            required
          />
        </Group>
      )}

      <Group label="Site Name" name="site_name">
        <Input
          value={siteName}
          onChange={(e) => setSiteName(e.target.value)}
          placeholder="e.g., Forest Clearing North"
          required
        />
      </Group>

      <Group
        label="Location (H3 Index)"
        name="h3_index"
        help="Click on the map to select a location. The H3 index provides privacy by using hexagonal grids."
      >
        <div className="space-y-2">
          <Input
            value={h3Index}
            onChange={(e) => setH3Index(e.target.value)}
            placeholder="Click on map or paste H3 index"
            required
          />
          <H3HexPicker
            value={h3Index}
            onChange={setH3Index}
            resolution={resolution}
            onResolutionChange={setResolution}
          />
        </div>
      </Group>

      <div className="flex justify-end gap-2 pt-4 border-t border-stone-200 dark:border-stone-700">
        <Button
          type="button"
          variant="secondary"
          onClick={onCancel}
          disabled={isSubmitting}
        >
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          disabled={isSubmitting || !siteId || !siteName || !h3Index}
        >
          {isSubmitting ? (
            <>
              <Spinner className="w-4 h-4 mr-2" />
              {isEditing ? "Updating..." : "Creating..."}
            </>
          ) : (
            <>
              <MapPin className="w-4 h-4 mr-2" />
              {isEditing ? "Update Site" : "Create Site"}
            </>
          )}
        </Button>
      </div>
    </form>
  );
}
