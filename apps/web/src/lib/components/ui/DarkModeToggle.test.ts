import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Component test for DarkModeToggle.svelte (W5-7 baseline pattern).
 * See ConfirmDialog.test.ts for the rationale behind the `vi.mock('svelte', ...)`
 * shim below — it forces the client (browser) runtime build so `mount()`
 * works under vitest's jsdom environment.
 */
vi.mock('svelte', async () => {
  // @ts-expect-error Svelte does not publish declarations for this runtime path.
  return await import('../../../../node_modules/svelte/src/index-client.js');
});

// vitest transforms modules in SSR mode by default, so SvelteKit's
// `$app/environment` `browser` constant resolves to `false` here (unlike a
// real browser bundle). DarkModeToggle gates all of its DOM/localStorage
// logic behind `if (browser)`, so force it to `true` to exercise that code
// path under test.
vi.mock('$app/environment', () => ({
  browser: true,
  building: false,
  dev: true,
  version: 'test',
}));

import DarkModeToggle from './DarkModeToggle.svelte';

type MountedComponent = ReturnType<Awaited<typeof import('svelte')>['mount']>;

let component: MountedComponent | null = null;

async function renderToggle() {
  const { mount, tick } = await import('svelte');
  const target = document.createElement('div');
  document.body.appendChild(target);
  component = mount(DarkModeToggle, { target, props: {} }) as MountedComponent;
  await tick();
  return target;
}

beforeEach(() => {
  document.documentElement.classList.remove('dark');
  localStorage.clear();
});

afterEach(async () => {
  if (component) {
    const { unmount } = await import('svelte');
    await unmount(component);
    component = null;
  }
  document.body.innerHTML = '';
  document.documentElement.classList.remove('dark');
  localStorage.clear();
});

describe('DarkModeToggle', () => {
  it('renders a single toggle button defaulting to light-mode labelling', async () => {
    await renderToggle();

    const button = document.querySelector('button');
    expect(button).not.toBeNull();
    expect(button?.getAttribute('aria-label')).toBe('Switch to dark mode');
  });

  it('reflects an existing "dark" class on <html> as already-dark state', async () => {
    document.documentElement.classList.add('dark');
    await renderToggle();

    const button = document.querySelector('button');
    expect(button?.getAttribute('aria-label')).toBe('Switch to light mode');
  });

  it('toggles the "dark" class on <html> and persists the choice on click', async () => {
    await renderToggle();
    const { tick } = await import('svelte');

    const button = document.querySelector('button');
    expect(document.documentElement.classList.contains('dark')).toBe(false);

    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();

    expect(document.documentElement.classList.contains('dark')).toBe(true);
    expect(localStorage.getItem('echoroo-dark-mode')).toBe('true');
    expect(document.querySelector('button')?.getAttribute('aria-label')).toBe('Switch to light mode');

    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();

    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(localStorage.getItem('echoroo-dark-mode')).toBe('false');
  });
});
