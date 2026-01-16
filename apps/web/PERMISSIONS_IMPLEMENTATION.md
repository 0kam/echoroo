# Project Member Permissions Implementation

## Overview
This document describes the implementation of role-based permissions for project members (User Story 3: T093-T095).

## Implemented Features

### 1. Permission Store (T094)
**File**: `/apps/web/src/lib/stores/permissions.ts`

A centralized permission management system that:
- Defines role types: `admin`, `member`, `viewer`
- Provides permission calculation based on role and ownership
- Includes helper functions for role descriptions and display names

**Role Permissions**:
- **Admin**: Can manage members and edit project settings
- **Member**: Can view and edit project data
- **Viewer**: Can only view project data
- **Owner**: Has all permissions including project deletion

### 2. Role Selector with Tooltips (T093)
**File**: `/apps/web/src/routes/(app)/projects/[id]/members/+page.svelte`

Enhanced member management page with:
- Role selection dropdown with information tooltips
- Role descriptions on hover
- Owner role protection (cannot be changed)
- Confirmation dialog for role changes
- Visual feedback during role updates

**Features**:
- Info icon next to role selector shows permission details
- Confirmation dialog displays old and new roles
- Clear description of what each role can do

### 3. Permission-Based UI Visibility (T094)

**Updated Pages**:

#### Project Detail Page (`/apps/web/src/routes/(app)/projects/[id]/+page.svelte`)
- Settings button visible only to admins and owner
- Delete button visible only to owner
- Manage members button visible only to admins and owner

#### Project Settings Page (`/apps/web/src/routes/(app)/projects/[id]/settings/+page.svelte`)
- Access restricted to admins and owner
- Shows "Access Denied" message for non-admin members
- Loads member data to determine permissions

#### Member Management Page (`/apps/web/src/routes/(app)/projects/[id]/members/+page.svelte`)
- Access restricted to admins and owner
- Add member functionality only for admins
- Role change functionality only for admins
- Remove member functionality only for admins
- Owner role cannot be modified

### 4. E2E Tests (T095)
**File**: `/apps/web/tests/e2e/permissions.spec.ts`

Comprehensive test suite covering:

**Test Cases**:
1. `admin can change member role` - Verifies admin can modify member roles with confirmation
2. `member cannot access settings page` - Ensures members cannot access settings
3. `viewer cannot edit project` - Ensures viewers have read-only access
4. `owner can delete project` - Verifies only owner can delete projects
5. `admin cannot delete project` - Ensures admins cannot delete projects
6. `role tooltips show correct descriptions` - Verifies tooltip functionality
7. `owner role cannot be changed` - Ensures owner role is protected
8. `role change confirmation shows permission details` - Verifies confirmation dialog
9. `member cannot add or remove members` - Ensures member role restrictions
10. `viewer cannot see manage members link` - Ensures UI visibility based on role

## Permission Matrix

| Action | Owner | Admin | Member | Viewer |
|--------|-------|-------|--------|--------|
| View project | ✓ | ✓ | ✓ | ✓ |
| Edit project data | ✓ | ✓ | ✓ | ✗ |
| Edit project settings | ✓ | ✓ | ✗ | ✗ |
| Manage members | ✓ | ✓ | ✗ | ✗ |
| Add members | ✓ | ✓ | ✗ | ✗ |
| Remove members | ✓ | ✓ | ✗ | ✗ |
| Change member roles | ✓ | ✓ | ✗ | ✗ |
| Delete project | ✓ | ✗ | ✗ | ✗ |

## User Experience Improvements

1. **Visual Feedback**: Role changes show confirmation dialogs with clear descriptions
2. **Tooltips**: Hover tooltips explain what each role can do
3. **Access Control**: Clear "Access Denied" messages when permissions are insufficient
4. **UI Hiding**: Buttons and actions are hidden when user lacks permission
5. **Owner Protection**: Owner role cannot be changed or removed

## Accessibility

All interactive elements include:
- Proper ARIA labels for icon buttons
- Keyboard navigation support
- Role and tabindex attributes on modal overlays
- Escape key support for closing dialogs

## Type Safety

- Strict TypeScript types for roles and permissions
- Type-safe permission calculation functions
- Svelte 5 runes for reactive state management

## Testing

Run type checking:
```bash
cd apps/web
npm run check
```

Run E2E tests:
```bash
cd apps/web
npx playwright test tests/e2e/permissions.spec.ts
```

## Files Modified/Created

**Created**:
- `/apps/web/src/lib/stores/permissions.ts` - Permission management store
- `/apps/web/tests/e2e/permissions.spec.ts` - E2E tests for permissions

**Modified**:
- `/apps/web/src/routes/(app)/projects/[id]/members/+page.svelte` - Enhanced role management
- `/apps/web/src/routes/(app)/projects/[id]/settings/+page.svelte` - Admin permission check
- `/apps/web/src/routes/(app)/projects/[id]/+page.svelte` - UI visibility based on permissions

## Future Enhancements

1. **Granular Permissions**: Add more fine-grained permissions (e.g., can_upload, can_annotate)
2. **Custom Roles**: Allow project owners to define custom roles
3. **Permission Audit Log**: Track permission changes and access attempts
4. **Bulk Role Updates**: Change roles for multiple members at once
5. **Role Templates**: Pre-defined permission sets for common use cases
