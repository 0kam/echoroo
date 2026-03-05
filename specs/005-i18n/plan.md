# 005 - Internationalization (i18n) Plan

## Overview
Echoroo v2 internationalization: UI text (Paraglide-JS) + species vernacular names (GBIF).
Languages: English (en, base) / Japanese (ja).

## Current State

### UI i18n (Paraglide-JS)
- Paraglide-JS v2.13.1 configured (Vite plugin, server hooks, URL reroute)
- URL strategy: `/en/*`, `/ja/*` (both explicit prefixes)
- `messages/en.json` and `messages/ja.json`: **~140 keys populated with translations**
- 19 files use `m.*()` functions (256 call sites)
- `LanguageSwitcher.svelte`: **mounted in app layout, NOT in admin layout**
- `project.inlang/settings.json`: exists, baseLocale="en", locales=["en","ja"]

### Species Names
- DB schema supports multilingual vernacular names (`locale` column in `taxon_vernacular_names`)
- API has `locale` parameter (`/taxa/search?locale=ja`, `/detections/species-summary?locale=ja`)
- Frontend passes current UI locale to API
- GBIF service has Japanese name fetching code (`"ja": "jpn"` mapping)
- **BUT: Only English names seeded (BirdNET source). GBIF Japanese name fetch is NOT called anywhere.**

## Scope

### In Scope
- Complete remaining hardcoded UI text extraction
- GBIF Japanese vernacular name (和名) auto-population
- Date/number locale-aware formatting
- ICU plural syntax for count-dependent text
- Admin layout LanguageSwitcher
- Japanese translation audit

### Out of Scope
- Backend API error message localization (frontend maps error strings)
- Email template localization (future phase)
- Additional languages beyond en/ja

## Architecture

### UI Text Strategy
- **Frontend-only**: Backend returns English error messages; frontend localizes display
- **URL-based routing**: `/en/...`, `/ja/...` (configured)
- **Paraglide message functions**: `m.key_name()` from message files
- **Naming convention**: `{feature}_{element}_{type}()` (e.g., `auth_login_title()`)
- **Plurals**: ICU syntax `{count, plural, one{...} other{...}}`
- **Date/number formatting**: Pass locale from Paraglide to `toLocaleDateString(locale)`

### Species Name Strategy
- Vernacular names stored per locale in `taxon_vernacular_names` table
- API resolves names by locale with fallback: primary vernacular (locale) > tag.common_name > scientific name
- GBIF provides Japanese 和名 for most bird/anuran species
- Celery task to batch-fetch Japanese names from GBIF for all resolved taxa

## Remaining Work

### P1: Species Vernacular Names (和名) — Backend
**Critical for Japanese UX — species names are core content**
- Create Celery task to call `GBIFService.get_vernacular_names(taxon_key, locales=["ja"])` for resolved taxa
- Batch process: iterate all taxa with `gbif_taxon_key`, fetch and save Japanese vernacular names
- Schedule as one-time migration task + periodic sync for new taxa
- Verify species-summary API returns Japanese names when `locale=ja`

### P2: Admin LanguageSwitcher (~1 file)
- Mount `LanguageSwitcher` in `(admin)/+layout.svelte`

### P3: Hardcoded Form Component Text (~30-40 keys)
**Largest remaining gap in UI i18n**
- `SiteForm.svelte`: "Name is required", "Site is required", "Please select a location on the map"
- `DatasetForm.svelte`: validation messages, "Loading sites...", "Loading recorders..."
- `ConfirmDialog.svelte`: "Processing...", "The following will be deleted:"
- `FileUpload.svelte`: step labels in `getSessionStatusLabel()`
- `RecordingList.svelte`: "Loading recordings..."
- Members page: hardcoded role names "Viewer", "Member", "Admin"

### P4: Admin Section Text (~10-15 keys)
- `(admin)/+layout.svelte`: nav items ("Users", "Settings", "Licenses", "Recorders")
- Sidebar: "Echoroo Admin", "Logged in as", "Dashboard", "Logout"

### P5: Error/Toast Messages (~15-20 keys)
- "Failed to save site", generic error handlers
- Success notifications
- Pattern: `error_{action}()`, `success_{action}()` keys

### P6: Date/Number Formatting
- Add locale argument to `toLocaleDateString()` calls (~20 sites)
- Create utility: `formatDate(date, locale)` using Paraglide's `getLocale()`
- Handle English plural hardcodes: `${count} dataset${count > 1 ? 's' : ''}` → ICU syntax

### P7: Annotation Components (~10-15 keys)
- `AnnotationProjectForm.svelte`, `ReviewPanel.svelte` etc. (Svelte 4 syntax, no `m.*()`)
- Lower priority as these may be refactored to Svelte 5

### P8: Japanese Translation Audit
- Verify all keys in `en.json` have `ja.json` entries
- Review translation quality/consistency
- Inlang `missingTranslation` lint rule
- Verify GBIF Japanese names display correctly in species list

## Task Breakdown

| # | Task | Priority | Dependencies | SSA Type | Parallel? |
|---|------|----------|--------------|----------|-----------|
| 1 | GBIF Japanese vernacular name Celery task | P1 | None | backend-developer | Yes |
| 2 | Mount LanguageSwitcher in admin layout | P2 | None | frontend-developer | Yes |
| 3 | Extract form component hardcoded text | P3 | None | frontend-developer | Yes |
| 4 | Internationalize admin section text | P4 | None | frontend-developer | Yes (with 3) |
| 5 | Extract error/toast messages | P5 | None | frontend-developer | Yes (with 3,4) |
| 6 | Date/number formatting + ICU plurals | P6 | None | frontend-developer | Yes |
| 7 | Annotation components i18n | P7 | None | frontend-developer | Yes |
| 8 | Japanese translation audit | P8 | Tasks 1-7 | frontend-developer | No |
| 9 | Type check + browser verification | Final | All above | test-automator | No |

Tasks 1-7 are independent and can run in parallel.
Task 8 runs after all text changes are complete.
Task 9 is final verification.

## Key Decisions

1. **Message key naming**: `{feature}_{element}_{type}` (existing convention)
2. **Backend errors**: Frontend maps `detail` strings to i18n keys
3. **Plurals**: ICU `{count, plural, ...}` syntax (no hardcoded English plurals)
4. **Date formatting**: Utility function with Paraglide locale
5. **Species names**: GBIF as primary source for 和名, fallback chain: vernacular (locale) > tag.common_name > scientific name
6. **Fallback**: Paraglide auto-falls back to `en` for missing `ja` keys

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| GBIF rate limits during batch fetch | Medium | Throttle requests, use pagination, retry with backoff |
| GBIF missing 和名 for some species | Low | Fallback to English name; users can add via API |
| Large diff across many files | Low | Split by priority, each independently deployable |
| Annotation components use Svelte 4 syntax | Low | i18n separately, may be refactored later |
| `toLocaleDateString` inconsistency | Medium | Centralized utility ensures consistent locale passing |

## Definition of Done
- All user-facing text uses `m.*()` translation functions
- Both en.json and ja.json fully populated with all keys
- Japanese 和名 populated from GBIF for all resolved taxa
- Species list shows Japanese names when locale=ja
- Language switcher accessible from all pages (app + admin)
- Date/number formatting respects current locale
- No hardcoded English plurals
- `npm run check` passes
- Browser verification: switch en↔ja, all text + species names update correctly
- No console errors
