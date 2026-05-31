import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';

import { loginUser } from '$lib/api/web-auth';
import type { LoginResponse, LoginState } from '$lib/api/web-auth';
import { apiClient } from '$lib/api/client';
import { authStore } from '$lib/stores/auth.svelte';
import type { User } from '$lib/types';

import LoginPage from './+page.svelte';

vi.mock('svelte', async () => {
  // @ts-expect-error Svelte does not publish declarations for this runtime path.
  return await import('../../../../node_modules/svelte/src/index-client.js');
});

const { gotoMock } = vi.hoisted(() => ({
  gotoMock: vi.fn(),
}));

vi.mock('$app/navigation', () => ({
  goto: gotoMock,
}));

vi.mock('$app/stores', () => ({
  page: writable({
    url: new URL('http://localhost/login'),
  }),
}));

vi.mock('$lib/api/web-auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('$lib/api/web-auth')>();
  return {
    ...actual,
    loginUser: vi.fn(),
    challengeTwoFactor: vi.fn(),
  };
});

vi.mock('$lib/components/Captcha.svelte', () => ({
  default: () => undefined,
}));

vi.mock('$lib/components/ui/LanguageSwitcher.svelte', () => ({
  default: () => undefined,
}));

vi.mock('$lib/components/ui/DarkModeToggle.svelte', () => ({
  default: () => undefined,
}));

vi.mock('$lib/paraglide/runtime', async (importOriginal) => {
  const actual = await importOriginal<typeof import('$lib/paraglide/runtime')>();
  return {
    ...actual,
    localizeHref: (href: string) => href,
  };
});

const { mount, tick, unmount } = await import('svelte');

type MountedComponent = ReturnType<typeof mount>;

const loginUserMock = vi.mocked(loginUser);

let component: MountedComponent | null = null;

const currentUser = {
  id: 'trusted-device-user',
  email: 'trusted@example.com',
  display_name: 'Trusted Device User',
  organization: null,
  is_active: true,
  is_superuser: false,
  created_at: '2026-05-18T00:00:00Z',
  last_login_at: '2026-05-18T00:00:00Z',
} satisfies User;

async function renderLoginPage() {
  const target = document.createElement('div');
  document.body.appendChild(target);
  component = mount(LoginPage, { target });
  await flushComponentUpdates();
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

function setInputValue(selector: string, value: string) {
  const input = document.querySelector<HTMLInputElement>(selector);
  if (!input) {
    throw new Error(`Input not found: ${selector}`);
  }
  input.value = value;
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

function submitCredentials() {
  const form = document.querySelector('form');
  if (!form) {
    throw new Error('Login form not found');
  }
  form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
}

describe('login trusted-device complete state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authStore.clearUser();
    apiClient.setAccessToken(null);
  });

  afterEach(async () => {
    if (component) {
      await unmount(component);
      component = null;
    }
    authStore.clearUser();
    apiClient.setAccessToken(null);
    document.body.innerHTML = '';
  });

  it('treats a complete login response as signed in without rendering the 2FA form', async () => {
    const completeState: LoginState = 'complete';
    const completeLoginResponse = {
      login_state: completeState,
      access_token: 'access-token-from-trusted-device',
      expires_in: 900,
    } satisfies LoginResponse;

    loginUserMock.mockResolvedValueOnce(completeLoginResponse);
    const setAccessTokenSpy = vi.spyOn(apiClient, 'setAccessToken');
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValueOnce(currentUser);
    const setUserSpy = vi.spyOn(authStore, 'setUser');

    await renderLoginPage();
    setInputValue('input[name="email"]', 'trusted@example.com');
    setInputValue('input[name="password"]', 'correct-password');
    submitCredentials();

    await waitFor(() => {
      expect(loginUserMock).toHaveBeenCalledWith({
        email: 'trusted@example.com',
        password: 'correct-password',
      });
      expect(setAccessTokenSpy).toHaveBeenCalledWith('access-token-from-trusted-device');
      expect(getSpy).toHaveBeenCalledWith('/web-api/v1/users/me');
      expect(setUserSpy).toHaveBeenCalledWith(currentUser);
      expect(gotoMock).toHaveBeenCalledWith('/dashboard');
    });

    expect(document.querySelector('[data-testid="two-factor-form"]')).toBeNull();
  });
});
