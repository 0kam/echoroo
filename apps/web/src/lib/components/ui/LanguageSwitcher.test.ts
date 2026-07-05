import { afterEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';

/**
 * Component test for LanguageSwitcher.svelte (W5-7 baseline pattern).
 * See ConfirmDialog.test.ts for the rationale behind the `vi.mock('svelte', ...)`
 * shim below.
 */
vi.mock('svelte', async () => {
  // @ts-expect-error Svelte does not publish declarations for this runtime path.
  return await import('../../../../node_modules/svelte/src/index-client.js');
});

vi.mock('$app/stores', () => ({
  page: writable({ url: new URL('http://localhost/en/dashboard') }),
}));

const { setLocaleMock } = vi.hoisted(() => ({ setLocaleMock: vi.fn() }));

vi.mock('$lib/paraglide/runtime', async (importOriginal) => {
  const actual = await importOriginal<typeof import('$lib/paraglide/runtime')>();
  return {
    ...actual,
    setLocale: setLocaleMock,
  };
});

import LanguageSwitcher from './LanguageSwitcher.svelte';

type MountedComponent = ReturnType<Awaited<typeof import('svelte')>['mount']>;

let component: MountedComponent | null = null;

async function renderSwitcher() {
  const { mount, tick } = await import('svelte');
  const target = document.createElement('div');
  document.body.appendChild(target);
  component = mount(LanguageSwitcher, { target, props: {} }) as MountedComponent;
  await tick();
  return target;
}

afterEach(async () => {
  if (component) {
    const { unmount } = await import('svelte');
    await unmount(component);
    component = null;
  }
  document.body.innerHTML = '';
  setLocaleMock.mockClear();
});

describe('LanguageSwitcher', () => {
  it('renders both locales, marking the active one as non-interactive', async () => {
    await renderSwitcher();

    const activeMarker = document.querySelector('[aria-current="true"]');
    expect(activeMarker?.textContent?.trim()).toBe('English');

    const switchButtons = Array.from(document.querySelectorAll('button')).map((b) => b.textContent?.trim());
    expect(switchButtons).toEqual(['日本語']);
  });

  it('calls setLocale with the target locale when a non-active locale is clicked', async () => {
    await renderSwitcher();

    const jaButton = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === '日本語',
    );
    expect(jaButton).toBeDefined();

    // jsdom does not implement real navigation; stub window.location.href
    // assignment so clicking doesn't log a jsdom "not implemented" warning.
    const originalHref = window.location.href;
    const hrefSetter = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, set href(value: string) {
        hrefSetter(value);
      } },
    });

    jaButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

    expect(setLocaleMock).toHaveBeenCalledWith('ja', { reload: false });
    expect(hrefSetter).toHaveBeenCalledTimes(1);

    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, href: originalHref },
    });
  });
});
