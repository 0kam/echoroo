import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ComponentProps } from 'svelte';

/**
 * Component test for ConfirmDialog.svelte (W5-7 baseline pattern).
 *
 * @testing-library/svelte is NOT installed in this project (see
 * package.json devDependencies) so this follows the same low-level pattern
 * already used by src/routes/(auth)/login/login-trusted-device.spec.ts:
 * mount the compiled Svelte 5 component directly via `svelte`'s `mount`/
 * `unmount` runtime API and assert on the resulting DOM.
 *
 * The `vi.mock('svelte', ...)` below is required because vite/vitest
 * otherwise resolves the `svelte` package to its server-side build in this
 * test environment, and `mount()` throws `lifecycle_function_unavailable`
 * ("mount(...) is not available on the server") when that happens. Forcing
 * the client runtime module makes `mount`/`unmount`/`tick` behave like a
 * real browser render.
 */
vi.mock('svelte', async () => {
  // @ts-expect-error Svelte does not publish declarations for this runtime path.
  return await import('../../../../node_modules/svelte/src/index-client.js');
});

import ConfirmDialog from './ConfirmDialog.svelte';

type MountedComponent = ReturnType<Awaited<typeof import('svelte')>['mount']>;

let component: MountedComponent | null = null;

async function renderDialog(props: ComponentProps<typeof ConfirmDialog>) {
  const { mount, tick } = await import('svelte');
  const target = document.createElement('div');
  document.body.appendChild(target);
  component = mount(ConfirmDialog, { target, props }) as MountedComponent;
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
});

describe('ConfirmDialog', () => {
  it('renders nothing when isOpen is false', async () => {
    await renderDialog({
      isOpen: false,
      title: 'Delete recording',
      message: 'This cannot be undone.',
      onConfirm: vi.fn(),
    });

    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it('renders title, message, and default button labels when open', async () => {
    await renderDialog({
      isOpen: true,
      title: 'Delete recording',
      message: 'This cannot be undone.',
      onConfirm: vi.fn(),
    });

    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(document.body.textContent).toContain('Delete recording');
    expect(document.body.textContent).toContain('This cannot be undone.');
    const buttons = Array.from(document.querySelectorAll('button')).map((b) => b.textContent?.trim());
    expect(buttons).toContain('Confirm');
    expect(buttons).toContain('Cancel');
  });

  it('renders custom confirm/cancel text and warning items', async () => {
    await renderDialog({
      isOpen: true,
      title: 'Delete project',
      message: 'All data will be lost.',
      confirmText: 'Delete forever',
      cancelText: 'Keep it',
      warningItems: ['5 recordings', '2 datasets'],
      errorMessage: 'Something went wrong',
      onConfirm: vi.fn(),
    });

    const buttons = Array.from(document.querySelectorAll('button')).map((b) => b.textContent?.trim());
    expect(buttons).toContain('Delete forever');
    expect(buttons).toContain('Keep it');
    expect(document.body.textContent).toContain('5 recordings');
    expect(document.body.textContent).toContain('2 datasets');
    expect(document.body.textContent).toContain('Something went wrong');
  });

  it('applies the danger styling class to the confirm button when isDanger is true', async () => {
    await renderDialog({
      isOpen: true,
      title: 'Danger',
      message: 'Careful.',
      isDanger: true,
      onConfirm: vi.fn(),
    });

    const confirmButton = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Confirm',
    );
    expect(confirmButton?.className).toContain('bg-danger');
  });

  it('invokes onConfirm when the confirm button is clicked', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    await renderDialog({
      isOpen: true,
      title: 'Confirm action',
      message: 'Are you sure?',
      onConfirm,
    });

    const confirmButton = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Confirm',
    );
    confirmButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    const { tick } = await import('svelte');
    await tick();
    await Promise.resolve();

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('invokes onCancel when the cancel button is clicked', async () => {
    const onCancel = vi.fn();
    await renderDialog({
      isOpen: true,
      title: 'Confirm action',
      message: 'Are you sure?',
      onConfirm: vi.fn(),
      onCancel,
    });

    const cancelButton = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Cancel',
    );
    cancelButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
