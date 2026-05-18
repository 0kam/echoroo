import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resendVerificationEmail } from '$lib/api/auth';
import type { User } from '$lib/types';

import ProfilePage from './+page.svelte';

vi.mock('svelte', async () => {
  // @ts-expect-error Svelte does not publish declarations for this runtime path.
  return await import('../../../../node_modules/svelte/src/index-client.js');
});

vi.mock('$lib/api/auth', () => ({
  resendVerificationEmail: vi.fn(),
}));

vi.mock('$lib/api/users', () => ({
  updateUser: vi.fn(),
}));

vi.mock('$lib/paraglide/runtime', async (importOriginal) => {
  const actual = await importOriginal<typeof import('$lib/paraglide/runtime')>();
  return {
    ...actual,
    getLocale: () => 'en',
    localizeHref: (href: string) => href,
  };
});

const { mount, tick, unmount } = await import('svelte');
const { authStore } = await import('$lib/stores/auth.svelte');

type MountedComponent = ReturnType<typeof mount>;

const resendVerificationEmailMock = vi.mocked(resendVerificationEmail);

let component: MountedComponent | null = null;

type LegacyProfileUserResponse = User & {
  is_verified: boolean;
};

const baseUser = {
  id: 'profile-user',
  email: 'profile@example.com',
  display_name: 'Profile User',
  organization: null,
  is_active: true,
  is_superuser: false,
  email_verified_at: null,
  created_at: '2026-05-18T00:00:00Z',
  last_login_at: null,
} satisfies User;

function renderProfilePage(user: User | LegacyProfileUserResponse) {
  authStore.setUser(user);
  const target = document.createElement('div');
  document.body.appendChild(target);
  component = mount(ProfilePage, {
    target,
  });
  return target;
}

async function flushComponentUpdates() {
  await tick();
  await Promise.resolve();
  await tick();
}

async function waitFor(assertion: () => void) {
  let lastError: unknown;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      assertion();
      return;
    } catch (err) {
      lastError = err;
      await flushComponentUpdates();
    }
  }
  throw lastError;
}

function bodyText() {
  return document.body.textContent ?? '';
}

function findButton(name: string): HTMLButtonElement {
  const button = Array.from(document.querySelectorAll('button')).find((candidate) =>
    candidate.textContent?.includes(name)
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Button not found: ${name}`);
  }
  return button;
}

describe('profile email verification state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authStore.clearUser();
  });

  afterEach(async () => {
    if (component) {
      await unmount(component);
      component = null;
    }
    authStore.clearUser();
    document.body.innerHTML = '';
  });

  it('renders an unverified account state from null email_verified_at even when legacy is_verified is true', () => {
    renderProfilePage({
      ...baseUser,
      email_verified_at: null,
      is_verified: true,
    } satisfies LegacyProfileUserResponse);

    expect(bodyText()).toContain('Unverified');
    expect(bodyText()).not.toContain('Verified');
    expect(bodyText()).toContain('profile@example.com');
  });

  it('renders a verified account state when email_verified_at has a timestamp', () => {
    renderProfilePage({
      ...baseUser,
      email_verified_at: '2026-05-18T01:02:03Z',
      is_verified: false,
    } satisfies LegacyProfileUserResponse);

    expect(bodyText()).toContain('Verified');
    expect(bodyText()).not.toContain('Unverified');
  });

  it('offers resend for unverified accounts and shows success after resend succeeds', async () => {
    resendVerificationEmailMock.mockResolvedValueOnce({ message: 'Accepted' });
    renderProfilePage({
      ...baseUser,
      email_verified_at: null,
      is_verified: true,
    } satisfies LegacyProfileUserResponse);

    findButton('Resend Verification Email').click();

    await waitFor(() => {
      expect(resendVerificationEmailMock).toHaveBeenCalledTimes(1);
      expect(bodyText()).toContain('Verification email sent successfully!');
    });
  });

  it('shows an error state when resend fails', async () => {
    resendVerificationEmailMock.mockRejectedValueOnce(new Error('rate limited'));
    renderProfilePage({
      ...baseUser,
      email_verified_at: null,
      is_verified: true,
    } satisfies LegacyProfileUserResponse);

    findButton('Resend Verification Email').click();

    await waitFor(() => {
      expect(resendVerificationEmailMock).toHaveBeenCalledTimes(1);
      expect(bodyText()).toContain('Failed to resend verification email. Please try again.');
    });
  });
});
