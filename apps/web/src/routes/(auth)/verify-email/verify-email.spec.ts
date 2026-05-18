import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { verifyEmail, resendVerificationEmail } from '$lib/api/auth';
import { ApiError } from '$lib/api/client';

import VerifyEmailPage from './+page.svelte';

vi.mock('svelte', async () => {
  // @ts-expect-error Svelte does not publish declarations for this runtime path.
  return await import('../../../../node_modules/svelte/src/index-client.js');
});

vi.mock('$lib/api/auth', () => ({
  verifyEmail: vi.fn(),
  resendVerificationEmail: vi.fn(),
}));

vi.mock('$lib/paraglide/runtime', () => ({
  localizeHref: (href: string) => href,
}));

const { mount, tick, unmount } = await import('svelte');

type MountedComponent = ReturnType<typeof mount>;

const verifyEmailMock = vi.mocked(verifyEmail);
const resendVerificationEmailMock = vi.mocked(resendVerificationEmail);

let component: MountedComponent | null = null;

function apiError(message: string, code: string): ApiError {
  return new ApiError(message, 400, message, code, {
    error: code,
    detail: message,
  });
}

function renderVerifyEmailPage(data: { token?: string | null; registered?: boolean }) {
  const pageData = {
    pathname: '/verify-email',
    hasSession: false,
    token: data.token ?? null,
    registered: data.registered ?? false,
  };
  const target = document.createElement('div');
  document.body.appendChild(target);
  component = mount(VerifyEmailPage, {
    target,
    props: {
      data: pageData,
    },
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

describe('verify-email page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(async () => {
    if (component) {
      await unmount(component);
      component = null;
    }
    document.body.innerHTML = '';
    vi.useRealTimers();
  });

  it('verifies a valid token and renders the success state', async () => {
    verifyEmailMock.mockResolvedValueOnce({ message: 'Email verified' });

    renderVerifyEmailPage({ token: 'valid-token' });

    await waitFor(() => {
      expect(verifyEmailMock).toHaveBeenCalledWith('valid-token');
      expect(bodyText()).toContain('Email verified successfully!');
      expect(bodyText()).toContain('Your email address has been verified.');
    });
    expect(document.querySelector<HTMLAnchorElement>('a[href="/login"]')?.textContent).toContain(
      'Go to Login'
    );
  });

  it('renders a clear invalid-token state without exposing account existence', async () => {
    verifyEmailMock.mockRejectedValueOnce(
      apiError('Verification token could not be accepted.', 'ERR_EMAIL_VERIFICATION_TOKEN_INVALID')
    );

    renderVerifyEmailPage({ token: 'tampered-token' });

    await waitFor(() => {
      expect(bodyText()).toContain('Verification link is invalid');
      expect(bodyText()).toContain('Request a new verification email or return to login.');
    });
    expect(bodyText()).not.toContain('tampered-token');
    expect(document.querySelector<HTMLAnchorElement>('a[href="/login"]')?.textContent).toContain(
      'Back to Login'
    );
  });

  it('renders an expired-token state with a resend affordance', async () => {
    verifyEmailMock.mockRejectedValueOnce(
      apiError('Verification token could not be accepted.', 'ERR_EMAIL_VERIFICATION_TOKEN_EXPIRED')
    );
    resendVerificationEmailMock.mockResolvedValueOnce({ message: 'Accepted' });

    renderVerifyEmailPage({ token: 'expired-token' });

    await waitFor(() => {
      expect(bodyText()).toContain('Verification link has expired');
      expect(bodyText()).toContain('Send a fresh verification email to continue.');
    });

    findButton('Resend Verification Email').click();
    await waitFor(() => {
      expect(resendVerificationEmailMock).toHaveBeenCalledTimes(1);
      expect(bodyText()).toContain('Verification email sent successfully!');
    });
  });

  it('renders a reused-token state with a resend affordance', async () => {
    verifyEmailMock.mockRejectedValueOnce(
      apiError(
        'Verification token could not be accepted.',
        'ERR_EMAIL_VERIFICATION_TOKEN_CONSUMED'
      )
    );

    renderVerifyEmailPage({ token: 'already-used-token' });

    await waitFor(() => {
      expect(bodyText()).toContain('Verification link was already used');
      expect(bodyText()).toContain('Use the most recent verification email or request a new one.');
    });
    expect(findButton('Resend Verification Email').disabled).toBe(false);
  });

  it('maps backend verification error codes to the same reused-token state', async () => {
    verifyEmailMock.mockRejectedValueOnce(
      apiError('Verification token could not be accepted.', 'ERR_EMAIL_VERIFICATION_REUSED')
    );

    renderVerifyEmailPage({ token: 'backend-reused-token' });

    await waitFor(() => {
      expect(bodyText()).toContain('Verification link was already used');
      expect(bodyText()).toContain('Use the most recent verification email or request a new one.');
    });
    expect(bodyText()).not.toContain('backend-reused-token');
  });

  it('shows the registered-user resend affordance and cooldown after resend succeeds', async () => {
    vi.useFakeTimers();
    resendVerificationEmailMock.mockResolvedValueOnce({ message: 'Accepted' });

    renderVerifyEmailPage({ registered: true });

    expect(verifyEmailMock).not.toHaveBeenCalled();
    expect(bodyText()).toContain('Check your email!');

    findButton('Resend Verification Email').click();
    await waitFor(() => {
      expect(resendVerificationEmailMock).toHaveBeenCalledTimes(1);
      expect(bodyText()).toContain('Verification email sent successfully!');
      expect(bodyText()).toContain('Resend in 60s');
    });

    vi.advanceTimersByTime(1000);
    await waitFor(() => {
      expect(bodyText()).toContain('Resend in 59s');
    });
  });
});
