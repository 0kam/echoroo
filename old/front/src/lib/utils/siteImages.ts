import { HOST } from "@/lib/api/common";
import type { SiteImage } from "@/lib/types";

function isAbsoluteUrl(path: string) {
  return /^https?:\/\//i.test(path);
}

export function getSiteImageUrl(
  image: Pick<SiteImage, "site_image_id" | "site_image_path">,
): string | null {
  if (!image.site_image_path) {
    return null;
  }

  if (isAbsoluteUrl(image.site_image_path)) {
    return image.site_image_path;
  }

  const trimmedHost = HOST?.replace(/\/$/, "") ?? "";
  const base = trimmedHost || "";
  const route = `/api/v1/metadata/site_images/${encodeURIComponent(image.site_image_id)}/download`;
  return base ? `${base}${route}` : route;
}
