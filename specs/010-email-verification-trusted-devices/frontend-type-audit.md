# Frontend Type Audit — `is_verified` Replacement

**Date**: 2026-05-18
**Feature**: 010 Email Verification and Trusted Devices

## Target Shape

Frontend user/account state should use:

```ts
email_verified_at: string | null;
```

`null` means the current account email is not verified. A non-null ISO timestamp means the current email was verified at that time.

## Current `is_verified` Usage

| File | Current usage | Replacement |
|------|---------------|-------------|
| `apps/web/src/lib/types/index.ts` | `User.is_verified: boolean` and `UserUpdateRequest.is_verified?: boolean` | Replace user response field with `email_verified_at: string | null`. Remove user-update support unless a backend admin contract explicitly supports verification changes. |
| `apps/web/src/routes/(app)/dashboard/+page.svelte` | Shows verified/unverified badge from `authStore.user.is_verified`. | Derive `const emailVerified = authStore.user.email_verified_at !== null`. |
| `apps/web/src/routes/(app)/profile/+page.svelte` | Shows verified/unverified status from `authStore.user?.is_verified`. | Show timestamp-aware account state and add resend affordance in US2. |
| `apps/web/src/routes/(admin)/admin/users/+page.svelte` | Shows verification badge from `user.is_verified`. | Render from `user.email_verified_at`; admin mutation behavior must not silently mark users verified unless backend contract defines it. |
| `apps/web/tests/e2e/permissions/smoke-matrix.spec.ts` | Mock current-user responses omit verification timestamp and include older user-shape assumptions. | Add `email_verified_at` to current-user fixtures where the authenticated UI expects a verified account. |

## Adjacent Auth Types

- `apps/web/src/lib/api/web-auth.ts` currently defines `LoginState = '2fa_setup_required' | '2fa_required'`; US4 must add `complete`.
- Login and 2FA setup pages should add `trust_device` only to second-factor submit payloads, not the initial password login request.
- `apps/web/src/lib/stores/auth.svelte.ts` should persist only the typed `User` state; no localStorage token persistence should be added.

## Migration Plan

1. Add failing auth-store/user-type tests for `email_verified_at` in T036.
2. Update `User` and related response fixtures in T039/T046.
3. Replace badge derivations in dashboard/profile/admin pages as part of US2 UI work.
4. Add unverified account messaging and resend behavior on profile after backend resend support exists.
5. Add trusted-device API and UI types in US3/US4 without reintroducing boolean verification state.

## Done Criteria

- `rg "is_verified" apps/web/src apps/web/tests` has no product-code references except historical comments or intentionally skipped legacy fixtures.
- `email_verified_at` is present in `User` and current-user test fixtures.
- Frontend tests cover `email_verified_at === null` and non-null timestamp rendering.
