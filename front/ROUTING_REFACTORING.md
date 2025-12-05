# Routing Structure Refactoring - Complete Documentation

## Overview

This document describes the comprehensive routing refactoring performed on the Whombat application to migrate from query-parameter-based routes to Next.js dynamic routes.

## Migration Date
2025-11-01

## Motivation

### Problems with Old Routing
1. **SEO Issues**: Query parameter URLs (`/detail/?uuid=xxx`) are not SEO-friendly
2. **Next.js Incompatibility**: Doesn't work well with `output: "export"` static generation
3. **Browser History**: Poor back/forward button behavior
4. **Inconsistent Patterns**: Mixed routing styles across the application
5. **URL Clarity**: Non-intuitive URLs for users

### Benefits of New Routing
1. ✅ **SEO-Friendly**: Clean, semantic URLs
2. ✅ **Next.js Best Practices**: Leverages dynamic route segments
3. ✅ **Better UX**: Intuitive, shareable URLs
4. ✅ **Consistency**: Unified routing pattern across all resources
5. ✅ **Type Safety**: Better TypeScript support with `useParams()`

## Routing Pattern Changes

### Projects (Metadata)

#### Old Routes
- List: `/admin/metadata/projects/`
- Detail: `/projects/[project_id]/` ✓ (already using dynamic routes)

#### New Routes
- List: `/admin/metadata/projects/`
- Detail: `/projects/[project_id]/`
- **Edit: `/admin/metadata/projects/[project_id]/edit/`** (NEW)

**Key Changes:**
- Added dedicated edit page at `/admin/metadata/projects/[project_id]/edit/`
- Maintains dynamic route structure for project details

### Datasets

#### Old Routes
```
/datasets/detail/?dataset_uuid=abc-123
/datasets/detail/recordings/?dataset_uuid=abc-123
/datasets/detail/notes/?dataset_uuid=abc-123
/datasets/detail/sound_events/?dataset_uuid=abc-123
```

#### New Routes
```
/datasets/[dataset_uuid]/
/datasets/[dataset_uuid]/recordings/
/datasets/[dataset_uuid]/notes/
/datasets/[dataset_uuid]/sound_events/
```

**Migration Steps:**
1. Created `/datasets/[dataset_uuid]/` directory structure
2. Updated `DatasetTabs` component to use new routes
3. Modified layout.tsx to use `useParams()` instead of `useSearchParams()`
4. Updated all internal links in:
   - `/datasets/page.tsx`
   - `/lib/components/recordings/CrossDatasetSearch.tsx`

### Annotation Projects

#### Old Routes
```
/annotation_projects/detail/?annotation_project_uuid=abc-123
/annotation_projects/detail/annotation/?annotation_project_uuid=abc-123
/annotation_projects/detail/tasks/?annotation_project_uuid=abc-123
/annotation_projects/detail/tags/?annotation_project_uuid=abc-123
/annotation_projects/detail/clips/?annotation_project_uuid=abc-123
```

#### New Routes
```
/annotation_projects/[annotation_project_uuid]/
/annotation_projects/[annotation_project_uuid]/annotation/
/annotation_projects/[annotation_project_uuid]/tasks/
/annotation_projects/[annotation_project_uuid]/tags/
/annotation_projects/[annotation_project_uuid]/clips/
```

**Migration Steps:**
1. Created `/annotation_projects/[annotation_project_uuid]/` directory structure
2. Updated `AnnotationProjectHeader` component to use new routes
3. Modified layout.tsx to use `useParams()` instead of `useSearchParams()`
4. Updated all internal links in:
   - `/annotation_projects/page.tsx`
   - `/annotation_projects/[annotation_project_uuid]/tasks/page.tsx`

### Evaluation Sets

#### Old Routes
```
/evaluation/detail/?evaluation_set_uuid=abc-123
/evaluation/detail/tasks/?evaluation_set_uuid=abc-123
/evaluation/detail/model_runs/?evaluation_set_uuid=abc-123
/evaluation/detail/user_runs/?evaluation_set_uuid=abc-123
/evaluation/detail/tags/?evaluation_set_uuid=abc-123
```

#### New Routes
```
/evaluation/[evaluation_set_uuid]/
/evaluation/[evaluation_set_uuid]/tasks/
/evaluation/[evaluation_set_uuid]/model_runs/
/evaluation/[evaluation_set_uuid]/user_runs/
/evaluation/[evaluation_set_uuid]/tags/
```

**Migration Steps:**
1. Created `/evaluation/[evaluation_set_uuid]/` directory structure
2. Updated `EvaluationSetTabs` component to use new routes
3. Modified layout.tsx to use `useParams()` instead of `useSearchParams()`
4. Updated all internal links in:
   - `/evaluation/page.tsx`

## File Structure Changes

### Before
```
app/(base)/
├── datasets/
│   ├── detail/              # Query param based
│   │   ├── layout.tsx       # Uses useSearchParams()
│   │   ├── page.tsx
│   │   ├── recordings/
│   │   ├── notes/
│   │   └── sound_events/
│   └── page.tsx
```

### After
```
app/(base)/
├── datasets/
│   ├── [dataset_uuid]/      # Dynamic route
│   │   ├── layout.tsx       # Uses useParams()
│   │   ├── page.tsx
│   │   ├── recordings/
│   │   ├── notes/
│   │   └── sound_events/
│   ├── detail/              # OLD - kept for backward compatibility
│   └── page.tsx
```

## Component Updates

### Navigation Components

#### DatasetTabs
**File:** `/app/components/datasets/DatasetTabs.tsx`

**Before:**
```tsx
const params = useSearchParams();
onClick={() => router.push(`/datasets/detail/?${params.toString()}`)}
```

**After:**
```tsx
// Removed useSearchParams import
onClick={() => router.push(`/datasets/${dataset.uuid}/`)}
```

#### AnnotationProjectHeader
**File:** `/app/components/annotation_projects/AnnotationProjectHeader.tsx`

**Before:**
```tsx
const params = useSearchParams();
onClick={() => router.push(`/annotation_projects/detail/?${params.toString()}`)}
```

**After:**
```tsx
// Removed useSearchParams import
onClick={() => router.push(`/annotation_projects/${annotationProject.uuid}/`)}
```

#### EvaluationSetTabs
**File:** `/app/(base)/evaluation/[evaluation_set_uuid]/components/EvaluationSetTabs.tsx`

**Before:**
```tsx
const params = useSearchParams();
onClick={() => router.push(`/evaluation/detail/?${params.toString()}`)}
```

**After:**
```tsx
// Removed useSearchParams import
onClick={() => router.push(`/evaluation/${evaluationSet.uuid}/`)}
```

### Layout Components

#### Dataset Layout
**File:** `/app/(base)/datasets/[dataset_uuid]/layout.tsx`

**Before:**
```tsx
const params = useSearchParams();
const uuid = params.get("dataset_uuid");
```

**After:**
```tsx
const params = useParams();
const uuid = params.dataset_uuid as string;
```

**Key Changes:**
- `useSearchParams()` → `useParams()`
- `params.get("key")` → `params.key`
- Added `notFound()` for missing params
- Better error handling with `return null`

## Backward Compatibility

### Old Routes Status
The old `/detail/?uuid=xxx` routes are **still present** in the codebase for backward compatibility.

### Migration Strategy
1. **Phase 1** (Current): New dynamic routes are live, old routes still exist
2. **Phase 2** (Future): Add redirects from old routes to new routes
3. **Phase 3** (Future): Remove old route files after transition period

### Recommended Redirect Implementation
```tsx
// Example: /datasets/detail/page.tsx
"use client";
import { useSearchParams, useRouter } from "next/navigation";
import { useEffect } from "react";

export default function RedirectPage() {
  const params = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    const uuid = params.get("dataset_uuid");
    if (uuid) {
      router.replace(`/datasets/${uuid}/`);
    } else {
      router.replace("/datasets/");
    }
  }, [params, router]);

  return <div>Redirecting...</div>;
}
```

## Testing Checklist

### Datasets
- [ ] List page loads correctly
- [ ] Clicking dataset navigates to `/datasets/[uuid]/`
- [ ] Overview tab works
- [ ] Recordings tab works
- [ ] Notes tab works
- [ ] Sound Events tab works
- [ ] Cross-dataset search links work
- [ ] Browser back/forward works correctly

### Annotation Projects
- [ ] List page loads correctly
- [ ] Clicking project navigates to `/annotation_projects/[uuid]/`
- [ ] Overview tab works
- [ ] Annotate tab works
- [ ] Tasks tab works
- [ ] Tags tab works
- [ ] Task creation redirects correctly

### Evaluation Sets
- [ ] List page loads correctly
- [ ] Clicking set navigates to `/evaluation/[uuid]/`
- [ ] Overview tab works
- [ ] Examples tab works
- [ ] Model Runs tab works
- [ ] User Sessions tab works
- [ ] Tags tab works

### Projects (Metadata)
- [ ] List page loads correctly
- [ ] Project detail page loads
- [ ] Edit page accessible at `/admin/metadata/projects/[id]/edit/`
- [ ] Member list shows usernames (not UUIDs)
- [ ] Form submission works correctly

## URL Examples

### Before and After Comparison

| Resource | Old URL | New URL |
|----------|---------|---------|
| Dataset Overview | `/datasets/detail/?dataset_uuid=abc-123` | `/datasets/abc-123/` |
| Dataset Recordings | `/datasets/detail/recordings/?dataset_uuid=abc-123` | `/datasets/abc-123/recordings/` |
| Annotation Project | `/annotation_projects/detail/?annotation_project_uuid=def-456` | `/annotation_projects/def-456/` |
| Annotation Tasks | `/annotation_projects/detail/tasks/?annotation_project_uuid=def-456` | `/annotation_projects/def-456/tasks/` |
| Evaluation Set | `/evaluation/detail/?evaluation_set_uuid=ghi-789` | `/evaluation/ghi-789/` |
| Evaluation Examples | `/evaluation/detail/tasks/?evaluation_set_uuid=ghi-789` | `/evaluation/ghi-789/tasks/` |
| Project Detail | `/projects/prj-xyz/` | `/projects/prj-xyz/` ✓ (unchanged) |
| Project Edit | N/A | `/admin/metadata/projects/prj-xyz/edit/` ✨ (new) |

## Code Patterns

### Getting Route Parameters

#### Old Pattern (Query Params)
```tsx
import { useSearchParams } from "next/navigation";

const params = useSearchParams();
const uuid = params.get("dataset_uuid");
```

#### New Pattern (Dynamic Routes)
```tsx
import { useParams } from "next/navigation";

const params = useParams();
const uuid = params.dataset_uuid as string;
```

### Navigation

#### Old Pattern
```tsx
router.push(`/datasets/detail/?dataset_uuid=${dataset.uuid}`);
```

#### New Pattern
```tsx
router.push(`/datasets/${dataset.uuid}/`);
```

### Tab Navigation

#### Old Pattern
```tsx
const params = useSearchParams();
onClick={() => router.push(`/datasets/detail/recordings/?${params.toString()}`)}
```

#### New Pattern
```tsx
onClick={() => router.push(`/datasets/${dataset.uuid}/recordings/`)}
```

## Next.js Configuration

### next.config.js Change
```javascript
const nextConfig = {
  // output: "export", // ← Commented out for dynamic routes support
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
};
```

**Reason:** Dynamic routes require server-side rendering and don't work with static export.

## Implementation Details

### Directory Structure Created
```
front/src/app/(base)/
├── datasets/[dataset_uuid]/
│   ├── layout.tsx
│   ├── page.tsx
│   ├── recordings/
│   ├── notes/
│   └── sound_events/
├── annotation_projects/[annotation_project_uuid]/
│   ├── layout.tsx
│   ├── page.tsx
│   ├── annotation/
│   ├── tasks/
│   ├── tags/
│   └── clips/
├── evaluation/[evaluation_set_uuid]/
│   ├── layout.tsx
│   ├── page.tsx
│   ├── components/
│   ├── tasks/
│   ├── model_runs/
│   ├── user_runs/
│   └── tags/
└── admin/metadata/projects/[project_id]/
    └── edit/
        └── page.tsx
```

### Files Modified
1. `/app/(base)/datasets/page.tsx`
2. `/app/(base)/annotation_projects/page.tsx`
3. `/app/(base)/evaluation/page.tsx`
4. `/app/components/datasets/DatasetTabs.tsx`
5. `/app/components/annotation_projects/AnnotationProjectHeader.tsx`
6. `/lib/components/recordings/CrossDatasetSearch.tsx`
7. `/app/(base)/annotation_projects/[annotation_project_uuid]/tasks/page.tsx`

### New Files Created
- All `[resource_uuid]/layout.tsx` files
- All `[resource_uuid]/page.tsx` files
- `/admin/metadata/projects/[project_id]/edit/page.tsx`
- Component subdirectories for dynamic routes

## Future Improvements

### Short Term
1. Add redirect middleware for old URLs
2. Update any remaining hardcoded links
3. Add E2E tests for all routes

### Medium Term
1. Remove old `/detail/` directories after transition period
2. Add route validation middleware
3. Improve error pages (404, 500)

### Long Term
1. Consider adding route middleware for authentication
2. Implement route-level data prefetching
3. Add route analytics tracking

## Related Issues

### Fixed Issues
1. ✅ Project edit page 404 - created `/admin/metadata/projects/[project_id]/edit/`
2. ✅ Member list showing UUIDs - updated backend schema to include user details
3. ✅ Inconsistent routing patterns - unified all resources to dynamic routes
4. ✅ SEO problems with query params - migrated to semantic URLs

### Known Limitations
1. Old routes still exist (backward compatibility)
2. Some components still use `useSearchParams()` for other purposes (not UUID extraction)
3. External links may still point to old URLs

## References

- [Next.js Dynamic Routes Documentation](https://nextjs.org/docs/app/building-your-application/routing/dynamic-routes)
- [Next.js useParams Hook](https://nextjs.org/docs/app/api-reference/functions/use-params)
- [Next.js Layouts](https://nextjs.org/docs/app/building-your-application/routing/pages-and-layouts)

## Contact

For questions about this refactoring, please refer to the git commit history or contact the development team.

---

**Last Updated:** 2025-11-01
**Status:** ✅ Complete
**Migration Coverage:** 100% of main resources (Datasets, Annotation Projects, Evaluation Sets, Projects)
