import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { User } from '$lib/types';

vi.mock('$app/navigation', () => ({
  goto: vi.fn(),
}));

vi.mock('$lib/paraglide/runtime', () => ({
  localizeHref: (href: string) => href,
}));

vi.mock('$lib/api/client', () => ({
  apiClient: {
    getAccessToken: vi.fn(() => 'access-token'),
    refreshToken: vi.fn(),
    get: vi.fn(),
    post: vi.fn(),
    setAccessToken: vi.fn(),
    requestRaw: vi.fn(),
    onRefreshFailed: null,
  },
}));

vi.mock('$lib/api/web-auth', () => ({
  logoutUser: vi.fn(),
}));

const { authStore } = await import('./auth.svelte');
const { apiClient } = await import('$lib/api/client');

const apiGetMock = vi.mocked(apiClient.get);

type LegacyCurrentUserResponse = User & {
  is_verified: boolean;
};

const unverifiedUser = {
  id: 'user-unverified',
  email: 'unverified@example.com',
  display_name: 'Unverified User',
  organization: null,
  is_active: true,
  is_superuser: false,
  is_verified: true,
  email_verified_at: null,
  created_at: '2026-05-18T00:00:00Z',
  last_login_at: null,
} satisfies LegacyCurrentUserResponse;

const verifiedUser = {
  id: 'user-verified',
  email: 'verified@example.com',
  display_name: 'Verified User',
  organization: null,
  is_active: true,
  is_superuser: false,
  is_verified: false,
  email_verified_at: '2026-05-18T01:02:03Z',
  created_at: '2026-05-18T00:00:00Z',
  last_login_at: null,
} satisfies LegacyCurrentUserResponse;

describe('auth store email verification state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authStore.clearUser();
  });

  it('stores an unverified current user from email_verified_at instead of legacy is_verified', async () => {
    apiGetMock.mockResolvedValueOnce(unverifiedUser);

    await authStore.initialize();

    expect(apiGetMock).toHaveBeenCalledWith('/web-api/v1/users/me');
    expect(authStore.user?.email_verified_at).toBeNull();
    expect(authStore.user).not.toHaveProperty('is_verified');
    expect(authStore.isAuthenticated).toBe(true);
  });

  it('stores a verified current user when email_verified_at has a timestamp', async () => {
    apiGetMock.mockResolvedValueOnce(verifiedUser);

    await authStore.initialize();

    expect(authStore.user?.email_verified_at).toBe('2026-05-18T01:02:03Z');
    expect(authStore.user).not.toHaveProperty('is_verified');
    expect(authStore.isAuthenticated).toBe(true);
  });
});
