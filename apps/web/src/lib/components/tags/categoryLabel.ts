/**
 * Localized display label for a tag category.
 *
 * Shared by the tag form, list, and statistics components. Kept local to the
 * tags component directory (not a global util) since it is specific to this
 * feature surface.
 */
import * as m from '$lib/paraglide/messages';

export function getCategoryLabel(category: string): string {
  switch (category) {
    case 'species':
      return m.annotation_tag_category_species();
    case 'sound_type':
      return m.annotation_tag_category_sound_type();
    case 'quality':
      return m.annotation_tag_category_quality();
    default:
      return category;
  }
}
